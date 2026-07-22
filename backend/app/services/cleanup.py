"""
Startup Cleanup Service — Purges orphan data from Qdrant and Neo4j.

MongoDB TTL indexes handle automatic document expiration, but Qdrant
vectors and Neo4j graph nodes have no built-in TTL. This service runs
once on each server startup and removes data whose parent repository
has already been deleted by MongoDB's TTL.
"""
import logging
from typing import Set

from app.db.mongo import get_collection
from app.db.qdrant_client import get_qdrant_client, COLLECTION_KNOWLEDGE, COLLECTION_FILES

logger = logging.getLogger(__name__)


async def _get_live_repo_ids() -> Set[str]:
    """Fetch all repository IDs that still exist in MongoDB."""
    repos_col = get_collection("repositories")
    cursor = repos_col.find({}, {"_id": 1})
    docs = await cursor.to_list(length=10000)
    return {str(doc["_id"]) for doc in docs}


async def _cleanup_qdrant(live_repo_ids: Set[str]):
    """Delete Qdrant vectors whose repository_id no longer exists in MongoDB."""
    try:
        client = get_qdrant_client()

        for collection_name in [COLLECTION_KNOWLEDGE, COLLECTION_FILES]:
            # Scroll through all points and collect orphan IDs
            orphan_ids = []
            offset = None
            while True:
                scroll_kwargs = {
                    "collection_name": collection_name,
                    "limit": 100,
                    "with_payload": True,
                    "with_vectors": False,
                }
                if offset is not None:
                    scroll_kwargs["offset"] = offset

                results = await client.scroll(**scroll_kwargs)
                points, next_offset = results

                for point in points:
                    repo_id = (point.payload or {}).get("repository_id")
                    if repo_id and repo_id not in live_repo_ids:
                        orphan_ids.append(point.id)

                if next_offset is None or not points:
                    break
                offset = next_offset

            if orphan_ids:
                await client.delete(
                    collection_name=collection_name,
                    points_selector=orphan_ids,
                )
                logger.info(
                    f"[Cleanup] Deleted {len(orphan_ids)} orphan vectors "
                    f"from Qdrant '{collection_name}'."
                )
    except Exception as e:
        logger.warning(f"[Cleanup] Qdrant cleanup failed (non-fatal): {e}")



async def run_startup_cleanup():
    """
    Run once on server startup. Removes Qdrant vectors
    for repositories that have been auto-deleted by MongoDB TTL.
    """
    logger.info("[Cleanup] Running startup cleanup for orphan data...")
    live_repo_ids = await _get_live_repo_ids()
    logger.info(f"[Cleanup] Found {len(live_repo_ids)} live repositories in MongoDB.")

    await _cleanup_qdrant(live_repo_ids)

    logger.info("[Cleanup] Startup cleanup complete.")
