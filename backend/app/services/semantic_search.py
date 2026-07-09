"""
Semantic Search Service (Qdrant-powered).

Replaces the old keyword LIKE-based PostgreSQL search with true
embedding-based vector similarity search using Qdrant.

Flow:
  1. Encode the user query into a 384-dim vector (all-MiniLM-L6-v2).
  2. Search `knowledge_objects` Qdrant collection → top matching KO summaries.
  3. Search `repository_files` Qdrant collection → top matching file paths.
  4. Fetch full documents from MongoDB using the returned mongo_id payloads.
  5. Return (files, knowledge_objects) for the planner node to evaluate.
"""
import logging
from typing import List, Tuple, Dict, Any, Optional

from app.db.mongo import get_collection
from app.db.qdrant_client import (
    search_knowledge_objects,
    search_repository_files,
)
from bson import ObjectId

logger = logging.getLogger(__name__)


def _doc_to_dict(doc: dict) -> dict:
    """Convert MongoDB _id ObjectId to string 'id' field."""
    if doc and "_id" in doc:
        doc["id"] = str(doc.pop("_id"))
    return doc


class SemanticSearchService:
    """
    Qdrant-backed semantic search for local repository knowledge cache.
    """

    def __init__(self, repository_id: str):
        self.repository_id = repository_id

    async def search_local_cache(
        self,
        query: str,
        ko_top_k: int = 5,
        file_top_k: int = 8,
        score_threshold: float = 0.30,
        file_filter_list: Optional[List[str]] = None,
    ) -> Tuple[List[Dict], List[Dict]]:
        """
        Semantic search over locally cached Knowledge Objects and Repository Files.

        Returns:
            (matching_files, matching_knowledge_objects)
            Both are lists of MongoDB document dicts, sorted by relevance.
        """
        # ── 1. Search Knowledge Objects ───────────────────────────────────
        ko_hits = await search_knowledge_objects(
            query=query,
            repository_id=self.repository_id,
            top_k=ko_top_k,
        )

        matching_kos = []
        for hit in ko_hits:
            if hit.score < score_threshold:
                continue
            mongo_id = hit.payload.get("mongo_id")
            if not mongo_id:
                continue
            try:
                ko_col = get_collection("knowledge_objects")
                doc = await ko_col.find_one({"_id": ObjectId(mongo_id)})
                if doc:
                    doc = _doc_to_dict(doc)
                    doc["_qdrant_score"] = hit.score
                    matching_kos.append(doc)
            except Exception as e:
                logger.error(f"Failed to fetch KO {mongo_id} from MongoDB: {e}")

        logger.info(
            f"[SemanticSearch] KnowledgeObjects: {len(matching_kos)} hits "
            f"(threshold={score_threshold}) for query='{query[:60]}'"
        )

        # ── 2. Search Repository Files ────────────────────────────────────
        from app.db.qdrant_client import get_qdrant_client, COLLECTION_FILES, embed_text
        from qdrant_client.models import Filter, FieldCondition, MatchValue, MatchAny

        qdrant = get_qdrant_client()
        vector = embed_text(query)
        
        must_conditions = [FieldCondition(key="repository_id", match=MatchValue(value=self.repository_id))]
        if file_filter_list is not None:
            must_conditions.append(FieldCondition(key="path", match=MatchAny(any=file_filter_list)))

        file_hits = await qdrant.query_points(
            collection_name=COLLECTION_FILES,
            query=vector,
            query_filter=Filter(must=must_conditions),
            limit=file_top_k * 3, # fetch more chunks since we deduplicate by file
            with_payload=True,
        )

        matching_files = []
        seen_mongo_ids = set()
        
        for hit in file_hits:
            if hit.score < score_threshold:
                continue
            mongo_id = hit.payload.get("mongo_id")
            if not mongo_id or mongo_id in seen_mongo_ids:
                continue
                
            seen_mongo_ids.add(mongo_id)
            try:
                files_col = get_collection("repository_files")
                doc = await files_col.find_one({"_id": ObjectId(mongo_id)})
                if doc:
                    doc = _doc_to_dict(doc)
                    doc["_qdrant_score"] = hit.score
                    matching_files.append(doc)
            except Exception as e:
                logger.error(f"Failed to fetch file {mongo_id} from MongoDB: {e}")

        logger.info(
            f"[SemanticSearch] RepositoryFiles: {len(matching_files)} hits "
            f"(threshold={score_threshold}) for query='{query[:60]}'"
        )

        return matching_files, matching_kos
