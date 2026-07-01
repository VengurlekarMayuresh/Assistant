"""
Neo4j AuraDB async driver for the File Dependency Graph.

Graph schema:
  (:File {path, repo_id, language})  -[:IMPORTS]->  (:File {...})

This powers queries like:
  "What files depend on auth.py?"
  "Show me the import chain from payments.py"

Cloud: set NEO4J_URI (neo4j+s://xxx.databases.neo4j.io), NEO4J_USER, NEO4J_PASSWORD
from your Neo4j AuraDB instance dashboard.
"""
import logging
import os
import re
from typing import List, Dict, Any, Optional

from bson import ObjectId
from neo4j import AsyncGraphDatabase, AsyncDriver

from app.config import settings
from app.db.mongo import get_collection
from app.services.github_service import GitHubService

logger = logging.getLogger(__name__)

_driver: AsyncDriver | None = None

PYTHON_IMPORT_RE = re.compile(
    r"^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.,\s]+))",
    re.MULTILINE,
)
JS_IMPORT_RE = re.compile(
    r"""(?:import\s+.*?from\s+['\"]([^'\"]+)['\"]|require\s*\(\s*['\"]([^'\"]+)['\"]\s*\))""",
    re.MULTILINE,
)


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


def _match_paths(candidates: List[str], all_paths: List[str]) -> List[str]:
    path_set = set(all_paths)
    resolved: List[str] = []
    for candidate in candidates:
        for path in path_set:
            if path == candidate or path.endswith("/" + candidate) or path.endswith(candidate):
                resolved.append(path)
    return list(set(resolved))


def _extract_python_imports(content: str, all_paths: List[str]) -> List[str]:
    raw_modules = []
    for match in PYTHON_IMPORT_RE.finditer(content):
        module = match.group(1) or match.group(2)
        if module:
            for part in module.split(","):
                raw_modules.append(part.strip().split(" ")[0])

    candidates: List[str] = []
    for module in raw_modules:
        root = module.replace(".", "/")
        candidates.extend([root + ".py", root + "/__init__.py"])

    return _match_paths(candidates, all_paths)


def _extract_js_imports(content: str, file_path: str, all_paths: List[str]) -> List[str]:
    base_dir = os.path.dirname(file_path)
    candidates: List[str] = []

    for match in JS_IMPORT_RE.finditer(content):
        raw = match.group(1) or match.group(2)
        if not raw or raw.startswith("@") and "/" not in raw[1:]:
            continue

        candidate_bases: List[str] = []
        if raw.startswith("."):
            candidate_bases.append(os.path.normpath(os.path.join(base_dir, raw)).replace("\\", "/"))
        else:
            normalized = raw.lstrip("@/").lstrip("~/")
            candidate_bases.extend([
                normalized,
                f"src/{normalized}",
                f"app/{normalized}",
                f"components/{normalized}",
                f"lib/{normalized}",
                f"pages/{normalized}",
            ])

        for base in candidate_bases:
            for ext in ["", ".js", ".ts", ".jsx", ".tsx", ".mjs", ".cjs", "/index.js", "/index.ts", "/index.jsx", "/index.tsx"]:
                candidates.append(base + ext)

    return _match_paths(candidates, all_paths)


def _extract_imports(path: str, content: str, all_paths: List[str]) -> List[str]:
    lang = _detect_language(path)
    if lang == "python":
        return _extract_python_imports(content, all_paths)
    if lang in ("javascript", "typescript"):
        return _extract_js_imports(content, path, all_paths)
    return []


async def _load_local_repository_files(repo_id: str) -> List[Dict[str, Any]]:
    files_col = get_collection("repository_files")
    cursor = files_col.find({"repository_id": repo_id})
    return await cursor.to_list(length=None)


async def _load_repository_context(repo_id: str) -> tuple[dict[str, Any], List[str]]:
    repos_col = get_collection("repositories")
    try:
        repo = await repos_col.find_one({"_id": ObjectId(repo_id)})
    except Exception:
        repo = await repos_col.find_one({"_id": repo_id})
    if not repo:
        return {}, []

    tree_items = (repo.get("structure_json") or {}).get("tree", [])
    all_paths = [item.get("path", "") for item in tree_items if item.get("path")]
    return repo, all_paths


def _prune_tree_paths(tree_items: List[Dict[str, Any]], max_files: int = 150) -> List[str]:
    code_extensions = {
        ".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".rs", ".java",
        ".rb", ".php", ".cs", ".cpp", ".c", ".h", ".swift", ".kt",
        ".json", ".yaml", ".yml", ".toml", ".env", ".md", ".txt",
        ".html", ".css", ".scss", ".sql",
    }
    excluded_dirs = {
        "node_modules", ".git", "__pycache__", ".venv", "venv",
        "dist", "build", ".next", "vendor", "coverage",
    }

    paths: List[str] = []
    for item in tree_items:
        if item.get("type") != "blob":
            continue
        path = item.get("path", "")
        if not path:
            continue
        if any(part in excluded_dirs for part in path.split("/")):
            continue
        ext = "." + path.rsplit(".", 1)[-1].lower() if "." in path else ""
        if ext in code_extensions or path in {"Makefile", "Dockerfile", "Procfile"}:
            paths.append(path)
        if len(paths) >= max_files:
            break
    return paths


async def _fetch_repo_file_content(owner: str, name: str, path: str) -> str:
    gh = GitHubService()
    for branch in ["main", "master"]:
        try:
            return await gh.fetch_file_content(owner, name, path, branch)
        except Exception:
            continue
    raise RuntimeError(f"Failed to fetch file content for {path}")


async def _build_local_dependency_maps(repo_id: str) -> tuple[Dict[str, List[str]], Dict[str, List[str]]]:
    docs = await _load_local_repository_files(repo_id)
    repo, repo_paths = await _load_repository_context(repo_id)
    all_paths = list({doc.get("path", "") for doc in docs if doc.get("path")})
    all_paths.extend([path for path in repo_paths if path not in all_paths])

    outgoing: Dict[str, List[str]] = {}
    incoming: Dict[str, List[str]] = {}

    doc_by_path = {doc.get("path", ""): doc for doc in docs if doc.get("path")}

    if repo and repo_paths:
        key_paths = _prune_tree_paths((repo.get("structure_json") or {}).get("tree", []), max_files=150)
        for path in key_paths:
            if path not in all_paths:
                all_paths.append(path)
            if path in doc_by_path:
                continue
            try:
                content = await _fetch_repo_file_content(repo["owner"], repo["name"], path)
                doc_by_path[path] = {"path": path, "content": content}
            except Exception:
                continue

    for path, doc in doc_by_path.items():
        path = doc.get("path", "")
        content = doc.get("content", "")
        deps = _extract_imports(path, content, all_paths)
        outgoing[path] = deps
        for dep in deps:
            incoming.setdefault(dep, []).append(path)

    return outgoing, incoming


def _walk_dependency_graph(start: str, adjacency: Dict[str, List[str]], depth: int) -> List[str]:
    seen = {start}
    frontier = [start]
    result: List[str] = []

    for _ in range(depth):
        next_frontier: List[str] = []
        for node in frontier:
            for neighbor in adjacency.get(node, []):
                if neighbor in seen:
                    continue
                seen.add(neighbor)
                result.append(neighbor)
                next_frontier.append(neighbor)
        frontier = next_frontier
        if not frontier:
            break

    return result


async def _get_local_dependencies(repo_id: str, path: str, depth: int) -> List[Dict[str, Any]]:
    outgoing, _ = await _build_local_dependency_maps(repo_id)
    deps = _walk_dependency_graph(path, outgoing, depth)
    return [{"path": dep, "depth": 1} for dep in deps]


async def _get_local_dependents(repo_id: str, path: str, depth: int) -> List[Dict[str, Any]]:
    _, incoming = await _build_local_dependency_maps(repo_id)
    deps = _walk_dependency_graph(path, incoming, depth)
    return [{"path": dep, "depth": 1} for dep in deps]


async def _get_local_related_files(repo_id: str, seed_paths: List[str], depth: int) -> List[str]:
    outgoing, incoming = await _build_local_dependency_maps(repo_id)
    related = set(seed_paths)

    for seed in seed_paths:
        related.update(_walk_dependency_graph(seed, outgoing, depth))
        related.update(_walk_dependency_graph(seed, incoming, depth))

    return list(related)


def _log_neo4j_error(action: str, error: Exception) -> None:
    logger.warning(f"Neo4j {action} failed: {error}")


async def init_neo4j_driver():
    """
    Initialize Neo4j AuraDB async driver. Call once at FastAPI startup.

    Supports both:
      - neo4j+s://xxx.databases.neo4j.io   (AuraDB / cloud, TLS enforced)
      - bolt://localhost:7687               (self-hosted, no TLS)

    The driver automatically handles TLS based on the URI scheme:
      neo4j+s:// and bolt+s:// enable encrypted connections.
    """
    global _driver
    logger.info(f"Connecting to Neo4j AuraDB at {settings.NEO4J_URI} ...")

    _driver = AsyncGraphDatabase.driver(
        settings.NEO4J_URI,
        auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
        # AuraDB requires encrypted connections (handled automatically by neo4j+s://)
        # max_connection_lifetime keeps long-lived connections healthy
        max_connection_lifetime=3600,
        max_connection_pool_size=50,
        connection_acquisition_timeout=30,
    )

    # Verify connectivity (will raise if credentials or URL are wrong)
    await _driver.verify_connectivity()

    # Create uniqueness constraint for File nodes
    async with _driver.session() as session:
        await session.run(
            "CREATE CONSTRAINT file_path_repo IF NOT EXISTS "
            "FOR (f:File) REQUIRE (f.path, f.repo_id) IS UNIQUE"
        )
    logger.info("Neo4j AuraDB driver initialized and constraints created.")


def get_neo4j_driver() -> AsyncDriver:
    """Return the singleton Neo4j async driver."""
    if _driver is None:
        raise RuntimeError("Neo4j driver not initialized. Call init_neo4j_driver() on startup.")
    return _driver


async def close_neo4j_driver():
    """Close Neo4j driver. Call on FastAPI shutdown."""
    global _driver
    if _driver:
        await _driver.close()
        logger.info("Neo4j driver closed.")


async def upsert_file_node(repo_id: str, path: str, language: str = "unknown"):
    """Create or update a File node in Neo4j."""
    try:
        driver = get_neo4j_driver()
        async with driver.session() as session:
            await session.run(
                """
                MERGE (f:File {path: $path, repo_id: $repo_id})
                SET f.language = $language
                """,
                path=path,
                repo_id=repo_id,
                language=language,
            )
    except Exception as error:
        _log_neo4j_error(f"upsert_file_node({path})", error)


async def upsert_import_relationship(
    repo_id: str,
    from_path: str,
    to_path: str,
):
    """Create IMPORTS relationship between two File nodes."""
    try:
        driver = get_neo4j_driver()
        async with driver.session() as session:
            await session.run(
                """
                MERGE (a:File {path: $from_path, repo_id: $repo_id})
                MERGE (b:File {path: $to_path, repo_id: $repo_id})
                MERGE (a)-[:IMPORTS]->(b)
                """,
                from_path=from_path,
                to_path=to_path,
                repo_id=repo_id,
            )
    except Exception as error:
        _log_neo4j_error(f"upsert_import_relationship({from_path} -> {to_path})", error)


async def clear_file_imports(repo_id: str, path: str):
    """Remove all outgoing IMPORTS relationships for a given file."""
    try:
        driver = get_neo4j_driver()
        async with driver.session() as session:
            await session.run(
                """
                MATCH (a:File {path: $path, repo_id: $repo_id})-[r:IMPORTS]->()
                DELETE r
                """,
                path=path,
                repo_id=repo_id,
            )
    except Exception as error:
        _log_neo4j_error(f"clear_file_imports({path})", error)


async def delete_file_node(repo_id: str, path: str):
    """Remove a File node and all its relationships."""
    try:
        driver = get_neo4j_driver()
        async with driver.session() as session:
            await session.run(
                """
                MATCH (f:File {path: $path, repo_id: $repo_id})
                DETACH DELETE f
                """,
                path=path,
                repo_id=repo_id,
            )
    except Exception as error:
        _log_neo4j_error(f"delete_file_node({path})", error)


async def get_file_dependencies(repo_id: str, path: str, depth: int = 2) -> List[Dict[str, Any]]:
    """
    Return all files that `path` depends on (outgoing IMPORTS), up to `depth` hops.
    Returns a list of {"path": str, "depth": int} dicts.
    """
    try:
        driver = get_neo4j_driver()
        async with driver.session() as session:
            result = await session.run(
                f"""
                MATCH p=(f:File {{path: $path, repo_id: $repo_id}})-[:IMPORTS*1..{depth}]->(dep:File)
                RETURN DISTINCT dep.path AS path, length(p) AS depth
                ORDER BY depth
                """,
                path=path,
                repo_id=repo_id,
            )
            records = await result.data()
            if records:
                return records
    except Exception as error:
        _log_neo4j_error(f"get_file_dependencies({path})", error)

    return await _get_local_dependencies(repo_id, path, depth)


async def get_file_dependents(repo_id: str, path: str, depth: int = 2) -> List[Dict[str, Any]]:
    """
    Return all files that depend ON `path` (incoming IMPORTS), up to `depth` hops.
    Returns a list of {"path": str, "depth": int} dicts.
    """
    try:
        driver = get_neo4j_driver()
        async with driver.session() as session:
            result = await session.run(
                f"""
                MATCH p=(dep:File)-[:IMPORTS*1..{depth}]->(f:File {{path: $path, repo_id: $repo_id}})
                RETURN DISTINCT dep.path AS path, length(p) AS depth
                ORDER BY depth
                """,
                path=path,
                repo_id=repo_id,
            )
            records = await result.data()
            if records:
                return records
    except Exception as error:
        _log_neo4j_error(f"get_file_dependents({path})", error)

    return await _get_local_dependents(repo_id, path, depth)


async def get_related_files_for_query(
    repo_id: str,
    seed_paths: List[str],
    depth: int = 1,
) -> List[str]:
    """
    Given a list of seed file paths (from semantic search),
    expand context by fetching their immediate import neighbors from the graph.
    Returns a deduplicated list of related file paths.
    """
    if not seed_paths:
        return []

    try:
        driver = get_neo4j_driver()
        related = set(seed_paths)

        async with driver.session() as session:
            result = await session.run(
                f"""
                UNWIND $paths AS p
                MATCH (f:File {{path: p, repo_id: $repo_id}})-[:IMPORTS*1..{depth}]-(neighbor:File)
                RETURN DISTINCT neighbor.path AS path
                """,
                paths=seed_paths,
                repo_id=repo_id,
            )
            records = await result.data()
            for rec in records:
                related.add(rec["path"])

        if len(related) > len(seed_paths):
            return list(related)
    except Exception as error:
        _log_neo4j_error(f"get_related_files_for_query({len(seed_paths)} seeds)", error)

    return await _get_local_related_files(repo_id, seed_paths, depth)


async def delete_repo_graph(repo_id: str):
    """Delete all File nodes for a repository (used on full re-sync)."""
    try:
        driver = get_neo4j_driver()
        async with driver.session() as session:
            await session.run(
                "MATCH (f:File {repo_id: $repo_id}) DETACH DELETE f",
                repo_id=repo_id,
            )
    except Exception as error:
        _log_neo4j_error(f"delete_repo_graph({repo_id})", error)
