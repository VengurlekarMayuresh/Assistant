"""
LangGraph Agent Graph — RepoMind AI.

Multi-node agentic pipeline:
  Planner → Explorer (loop) → Synthesizer

Cache-first strategy:
  1. Planner checks Qdrant semantic search for cached KO summaries.
  2. If high-confidence hit → skip Explorer, go straight to Synthesizer.
  3. Planner also queries Neo4j to expand file context via import graph.
  4. Explorer checks MongoDB file cache before hitting GitHub.
  5. Synthesizer spawns background prefetch task for follow-up files.
"""
import json
import logging
import re
import asyncio
from typing import Dict, Any, List, Optional
from typing_extensions import TypedDict
from langgraph.graph import StateGraph, END
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import SystemMessage, HumanMessage
from bson import ObjectId

from app.config import settings
from app.services.github_service import GitHubService

logger = logging.getLogger(__name__)


# ── State ──────────────────────────────────────────────────────────────────

class AgentState(TypedDict):
    query: str
    owner: str
    repo: str
    branch: str
    file_list: List[str]
    languages: Dict[str, Any]
    frameworks: List[str]
    plan: List[str]
    step_findings: List[str]
    current_step_index: int
    files_cache: Dict[str, str]
    session_id: str
    final_answer: str
    repo_id: str          # MongoDB repository _id string


# ── LLM factory ───────────────────────────────────────────────────────────

def get_llm():
    return ChatGoogleGenerativeAI(
        model=settings.GOOGLE_MODEL,
        google_api_key=settings.GOOGLE_API_KEY,
        temperature=0.2,
    )


def llm_content_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: List[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
                continue
            if isinstance(item, dict):
                text_value = item.get("text") or item.get("content") or item.get("value")
                if isinstance(text_value, str):
                    parts.append(text_value)
                    continue
            parts.append(str(item))
        return "\n".join(parts)
    return str(content)


def clean_llm_response_content(response: Any) -> str:
    return llm_content_text(getattr(response, "content", response)).strip()


# ── File tree utilities ────────────────────────────────────────────────────

CODE_EXTENSIONS = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".rs", ".java",
    ".rb", ".php", ".cs", ".cpp", ".c", ".h", ".swift", ".kt",
    ".json", ".yaml", ".yml", ".toml", ".env", ".md", ".txt",
    ".html", ".css", ".scss", ".sql",
}
EXCLUDED_DIRS = {
    "node_modules", ".git", "__pycache__", ".venv", "venv",
    "dist", "build", ".next", "vendor", "coverage",
}


def prune_structure(tree_items: List[Dict], max_files: int = 120) -> List[str]:
    """Filter tree to code-relevant files, returning a flat list of paths."""
    files = []
    for item in tree_items:
        if item.get("type") != "blob":
            continue
        path = item.get("path", "")
        parts = path.split("/")
        if any(part in EXCLUDED_DIRS for part in parts):
            continue
        ext = "." + path.rsplit(".", 1)[-1].lower() if "." in path else ""
        if ext in CODE_EXTENSIONS or path in {"Makefile", "Dockerfile", "Procfile"}:
            files.append(path)
        if len(files) >= max_files:
            break
    return files


# ── Node 1: Planner (Semantic-Search-First + Neo4j graph expansion) ────────

async def planner_node(state: AgentState, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    query = state["query"]
    file_list = state["file_list"]
    languages = state["languages"]
    frameworks = state["frameworks"]
    repo_id = state.get("repo_id", "")

    callback = (config or {}).get("configurable", {}).get("log_callback")

    if callback:
        await callback("Planner", "info", "Searching local Qdrant semantic cache...")

    # ── 1. Qdrant semantic search ──────────────────────────────────────────
    cached_files: List[dict] = []
    cached_kos: List[dict] = []

    if repo_id:
        try:
            from app.services.semantic_search import SemanticSearchService
            search_svc = SemanticSearchService(repo_id)
            cached_files, cached_kos = await search_svc.search_local_cache(query)
        except Exception as e:
            logger.error(f"Semantic search error: {e}")

    # ── 2. If KO hits → ask LLM if we can answer from cache ───────────────
    if cached_kos:
        if callback:
            await callback(
                "Planner", "info",
                f"Found {len(cached_kos)} matching Knowledge Object categories. Evaluating confidence..."
            )

        llm = get_llm()
        kos_context = "\n\n".join([
            f"### Category: {ko['category']} (Version {ko.get('version', 1)})\n{ko['summary']}"
            for ko in cached_kos
        ])

        system_eval = (
            "You are RepoMind AI Evaluator. Determine if the user's query can be answered fully "
            "based ONLY on the provided Knowledge Object summaries. Respond in raw JSON:\n"
            '{"can_answer": true/false, "explanation": "why or why not", "confidence": 0.0-1.0}\n'
            "Set can_answer=true when confidence >= 0.75."
        )
        user_eval = f"Query: {query}\n\nCache Summaries:\n{kos_context}"

        try:
            resp = await llm.ainvoke([SystemMessage(content=system_eval), HumanMessage(content=user_eval)])
            cleaned = clean_llm_response_content(resp)
            if "```json" in cleaned:
                cleaned = cleaned.split("```json")[1].split("```")[0].strip()
            elif "```" in cleaned:
                cleaned = cleaned.split("```")[1].split("```")[0].strip()

            eval_data = json.loads(cleaned)
            if eval_data.get("can_answer") and eval_data.get("confidence", 0) >= 0.75:
                if callback:
                    await callback(
                        "Planner", "info",
                        f"Cache HIT (confidence={eval_data['confidence']}). Answering from local DB.",
                        {"explanation": eval_data.get("explanation")},
                    )
                return {
                    "plan": ["Resolve from local Knowledge Object cache."],
                    "step_findings": [f"Cached Knowledge Summaries:\n{kos_context}"],
                    "current_step_index": 1,
                }
        except Exception as e:
            logger.error(f"Cache evaluator failed: {e}")

    # ── 3. Neo4j graph expansion — expand seed files from semantic search ──
    graph_related_files: List[str] = []
    if repo_id and cached_files:
        try:
            from app.db.neo4j_client import get_related_files_for_query
            seed_paths = [f["path"] for f in cached_files]
            graph_related_files = await get_related_files_for_query(repo_id, seed_paths, depth=1)
            graph_related_files = [p for p in graph_related_files if p not in seed_paths]
            if graph_related_files and callback:
                await callback(
                    "Planner", "info",
                    f"Neo4j graph expanded context by {len(graph_related_files)} related files.",
                    {"related_files": graph_related_files[:10]},
                )
        except Exception as e:
            logger.error(f"Neo4j graph expansion error: {e}")

    # ── 4. Cache miss → generate step-by-step fetch plan ──────────────────
    if callback:
        await callback("Planner", "info", "Cache miss. Generating investigation plan...")

    # Combine file list with Neo4j expanded context
    enhanced_file_list = list(dict.fromkeys(file_list + graph_related_files))

    llm = get_llm()
    system_prompt = (
        "You are RepoMind AI Planner, a senior software architect. "
        "Create a focused checklist of 2-4 concrete steps to answer the user's query. "
        "Steps should target specific files or directories in the codebase. "
        "Return a valid JSON array of strings. No markdown or conversational text."
    )
    user_prompt = (
        f"User Query: {query}\n"
        f"Languages: {list(languages.keys())}\n"
        f"Frameworks: {frameworks}\n"
        f"Key Files:\n" + "\n".join(enhanced_file_list[:120])
    )

    try:
        resp = await llm.ainvoke([SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)])
        cleaned = clean_llm_response_content(resp)
        if "```json" in cleaned:
            cleaned = cleaned.split("```json")[1].split("```")[0].strip()
        elif "```" in cleaned:
            cleaned = cleaned.split("```")[1].split("```")[0].strip()
        plan = json.loads(cleaned)
        if not isinstance(plan, list):
            plan = [plan]
    except Exception as e:
        logger.error(f"Planner LLM error: {e}")
        plan = [
            f"Locate files related to: {query}",
            "Examine implementation details",
            "Synthesize results",
        ]

    if callback:
        await callback("Planner", "plan", "Investigation plan generated.", {"plan": plan})

    return {
        "plan": plan,
        "step_findings": [""] * len(plan),
        "current_step_index": 0,
    }


# ── Node 2: Explorer (MongoDB cache-first + dynamic context expansion) ─────

async def explorer_node(state: AgentState, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    query = state["query"]
    plan = list(state["plan"])
    current_index = state["current_step_index"]
    file_list = state["file_list"]
    files_cache = state["files_cache"] or {}
    step_findings = list(state["step_findings"])
    owner = state["owner"]
    repo = state["repo"]
    branch = state["branch"]
    repo_id = state.get("repo_id", "")

    callback = (config or {}).get("configurable", {}).get("log_callback")

    if current_index >= len(plan):
        return {}

    current_step = plan[current_index]
    if callback:
        await callback("Explorer", "info", f"Step {current_index + 1}/{len(plan)}: '{current_step}'")

    # ── Identify file to read ──────────────────────────────────────────────
    llm = get_llm()
    system_prompt = (
        "You are RepoMind AI Explorer investigating a codebase.\n"
        f"Goal: {query}\n"
        f"Current Step: {current_step}\n"
        f"Files already read: {list(files_cache.keys())}\n\n"
        "Identify which file path from the repository list must be read to complete this step.\n"
        "If you already have enough information, specify 'NONE'.\n"
        'Output raw JSON: {"file_to_read": "path/to/file" or "NONE", "reason": "..."}'
    )
    user_prompt = "Available Files:\n" + "\n".join(file_list[:120])

    file_to_read = "NONE"
    try:
        resp = await llm.ainvoke([SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)])
        cleaned = clean_llm_response_content(resp)
        if "```json" in cleaned:
            cleaned = cleaned.split("```json")[1].split("```")[0].strip()
        elif "```" in cleaned:
            cleaned = cleaned.split("```")[1].split("```")[0].strip()
        data = json.loads(cleaned)
        file_to_read = data.get("file_to_read", "NONE").strip()
    except Exception as e:
        logger.error(f"Explorer file selection error: {e}")

    content = ""
    if file_to_read != "NONE" and file_to_read in file_list:
        if file_to_read not in files_cache:
            # 1. Check MongoDB cache
            mongo_content = None
            if repo_id:
                try:
                    from app.db.mongo import get_collection
                    files_col = get_collection("repository_files")
                    doc = await files_col.find_one({
                        "repository_id": repo_id,
                        "path": file_to_read,
                    })
                    if doc:
                        mongo_content = doc["content"]
                except Exception as e:
                    logger.error(f"MongoDB file lookup error: {e}")

            if mongo_content:
                if callback:
                    await callback("Explorer", "info", f"MongoDB cache hit: '{file_to_read}'")
                content = mongo_content
                files_cache[file_to_read] = content
            else:
                # 2. Fallback: fetch from GitHub
                if callback:
                    await callback("Explorer", "tool_call", f"Cache miss. Fetching '{file_to_read}' from GitHub...", {"path": file_to_read})
                try:
                    gh = GitHubService()
                    content = await gh.fetch_file_content(owner, repo, file_to_read, branch)
                    files_cache[file_to_read] = content

                    # Persist to MongoDB + Qdrant
                    if repo_id:
                        from app.db.mongo import get_collection
                        from app.db.qdrant_client import upsert_file_vector
                        files_col = get_collection("repository_files")
                        result = await files_col.insert_one({
                            "repository_id": repo_id,
                            "path": file_to_read,
                            "content": content,
                            "last_updated": __import__("datetime").datetime.utcnow(),
                        })
                        await upsert_file_vector(
                            str(result.inserted_id), repo_id, file_to_read, content[:500]
                        )
                except Exception as e:
                    logger.error(f"GitHub fetch failed for {file_to_read}: {e}")
                    content = f"Error fetching file: {e}"
                    files_cache[file_to_read] = content
        else:
            content = files_cache[file_to_read]

    # ── Analyze findings + dynamic import expansion ────────────────────────
    system_analyzer = (
        "You are RepoMind AI Explorer. Analyze file content to resolve the plan step.\n"
        f"Goal: {query}\n"
        f"Step: {current_step}\n"
        "Synthesize what you learned. Also suggest 0-3 additional import files to inspect if needed.\n"
        'Output raw JSON: {"findings": "...", "additional_imports_to_inspect": ["path/to/file"]}'
    )
    analyzer_input = f"File: {file_to_read}\nContent:\n{content[:12000] if content else 'No content.'}"

    step_result = ""
    try:
        analyzer_resp = await llm.ainvoke([
            SystemMessage(content=system_analyzer),
            HumanMessage(content=analyzer_input),
        ])
        cleaned = clean_llm_response_content(analyzer_resp)
        if "```json" in cleaned:
            cleaned = cleaned.split("```json")[1].split("```")[0].strip()
        elif "```" in cleaned:
            cleaned = cleaned.split("```")[1].split("```")[0].strip()

        analysis_data = json.loads(cleaned)
        step_result = analysis_data.get("findings", "")

        # Inject import dependencies into the plan
        additional_imports = analysis_data.get("additional_imports_to_inspect", [])
        valid_imports = [imp for imp in additional_imports if imp in file_list and imp not in files_cache]
        if valid_imports and callback:
            await callback(
                "Explorer", "info",
                f"Dynamic expansion: adding {valid_imports} to plan."
            )
        for imp_path in valid_imports:
            plan.insert(current_index + 1, f"Inspect dependency: '{imp_path}'")
            step_findings.insert(current_index + 1, "")

    except Exception as e:
        logger.error(f"Explorer analysis error: {e}")
        step_result = f"Unable to fully analyze {file_to_read}."

    step_findings[current_index] = step_result
    if callback:
        await callback("Explorer", "info", f"Step {current_index + 1} complete.")

    return {
        "plan": plan,
        "files_cache": files_cache,
        "step_findings": step_findings,
        "current_step_index": current_index + 1,
    }


# ── Node 3: Synthesizer (with background prefetch) ─────────────────────────

async def synthesizer_node(state: AgentState, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    query = state["query"]
    plan = state["plan"]
    step_findings = state["step_findings"]
    files_cache = state["files_cache"] or {}
    owner = state["owner"]
    repo = state["repo"]
    file_list = state["file_list"]
    repo_id = state.get("repo_id", "")

    callback = (config or {}).get("configurable", {}).get("log_callback")
    if callback:
        await callback("Synthesizer", "info", "Synthesizing final response...")

    llm = get_llm()
    system_prompt = (
        "You are RepoMind AI Synthesizer, a principal software engineer. "
        f"Answer the user query based on a detailed investigation of `{owner}/{repo}`.\n\n"
        "Provide a comprehensive technical response in Markdown. "
        "Cite specific files, classes, and code structures. Use structured headers and code blocks."
    )

    findings_context = "Investigation Plan & Findings:\n"
    for i, step in enumerate(plan):
        findings_context += f"Step {i+1}: {step}\n"
        findings_context += f"Findings: {step_findings[i] if i < len(step_findings) else 'N/A'}\n\n"

    findings_context += "Code Snippets:\n"
    for path, content in files_cache.items():
        findings_context += f"--- FILE: {path} ---\n{content[:6000]}\n\n"

    user_prompt = f"Query: {query}\n\nContext:\n{findings_context}\nGenerate the final response."

    try:
        resp = await llm.ainvoke([SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)])
        final_answer = clean_llm_response_content(resp)
    except Exception as e:
        logger.error(f"Synthesizer error: {e}")
        final_answer = f"Error generating response: {e}"

    if callback:
        await callback("Synthesizer", "completion", "Final answer compiled.")

    # Background prefetch
    if repo_id:
        asyncio.create_task(
            run_prefetching(query, final_answer, file_list, owner, repo, repo_id, callback)
        )

    return {"final_answer": final_answer}


async def run_prefetching(
    query: str,
    answer: str,
    file_list: List[str],
    owner: str,
    repo_name: str,
    repo_id: str,
    callback: Optional[Any],
):
    """
    Background task: predict follow-up files and pre-cache them
    in MongoDB + Qdrant so the next query is faster.
    """
    try:
        llm = get_llm()
        system_prompt = (
            "You are RepoMind AI Prefetcher. Given a query and its answer, predict 1-3 files "
            "the user is likely to ask about next. Return a raw JSON array of file paths only."
        )
        user_prompt = (
            f"Query: {query}\nAnswer: {answer[:4000]}\n\nAvailable files:\n"
            + "\n".join(file_list[:100])
        )

        resp = await llm.ainvoke([SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)])
        cleaned = clean_llm_response_content(resp)
        if "```json" in cleaned:
            cleaned = cleaned.split("```json")[1].split("```")[0].strip()
        elif "```" in cleaned:
            cleaned = cleaned.split("```")[1].split("```")[0].strip()

        prefetch_paths = json.loads(cleaned)
        if not isinstance(prefetch_paths, list):
            return

        valid_paths = [p for p in prefetch_paths if p in file_list]
        if not valid_paths:
            return

        if callback:
            await callback("Prefetcher", "info", f"Background prefetching: {valid_paths}")

        from app.db.mongo import get_collection
        from app.db.qdrant_client import upsert_file_vector
        files_col = get_collection("repository_files")
        gh = GitHubService()

        for path in valid_paths:
            existing = await files_col.find_one({"repository_id": repo_id, "path": path})
            if existing:
                continue
            try:
                content = await gh.fetch_file_content(owner, repo_name, path)
                result = await files_col.insert_one({
                    "repository_id": repo_id,
                    "path": path,
                    "content": content,
                    "last_updated": __import__("datetime").datetime.utcnow(),
                })
                await upsert_file_vector(str(result.inserted_id), repo_id, path, content[:500])
            except Exception as e:
                logger.error(f"Prefetch download failed for {path}: {e}")

    except Exception as e:
        logger.error(f"Prefetching task error: {e}")


# ── Routing ────────────────────────────────────────────────────────────────

def should_continue(state: AgentState) -> str:
    if state["current_step_index"] < len(state["plan"]):
        return "explorer"
    return "synthesizer"


def build_agent_graph():
    workflow = StateGraph(AgentState)
    workflow.add_node("planner", planner_node)
    workflow.add_node("explorer", explorer_node)
    workflow.add_node("synthesizer", synthesizer_node)
    workflow.set_entry_point("planner")
    workflow.add_conditional_edges("planner", should_continue, {
        "explorer": "explorer",
        "synthesizer": "synthesizer",
    })
    workflow.add_conditional_edges("explorer", should_continue, {
        "explorer": "explorer",
        "synthesizer": "synthesizer",
    })
    workflow.add_edge("synthesizer", END)
    return workflow.compile()
