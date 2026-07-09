"""
LangGraph Agent Graph — RepoMind AI.

Agentic RAG pipeline:

  [query_rewriter] ──► [retriever] ──► [synthesizer] ──► (check_context)
                             ▲                                    │
                             │                          ┌─────────┴──────────┐
                             │                       "research"           "end"
                             │                    [research_node]           │
                             └────────────────────────────┘               END

Flow:
  1. query_rewriter  — Expands the raw query using conversation history.
  2. retriever       — Two-Stage fast pass OR direct load_file:<path> bypass.
  3. synthesizer     — Strict prompt-cached generation with streaming.
  4. check_context   — Routes to research_node on <MISSING_CONTEXT>, else END.
  5. research_node   — Determines the best follow-up query; sets rewritten_query.
                       Loops back to retriever (max MAX_RESEARCH_LOOPS = 3).
"""

import re
from typing import Any, Dict, List, Optional

from bson import ObjectId
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import END, StateGraph
from typing_extensions import TypedDict

from app.config import settings

MAX_RESEARCH_LOOPS = 3


# ── AgentState ─────────────────────────────────────────────────────────────

class AgentState(TypedDict):
    # Core query fields
    query: str
    rewritten_query: str       # Also used as load_file:<path> signal for retriever

    # Repository context (set by main.py before graph invocation)
    owner: str
    repo: str
    branch: str
    repo_id: str               # MongoDB repository _id string
    file_list: List[str]       # Flat list of all repo file paths
    languages: Dict[str, Any]
    frameworks: List[str]

    # Retrieval output — grows across research loop iterations
    retrieved_context: List[Dict]   # [{path: str, content: str}, ...]

    # Conversation state
    chat_history: List[Any]         # [{role: str, content: str}, ...]
    session_id: str

    # Research loop control
    fallback_count: int

    # Final output
    final_answer: str


# ── LLM Helpers ────────────────────────────────────────────────────────────

def _get_llm() -> ChatGoogleGenerativeAI:
    return ChatGoogleGenerativeAI(
        model=settings.GOOGLE_MODEL,
        google_api_key=settings.GOOGLE_API_KEY,
        temperature=0.2,
    )


def _clean(response: Any) -> str:
    """Extracts plain text from any LangChain response object."""
    content = getattr(response, "content", response)
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(item.get("text") or item.get("content") or str(item))
            else:
                parts.append(str(item))
        return "\n".join(parts).strip()
    return str(content).strip()


# ── File Tree Utility ───────────────────────────────────────────────────────

CODE_EXTENSIONS = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".rs", ".java",
    ".rb", ".php", ".cs", ".cpp", ".c", ".h", ".swift", ".kt",
    ".json", ".yaml", ".yml", ".toml", ".env", ".md", ".txt",
    ".html", ".css", ".scss", ".sql",
}
EXCLUDED_DIRS = {
    "node_modules", ".git", "__pycache__", ".venv", "venv",
    "dist", "build", ".next", "vendor", "coverage", "bin", "obj",
    "target", "out",
}
IGNORE_EXTS = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".webp",
    ".mp3", ".mp4", ".wav", ".avi", ".mov", ".mkv",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".zip", ".tar", ".gz", ".rar", ".7z",
    ".exe", ".dll", ".so", ".dylib", ".class", ".jar", ".pyc",
    ".log", ".lock",
}


def prune_structure(tree_items: List[Dict], max_files: Optional[int] = 5000) -> List[str]:
    """Filters a GitHub tree payload to a flat list of code-relevant file paths."""
    files = []
    for item in tree_items:
        if item.get("type") != "blob":
            continue
        path = item.get("path", "")
        if any(part in EXCLUDED_DIRS for part in path.split("/")):
            continue
        ext = "." + path.rsplit(".", 1)[-1].lower() if "." in path else ""
        if ext in IGNORE_EXTS:
            continue
        if ext in CODE_EXTENSIONS or path in {"Makefile", "Dockerfile", "Procfile"}:
            files.append(path)
        if max_files and len(files) >= max_files:
            break
    return files


# ── Node 1: Query Rewriter ─────────────────────────────────────────────────

async def query_rewriter_node(state: AgentState, config: Any = None) -> Dict[str, Any]:
    """
    Expands the raw user query into a richer semantic search string,
    using the conversation history to resolve pronouns and infer intent.
    """
    history_text = "\n".join(
        f"{m['role']}: {m['content']}" for m in state.get("chat_history", [])
    )
    system_prompt = (
        "You are RepoMind AI Query Rewriter. Expand the user's technical question "
        "for semantic vector retrieval. Use the conversation history to resolve "
        "pronouns and infer missing context. Add technical synonyms and richer terms.\n"
        "Return ONLY the rewritten query string. No markdown, quotes, or explanations."
    )
    user_payload = f"Conversation History:\n{history_text}\n\nOriginal Query: {state['query']}"

    try:
        llm = _get_llm()
        resp = await llm.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_payload),
        ])
        rewritten_query = _clean(resp)
    except Exception:
        rewritten_query = state["query"]

    return {"rewritten_query": rewritten_query}


# ── Node 2: Retriever ─────────────────────────────────────────────────────

async def retriever_node(state: AgentState, config: Any = None) -> Dict[str, Any]:
    """
    Retrieves files for the synthesizer. Two operating modes:

    Mode A — Direct Load (load_file:<path>):
        Triggered when rewritten_query starts with 'load_file:'.
        Bypasses Qdrant entirely and does a single MongoDB find_one by path.
        Appends to the existing retrieved_context (does not replace it).

    Mode B — Two-Stage Fast Pass (default):
        Runs the full TwoStageRetriever pipeline:
          Stage 1: Qdrant global seed (top_k=8).
          Stage 2: Regex import extraction → MongoDB $in bulk fetch.
        Existing retrieved_context paths are passed as exclude_paths
        to avoid re-fetching files already in context.
    """
    rewritten_query = state.get("rewritten_query") or state["query"]
    repo_id = state.get("repo_id", "")
    file_list = state["file_list"]
    current_context = list(state.get("retrieved_context", []))
    existing_paths = {f["path"] for f in current_context}

    # ── Mode A: Direct file load ───────────────────────────────────────────
    if rewritten_query.startswith("load_file:"):
        file_path = rewritten_query[len("load_file:"):].strip()

        # Skip if already in context
        if file_path in existing_paths:
            return {"retrieved_context": current_context}

        try:
            from app.db.mongo import get_collection
            files_col = get_collection("repository_files")
            doc = await files_col.find_one({
                "repository_id": repo_id,
                "path": file_path,
            })
            if doc:
                current_context.append({
                    "path": doc["path"],
                    "content": doc.get("content", ""),
                })
        except Exception:
            pass

        return {"retrieved_context": current_context}

    # ── Mode B: Two-Stage fast pass ────────────────────────────────────────
    from app.services.two_stage_retriever import TwoStageRetriever

    retriever = TwoStageRetriever(
        repo_id=repo_id,
        file_list=file_list,
        exclude_paths=existing_paths,
    )
    new_files = await retriever.retrieve(rewritten_query, top_k=8)
    merged = current_context + new_files

    return {"retrieved_context": merged}


# ── Node 3: Synthesizer ────────────────────────────────────────────────────

async def synthesizer_node(state: AgentState, config: Any = None) -> Dict[str, Any]:
    """
    Generates the final answer using a strict prompt-cache-optimal layout:

      [1] System Instructions             (static)
      [2] <codebase> XML block            (static across follow-up turns)
      [3] <chat_history> sliding window   (last 3 turns)
      [4] <query> current question        (dynamic)

    Streams tokens via stream_callback if provided.
    Signals missing context by outputting ONLY:
      <MISSING_CONTEXT>exact_file_path_or_entity</MISSING_CONTEXT>
    """
    query = state["query"]
    retrieved_context = state.get("retrieved_context", [])
    chat_history = state.get("chat_history", [])
    owner = state["owner"]
    repo = state["repo"]

    stream_callback = (config or {}).get("configurable", {}).get("stream_callback")

    # ── 1. System Prompt ───────────────────────────────────────────────────
    system_prompt = (
        "You are RepoMind AI Synthesizer, a principal software engineer.\n"
        f"You are analyzing the repository `{owner}/{repo}`.\n\n"
        "Rules:\n"
        "- Answer in clean, well-structured Markdown.\n"
        "- Cite specific file paths, class names, and function names.\n"
        "- Use fenced code blocks with language tags for all code.\n"
        "- If you cannot answer because a critical file or function definition "
        "is missing from your context, output ONLY this tag and nothing else:\n"
        "  <MISSING_CONTEXT>exact_file_path_or_function_name</MISSING_CONTEXT>\n"
        "- Do NOT guess or hallucinate file contents. Use only what is provided."
    )

    # ── 2. Codebase XML Block ──────────────────────────────────────────────
    codebase_lines = ["<codebase>"]
    for f in retrieved_context:
        codebase_lines.append(f'<file path="{f.get("path", "unknown")}">')
        codebase_lines.append(f.get("content", "")[:10_000])
        codebase_lines.append("</file>")
    codebase_lines.append("</codebase>")
    codebase_str = "\n".join(codebase_lines)

    # ── 3. Truncated Chat History ──────────────────────────────────────────
    from app.services.two_stage_retriever import truncate_chat_history
    recent = truncate_chat_history(chat_history, retain_turns=3)
    history_str = "\n".join(
        f'<turn role="{t.get("role")}">{t.get("content")}</turn>' for t in recent
    ) or "(no prior conversation)"

    # ── 4. User Prompt ─────────────────────────────────────────────────────
    user_prompt = (
        f"{codebase_str}\n\n"
        f"<chat_history>\n{history_str}\n</chat_history>\n\n"
        f"<query>{query}</query>"
    )

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_prompt),
    ]

    llm = _get_llm()
    final_answer = ""

    if stream_callback:
        try:
            async for chunk in llm.astream(messages):
                token = ""
                c = getattr(chunk, "content", "")
                if isinstance(c, str):
                    token = c
                elif isinstance(c, list):
                    for part in c:
                        if isinstance(part, str):
                            token += part
                        elif isinstance(part, dict) and "text" in part:
                            token += part["text"]
                if token:
                    final_answer += token
                    await stream_callback(token)
        except Exception:
            if not final_answer:
                try:
                    resp = await llm.ainvoke(messages)
                    final_answer = _clean(resp)
                except Exception as e:
                    final_answer = f"Error generating response: {e}"
    else:
        try:
            resp = await llm.ainvoke(messages)
            final_answer = _clean(resp)
        except Exception as e:
            final_answer = f"Error generating response: {e}"

    return {"final_answer": final_answer.strip()}


# ── Node 4: Research Node ──────────────────────────────────────────────────

async def research_node(state: AgentState, config: Any = None) -> Dict[str, Any]:
    """
    Agentic research step triggered when the Synthesizer signals missing context.

    Behaviour:
      1. Parse the <MISSING_CONTEXT> tag from final_answer.
      2. If the entity looks like a file path (contains '/' or ends in a known
         extension), set rewritten_query = 'load_file:<path>' for a direct
         MongoDB fetch in the next retriever pass.
      3. If the entity is a concept/function name, use the LLM to generate a
         sharper vector search query that maximises the chance of locating
         the missing file in Qdrant.

    Always increments fallback_count.
    """
    raw_answer = state.get("final_answer", "")
    query = state["query"]

    match = re.search(r"<MISSING_CONTEXT>(.*?)</MISSING_CONTEXT>", raw_answer, re.DOTALL)
    missing_entity = match.group(1).strip() if match else raw_answer.strip()

    # ── Heuristic: does this look like a file path? ────────────────────────
    file_extensions = (
        ".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".rs", ".java",
        ".rb", ".php", ".cs", ".cpp", ".c", ".h", ".swift", ".kt",
        ".json", ".yaml", ".yml", ".toml", ".md", ".html", ".css",
    )
    is_file_path = (
        "/" in missing_entity
        or missing_entity.endswith(file_extensions)
    )

    if is_file_path:
        new_query = f"load_file:{missing_entity}"
    else:
        # Ask the LLM to generate a better semantic search query
        system_prompt = (
            "You are a code search query optimizer. "
            "Given an original user question and a missing entity that prevented answering, "
            "generate the single best vector search query to locate the file or code "
            "that defines or implements that entity.\n"
            "Return ONLY the search query string. No markdown, quotes, or explanation."
        )
        user_payload = (
            f"Original user question: {query}\n"
            f"Missing entity: {missing_entity}\n\n"
            "Generate a targeted search query to find the file containing this entity."
        )
        try:
            llm = _get_llm()
            resp = await llm.ainvoke([
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_payload),
            ])
            new_query = _clean(resp)
        except Exception:
            new_query = missing_entity

    return {
        "rewritten_query": new_query,
        "fallback_count": state.get("fallback_count", 0) + 1,
    }


# ── Conditional Edge ────────────────────────────────────────────────────────

def check_context(state: AgentState) -> str:
    """
    Routes the graph after the Synthesizer:
      "research" → <MISSING_CONTEXT> detected AND fallback_count < MAX_RESEARCH_LOOPS
      "end"      → answer is complete OR research loop cap reached
    """
    final_answer = state.get("final_answer", "")
    fallback_count = state.get("fallback_count", 0)

    if "<MISSING_CONTEXT>" in final_answer and fallback_count < MAX_RESEARCH_LOOPS:
        return "research"

    return "end"


# ── Graph Builder ───────────────────────────────────────────────────────────

def build_agent_graph():
    """
    Assembles and compiles the RepoMind AI LangGraph pipeline.

    Flow:
        [query_rewriter] ──► [retriever] ──► [synthesizer] ──► (check_context)
                                  ▲                                    │
                                  │                          ┌─────────┴──────────┐
                                  │                       "research"           "end"
                                  │                    [research_node]           │
                                  └────────────────────────────┘               END
    """
    workflow = StateGraph(AgentState)

    workflow.add_node("query_rewriter", query_rewriter_node)
    workflow.add_node("retriever", retriever_node)
    workflow.add_node("synthesizer", synthesizer_node)
    workflow.add_node("research", research_node)

    workflow.set_entry_point("query_rewriter")
    workflow.add_edge("query_rewriter", "retriever")
    workflow.add_edge("retriever", "synthesizer")

    workflow.add_conditional_edges(
        "synthesizer",
        check_context,
        {
            "research": "research",
            "end": END,
        },
    )

    # Research loops back to retriever with updated rewritten_query
    workflow.add_edge("research", "retriever")

    return workflow.compile()
