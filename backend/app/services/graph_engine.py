"""
Graph Engine — Neo4j File Dependency Graph Builder.

After each full or incremental sync, this service:
  1. Parses import/require statements from every cached source file.
  2. Upserts File nodes into Neo4j.
  3. Creates IMPORTS relationships between files.

This enables the planner agent to ask:
  "What files are imported by auth.py?"
  "What files would be affected if I change models.py?"
"""
import logging
import re
from typing import List, Dict, Optional, Any

from app.db.mongo import get_collection
from app.db.neo4j_client import (
    upsert_file_node,
    upsert_import_relationship,
    delete_file_node,
    delete_repo_graph,
)

logger = logging.getLogger(__name__)


# ── Language import parsers ────────────────────────────────────────────────

PYTHON_IMPORT_RE = re.compile(
    r"^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.,\s]+))",
    re.MULTILINE,
)
JS_IMPORT_RE = re.compile(
    r"""(?:import\s+.*?from\s+['"]([^'"]+)['"]|require\s*\(\s*['"]([^'"]+)['"]\s*\))""",
    re.MULTILINE,
)
JAVA_IMPORT_RE = re.compile(r"^import\s+([\w.]+);", re.MULTILINE)
GO_IMPORT_RE = re.compile(r'"([\w./\-]+)"', re.MULTILINE)


def _detect_language(path: str) -> str:
    ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    return {
        "py": "python",
        "js": "javascript",
        "ts": "typescript",
        "jsx": "javascript",
        "tsx": "typescript",
        "java": "java",
        "go": "go",
        "rs": "rust",
        "rb": "ruby",
        "php": "php",
    }.get(ext, "unknown")


def _extract_python_imports(content: str, file_path: str, all_paths: List[str]) -> List[str]:
    """
    Convert Python module paths to likely file paths using the known file tree.
    e.g.  'from app.models import Foo'  →  'app/models.py'
    """
    raw_modules = []
    for match in PYTHON_IMPORT_RE.finditer(content):
        module = match.group(1) or match.group(2)
        if module:
            for m in module.split(","):
                raw_modules.append(m.strip().split(" ")[0])

    resolved = []
    path_set = set(all_paths)
    for module in raw_modules:
        candidate = module.replace(".", "/") + ".py"
        if candidate in path_set:
            resolved.append(candidate)
        # Also check __init__.py
        pkg_candidate = module.replace(".", "/") + "/__init__.py"
        if pkg_candidate in path_set:
            resolved.append(pkg_candidate)

    return list(set(resolved))


def _extract_js_imports(content: str, file_path: str, all_paths: List[str]) -> List[str]:
    """Resolve relative JS/TS import paths to actual file paths."""
    import os
    base_dir = os.path.dirname(file_path)
    resolved = []
    path_set = set(all_paths)

    for match in JS_IMPORT_RE.finditer(content):
        raw = match.group(1) or match.group(2)
        if not raw or raw.startswith("@") and "/" not in raw[1:]:
            continue
        if raw.startswith("."):
            # Relative import
            abs_path = os.path.normpath(os.path.join(base_dir, raw)).replace("\\", "/")
            for ext in ["", ".js", ".ts", ".jsx", ".tsx", "/index.js", "/index.ts"]:
                candidate = abs_path + ext
                if candidate in path_set:
                    resolved.append(candidate)
                    break

    return list(set(resolved))


def _extract_imports(path: str, content: str, all_paths: List[str]) -> List[str]:
    lang = _detect_language(path)
    if lang == "python":
        return _extract_python_imports(content, path, all_paths)
    elif lang in ("javascript", "typescript"):
        return _extract_js_imports(content, path, all_paths)
    return []


class GraphEngine:
    """Builds and maintains the Neo4j file dependency graph."""

    def __init__(self, repository_id: str):
        self.repository_id = repository_id

    async def build_full_graph(self, log_callback: Optional[Any] = None):
        """
        Full rebuild of the file dependency graph for a repository.
        Called after the initial full sync.
        """
        files_col = get_collection("repository_files")
        cursor = files_col.find({"repository_id": self.repository_id})
        all_docs = await cursor.to_list(length=None)
        all_paths = [doc["path"] for doc in all_docs]

        if log_callback:
            await log_callback(
                "GraphEngine", "info",
                f"Building Neo4j file dependency graph for {len(all_docs)} files..."
            )

        # Clear existing graph for this repo (full rebuild)
        await delete_repo_graph(self.repository_id)

        processed = 0
        for doc in all_docs:
            path = doc["path"]
            content = doc.get("content", "")
            language = _detect_language(path)

            # Create File node
            await upsert_file_node(self.repository_id, path, language)

            # Parse imports and create relationships
            imports = _extract_imports(path, content, all_paths)
            for dep_path in imports:
                await upsert_import_relationship(self.repository_id, path, dep_path)

            processed += 1
            if log_callback and processed % 20 == 0:
                await log_callback(
                    "GraphEngine", "info",
                    f"Graph progress: {processed}/{len(all_docs)} files processed..."
                )

        if log_callback:
            await log_callback(
                "GraphEngine", "info",
                f"Neo4j graph construction complete. {processed} file nodes, relationships mapped."
            )

    async def update_files(
        self,
        changed_paths: List[str],
        deleted_paths: List[str],
        log_callback: Optional[Any] = None,
    ):
        """
        Incremental graph update — called after an incremental sync.
        Updates only the changed/deleted file nodes.
        """
        # Delete removed files
        for path in deleted_paths:
            await delete_file_node(self.repository_id, path)

        if not changed_paths:
            return

        # Fetch all file paths for import resolution
        files_col = get_collection("repository_files")
        cursor = files_col.find(
            {"repository_id": self.repository_id},
            {"path": 1}
        )
        all_path_docs = await cursor.to_list(length=None)
        all_paths = [d["path"] for d in all_path_docs]

        for path in changed_paths:
            # Fetch updated content
            doc = await files_col.find_one(
                {"repository_id": self.repository_id, "path": path}
            )
            if not doc:
                continue

            content = doc.get("content", "")
            language = _detect_language(path)

            # Upsert node (MERGE handles create-or-update)
            await upsert_file_node(self.repository_id, path, language)

            # Re-parse imports for updated file
            imports = _extract_imports(path, content, all_paths)
            for dep_path in imports:
                await upsert_import_relationship(self.repository_id, path, dep_path)

        if log_callback:
            await log_callback(
                "GraphEngine", "info",
                f"Neo4j graph incrementally updated: {len(changed_paths)} changed, {len(deleted_paths)} deleted."
            )
