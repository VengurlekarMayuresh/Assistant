"""
Knowledge Engine — generates and maintains LLM Knowledge Objects.

Changes from PostgreSQL version:
  - All DB operations use Motor (MongoDB async driver).
  - After saving each KnowledgeObject to MongoDB, its embedding is upserted
    into Qdrant for semantic search.
  - KnowledgeObjectFiles are embedded as a list inside the parent document
    instead of a separate table.
"""
import logging
import re
from datetime import datetime
from typing import List, Dict, Any, Tuple, Optional

from bson import ObjectId

from app.db.mongo import get_collection
from app.db.qdrant_client import upsert_knowledge_object_vector
from app.agents.agent_graph import _get_llm, _clean
from langchain_core.messages import SystemMessage, HumanMessage

logger = logging.getLogger(__name__)


CATEGORIES = {
    "Authentication": r"auth|login|signup|jwt|token|session|permission|oauth|credential",
    "Payments": r"pay|stripe|billing|invoice|checkout|card|subscription|purchase",
    "User Management": r"user|profile|member|account|role",
    "Notifications": r"email|sms|notification|alert|mail|sendgrid|twilio|broadcast",
    "Database": r"db|models|database|schema|migration|alembic|prisma|query|sql|postgres|mongo",
    "API Layer": r"route|endpoint|api|controller|views|url|handler|middleware",
    "Frontend": r"css|html|js|jsx|ts|tsx|component|style|tailwind|page|view",
    "DevOps": r"docker|kubernetes|ci|cd|workflow|deploy|nginx|compose|jenkins|yaml|yml",
    "Testing": r"test|mock|spec|conftest|pytest|unittest",
    "Documentation": r"readme|docs|license|changelog|docstring|guide|\.md",
}


class KnowledgeEngine:
    def __init__(self, repository_id: str):
        self.repository_id = repository_id
        self.files_col = get_collection("repository_files")
        self.ko_col = get_collection("knowledge_objects")

    def classify_file(self, path: str) -> List[str]:
        """Classify a file path into one or more logical categories."""
        matched = []
        path_lower = path.lower()
        for category, pattern in CATEGORIES.items():
            if re.search(pattern, path_lower):
                matched.append(category)

        if not matched:
            if path_lower.endswith((".py", ".go", ".rs", ".java")):
                matched.append("API Layer")
            elif path_lower.endswith((".js", ".ts", ".tsx", ".jsx", ".html", ".css")):
                matched.append("Frontend")
            else:
                matched.append("Documentation")

        return matched

    async def generate_knowledge_objects(
        self,
        commit_sha: str,
        log_callback: Optional[Any] = None,
    ):
        """
        Scans all cached repository files, groups them by domain,
        calls the LLM to write summaries, saves to MongoDB, and upserts
        embeddings into Qdrant.
        """
        # Fetch all cached files
        cursor = self.files_col.find({"repository_id": self.repository_id})
        files = await cursor.to_list(length=None)

        # Group by category
        category_files: Dict[str, List[dict]] = {cat: [] for cat in CATEGORIES}
        for file_doc in files:
            for cat in self.classify_file(file_doc["path"]):
                category_files[cat].append(file_doc)

        for category, cat_files in category_files.items():
            if not cat_files:
                continue

            if log_callback:
                await log_callback(
                    "KnowledgeEngine", "info",
                    f"Generating Knowledge Object: [{category}] ({len(cat_files)} files)"
                )

            summary, confidence = await self._summarize_category(category, cat_files)

            # Build embedded file list
            file_entries = [{"file_path": f["path"]} for f in cat_files]

            # Insert into MongoDB
            ko_doc = {
                "repository_id": self.repository_id,
                "category": category,
                "summary": summary,
                "confidence_score": confidence,
                "version": 1,
                "commit_sha": commit_sha,
                "last_updated": datetime.utcnow(),
                "files": file_entries,
            }
            result = await self.ko_col.insert_one(ko_doc)
            ko_id = str(result.inserted_id)

            # Upsert into Qdrant
            try:
                await upsert_knowledge_object_vector(
                    point_id=ko_id,
                    repository_id=self.repository_id,
                    category=category,
                    summary=summary,
                    version=1,
                )
            except Exception as e:
                logger.error(f"Qdrant upsert failed for KO {ko_id}: {e}")

    async def invalidate_cache(
        self,
        changed_files: List[str],
        commit_sha: str,
        log_callback: Optional[Any] = None,
    ):
        """
        Selectively regenerates Knowledge Objects whose category covers any of
        the changed files. Creates a new version document rather than updating
        in-place so we preserve history.
        """
        affected_categories = set()
        for path in changed_files:
            for cat in self.classify_file(path):
                affected_categories.add(cat)

        if not affected_categories:
            return

        if log_callback:
            await log_callback(
                "KnowledgeEngine", "info",
                f"Cache invalidation: regenerating {list(affected_categories)}"
            )

        # Fetch all repo files once
        cursor = self.files_col.find({"repository_id": self.repository_id})
        all_files = await cursor.to_list(length=None)

        for category in affected_categories:
            cat_files = [f for f in all_files if category in self.classify_file(f["path"])]
            if not cat_files:
                continue

            # Get current max version
            latest = await self.ko_col.find_one(
                {"repository_id": self.repository_id, "category": category},
                sort=[("version", -1)],
            )
            next_version = (latest["version"] + 1) if latest else 1

            if log_callback:
                await log_callback(
                    "KnowledgeEngine", "info",
                    f"Updating [{category}] → Version {next_version}"
                )

            summary, confidence = await self._summarize_category(category, cat_files)
            file_entries = [{"file_path": f["path"]} for f in cat_files]

            ko_doc = {
                "repository_id": self.repository_id,
                "category": category,
                "summary": summary,
                "confidence_score": confidence,
                "version": next_version,
                "commit_sha": commit_sha,
                "last_updated": datetime.utcnow(),
                "files": file_entries,
            }
            result = await self.ko_col.insert_one(ko_doc)
            ko_id = str(result.inserted_id)

            # Update Qdrant vector
            try:
                await upsert_knowledge_object_vector(
                    point_id=ko_id,
                    repository_id=self.repository_id,
                    category=category,
                    summary=summary,
                    version=next_version,
                )
            except Exception as e:
                logger.error(f"Qdrant upsert failed for KO {ko_id}: {e}")

    async def _summarize_category(
        self,
        category: str,
        files: List[dict],
    ) -> Tuple[str, float]:
        """Invoke Google GenAI LLM to write a markdown architectural summary."""
        llm = _get_llm()

        file_contexts = []
        for file_doc in files[:15]:
            content = file_doc.get("content", "")
            snippet = content[:1500] + "\n...[TRUNCATED]..." if len(content) > 1500 else content
            file_contexts.append(f"### FILE: {file_doc['path']}\n```\n{snippet}\n```")

        system_prompt = (
            "You are RepoMind AI Architect. Analyze the files belonging to a logical code module "
            "and write a high-level architectural overview in Markdown. "
            "Cover: what this module does, its key classes/functions, dependencies, and how it "
            "relates to the broader codebase. Also rate your confidence from 0.0 to 1.0. "
            "Format your response EXACTLY as:\n"
            "--- CONFIDENCE: 0.90 ---\n"
            "[Your detailed markdown summary here]"
        )
        user_prompt = (
            f"Logical Category: {category}\n\n"
            "Files:\n" + "\n\n".join(file_contexts)
        )

        try:
            resp = await llm.ainvoke([SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)])
            content_text = _clean(resp)

            confidence = 0.90
            conf_match = re.search(r"--- CONFIDENCE:\s*([\d.]+)\s*---", content_text)
            if conf_match:
                try:
                    confidence = float(conf_match.group(1))
                    content_text = content_text.replace(conf_match.group(0), "").strip()
                except ValueError:
                    pass

            return content_text, confidence

        except Exception as e:
            logger.error(f"LLM summarization failed for [{category}]: {e}")
            return (
                f"Summary placeholder for {category}. "
                f"Files: {', '.join(f['path'] for f in files)}",
                0.50,
            )
