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
from typing import List, Dict, Any, Optional

from neo4j import AsyncGraphDatabase, AsyncDriver

from app.config import settings

logger = logging.getLogger(__name__)

_driver: AsyncDriver | None = None


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
            return records
    except Exception as error:
        _log_neo4j_error(f"get_file_dependencies({path})", error)
        return []


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
            return records
    except Exception as error:
        _log_neo4j_error(f"get_file_dependents({path})", error)
        return []


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

        return list(related)
    except Exception as error:
        _log_neo4j_error(f"get_related_files_for_query({len(seed_paths)} seeds)", error)
        return list(seed_paths)


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
