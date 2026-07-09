"""
Two-Stage Codebase Retrieval Module — RepoMind AI.

Replaces the old agentic Planner → Explorer loop with a single, fast,
linear Python retrieval pass. No LLM calls are made during retrieval.

Pipeline:
  Stage 1 — Global Semantic Search:
      Query Qdrant with top_k=8 (global, filtered by repo_id only).
      Fetch raw source text for seed files from MongoDB.

  Stage 2 — Local Import Extraction:
      Scan the first 30 lines of each seed file using lightweight regex.
      Resolve relative and namespace import paths to exact repo file paths.
      Cross-reference against the known file_list set (O(1) per lookup).

  Stage 3 — Point-Blank MongoDB Fetch:
      Bulk-fetch any newly discovered internal dependency files via
      a single indexed $in query. No Qdrant call for these — raw key lookup.

  Stage 4 — Context Merge:
      Return a unified list of {path, content} dicts.

  Plan B Safety Valve:
      If Stage 1 returns zero results, automatically retry with top_k=35
      before returning an empty list.

  Utility — truncate_chat_history():
      Rolling sliding window on the conversation list to eliminate
      context drift and preserve the Prompt Cache line.
"""

import logging
import re
from typing import List, Dict, Any

from bson import ObjectId

from app.db.mongo import get_collection
from app.db.qdrant_client import get_qdrant_client, COLLECTION_FILES, embed_text
from qdrant_client.models import Filter, FieldCondition, MatchValue

logger = logging.getLogger(__name__)


# ── TwoStageRetriever ─────────────────────────────────────────────────────

class TwoStageRetriever:
    """
    High-performance, LLM-free codebase retrieval pipeline.

    Args:
        repo_id:   MongoDB _id string of the target repository.
        file_list: Flat list of all valid file paths in the repository.
                   Converted to a set internally for O(1) membership checks.
    """

    def __init__(self, repo_id: str, file_list: List[str], exclude_paths: set | None = None):
        self.repo_id = repo_id
        self.file_set: frozenset = frozenset(file_list)  # immutable, O(1) lookups
        self.exclude_paths: frozenset = frozenset(exclude_paths or set())

    # ── Stage 1: Global Semantic Search (Seed Pass) ───────────────────────

    async def _fetch_seeds_from_qdrant(self, query: str, top_k: int) -> List[Dict]:
        """
        Queries Qdrant globally (repo_id filter only, no folder scoping).
        Fetches the raw source text for matched files from MongoDB.
        """
        qdrant = get_qdrant_client()
        vector = embed_text(query)  # synchronous embedding — fast, CPU-bound

        search_filter = Filter(must=[
            FieldCondition(key="repository_id", match=MatchValue(value=self.repo_id)),
        ])

        results = await qdrant.query_points(
            collection_name=COLLECTION_FILES,
            query=vector,
            query_filter=search_filter,
            limit=top_k,
        )

        seed_files: List[Dict] = []
        files_col = get_collection("repository_files")

        for hit in results.points:
            mongo_id = hit.payload.get("mongo_id")
            if not mongo_id:
                continue
            try:
                doc = await files_col.find_one({"_id": ObjectId(mongo_id)})
                if doc and doc["path"] not in self.exclude_paths:
                    seed_files.append({
                        "path": doc["path"],
                        "content": doc.get("content", ""),
                    })
            except Exception as e:
                logger.error(f"[Retriever] MongoDB fetch error for seed {mongo_id}: {e}")

        logger.info(f"[Retriever] Stage 1 complete: {len(seed_files)} seed files (top_k={top_k}).")
        return seed_files

    # ── Stage 2: Local Import Extraction (Header Scan) ────────────────────

    def _extract_local_imports(self, content: str, current_path: str) -> List[str]:
        """
        Scans the first 30 lines of a file for import/require statements.
        Resolves relative and namespace paths to exact repo file paths.
        Filters out third-party modules by cross-referencing with file_set.

        Supports: Python (import / from...import), JS/TS (import...from / require).
        """
        header = "\n".join(content.splitlines()[:30])

        # JS / TS: matches `from './path'`, `import './path'`, `require('./path')`
        js_pattern = r"""(?:from|import)\s+['"]([^'"]+)['"]|require\(['"]([^'"]+)['"]\)"""
        # Python: matches `import foo.bar`, `from foo.bar import baz`
        py_pattern = r"""^(?:from|import)\s+([\w\.]+)"""

        raw_imports: List[str] = []
        for m in re.finditer(js_pattern, header):
            raw_imports.append(m.group(1) or m.group(2))
        for m in re.finditer(py_pattern, header, re.MULTILINE):
            raw_imports.append(m.group(1))

        # Determine the directory of the current file for relative resolution
        current_dir_parts = current_path.rsplit("/", 1)[0].split("/") if "/" in current_path else []

        resolved: List[str] = []
        for imp in raw_imports:
            imp = imp.strip()
            if not imp:
                continue

            if imp.startswith("."):
                # Relative path resolution (e.g., ../utils/helpers → src/utils/helpers.py)
                parts = imp.split("/")
                dir_parts = list(current_dir_parts)
                for part in parts:
                    if part == ".":
                        continue
                    elif part == "..":
                        if dir_parts:
                            dir_parts.pop()
                    else:
                        dir_parts.append(part)
                base = "/".join(dir_parts)
            else:
                # Absolute / namespace resolution (e.g., app.db.mongo → app/db/mongo)
                base = imp.replace(".", "/")

            # Try the path with common extensions to find an exact match in the repo
            for ext in ("", ".py", ".js", ".ts", ".jsx", ".tsx", "/index.js", "/index.ts", "/index.tsx"):
                candidate = base + ext
                if candidate in self.file_set:
                    resolved.append(candidate)
                    break

        return list(set(resolved))

    # ── Stage 3: Point-Blank MongoDB Bulk Fetch ───────────────────────────

    async def _fetch_dependencies_from_mongo(self, paths: frozenset) -> List[Dict]:
        """
        Fetches a set of known internal dependency files directly from MongoDB
        using a single indexed $in query. No Qdrant call is made here.
        """
        if not paths:
            return []

        files_col = get_collection("repository_files")
        cursor = files_col.find({
            "repository_id": self.repo_id,
            "path": {"$in": list(paths)},
        })

        docs = await cursor.to_list(length=None)
        logger.info(f"[Retriever] Stage 3 complete: {len(docs)} dependency files fetched.")
        return [{"path": d["path"], "content": d.get("content", "")} for d in docs]

    # ── Public API ────────────────────────────────────────────────────────

    async def retrieve(self, query: str, top_k: int = 8) -> List[Dict]:
        """
        Executes the full Two-Stage pipeline and returns the merged context list.

        Args:
            query:  The (optionally rewritten) user query string.
            top_k:  Number of Qdrant seed files to retrieve in Stage 1.
                    Defaults to 8 to keep the total context under 15 files.

        Returns:
            List of {path: str, content: str} dicts, or [] on total failure.
        """
        # Stage 1: Qdrant global seed pass
        seed_files = await self._fetch_seeds_from_qdrant(query, top_k)

        # Plan B: Retry with a wider net if Stage 1 found nothing
        if not seed_files:
            logger.warning(f"[Retriever] Plan B: Zero seeds for '{query[:60]}'. Retrying top_k=35.")
            seed_files = await self._fetch_seeds_from_qdrant(query, top_k=35)
            if not seed_files:
                logger.error("[Retriever] Plan B also returned zero results. Returning empty context.")
                return []

        # Stage 2: Regex import extraction from seed file headers
        seed_paths = frozenset(f["path"] for f in seed_files)
        already_known = seed_paths | self.exclude_paths
        dependency_paths: set = set()
        for f in seed_files:
            deps = self._extract_local_imports(f["content"], f["path"])
            for dep in deps:
                if dep not in already_known:
                    dependency_paths.add(dep)

        # Stage 3: Bulk fetch discovered dependencies directly from MongoDB
        helper_files = await self._fetch_dependencies_from_mongo(frozenset(dependency_paths))

        # Stage 4: Merge and return
        merged = seed_files + helper_files
        logger.info(
            f"[Retriever] Pipeline complete: {len(seed_files)} seeds + "
            f"{len(helper_files)} helpers = {len(merged)} total files."
        )
        return merged


# ── Chat History Utility ──────────────────────────────────────────────────

def truncate_chat_history(chat_history: List[Any], retain_turns: int = 3) -> List[Any]:
    """
    Rolling Chat History Truncation — Context Drift Fix.

    Slices the conversation list to retain only the most recent N turns.
    A single turn = one user message + one assistant reply = 2 list items.

    Args:
        chat_history:  List of {role, content} message dicts.
        retain_turns:  Number of full turns (pairs) to retain. Defaults to 3.

    Returns:
        The truncated list, or the original if it is already within bounds.
    """
    if not chat_history:
        return []
    max_messages = retain_turns * 2
    return chat_history[-max_messages:] if len(chat_history) > max_messages else chat_history
