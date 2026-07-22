"""
Qdrant Cloud vector database client.

Collections:
  - knowledge_objects  — one vector per KnowledgeObject summary
  - repository_files   — one vector per cached file (path + first 500 chars)

Embedding model: all-MiniLM-L6-v2 (384 dimensions, runs locally on the backend, no external API cost)

Cloud auth: set QDRANT_URL and QDRANT_API_KEY from your Qdrant Cloud dashboard.
"""
import logging
from typing import List, Dict, Any, Optional

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance,
    VectorParams,
    PointStruct,
    Filter,
    FieldCondition,
    MatchValue,
    ScoredPoint,
)
from sentence_transformers import SentenceTransformer

from app.config import settings

logger = logging.getLogger(__name__)

# ── Singleton instances ────────────────────────────────────────────────────
_qdrant_client: AsyncQdrantClient | None = None
_embedder: SentenceTransformer | None = None

# Qdrant collection names
COLLECTION_KNOWLEDGE = "knowledge_objects"
COLLECTION_FILES = "repository_files"
COLLECTION_MODULES = "repository_modules"

# Embedding vector size for all-MiniLM-L6-v2
VECTOR_SIZE = 384


def get_embedder() -> SentenceTransformer:
    """Lazy-load the local embedding model."""
    global _embedder
    if _embedder is None:
        logger.info("Loading sentence-transformer model (all-MiniLM-L6-v2)...")
        _embedder = SentenceTransformer("all-MiniLM-L6-v2")
        logger.info("Embedding model loaded.")
    return _embedder


def embed_text(text: str) -> List[float]:
    """Encode a single text string into a vector."""
    return get_embedder().encode(text, normalize_embeddings=True).tolist()


def embed_texts(texts: List[str]) -> List[List[float]]:
    """Encode a batch of text strings into vectors."""
    return get_embedder().encode(texts, normalize_embeddings=True).tolist()


def get_qdrant_client() -> AsyncQdrantClient:
    """Return the singleton Qdrant async client."""
    if _qdrant_client is None:
        raise RuntimeError("Qdrant client not initialized. Call init_qdrant_collections() on startup.")
    return _qdrant_client


async def init_qdrant_collections():
    """
    Initialize Qdrant Cloud client and ensure collections exist.
    Call once at FastAPI startup.

    Qdrant Cloud requires both QDRANT_URL and QDRANT_API_KEY.
    Self-hosted Qdrant works with just QDRANT_URL (no key needed).
    """
    global _qdrant_client

    logger.info(f"Connecting to Qdrant Cloud at {settings.QDRANT_URL} ...")

    # Build client kwargs — api_key is required for Qdrant Cloud
    client_kwargs: dict = {"url": settings.QDRANT_URL}
    if settings.QDRANT_API_KEY:
        client_kwargs["api_key"] = settings.QDRANT_API_KEY
    else:
        logger.warning(
            "QDRANT_API_KEY is not set. Connection will be attempted without authentication. "
            "This will fail for Qdrant Cloud — set your API key in .env."
        )

    _qdrant_client = AsyncQdrantClient(**client_kwargs)

    existing = await _qdrant_client.get_collections()
    existing_names = {c.name for c in existing.collections}

    # Create knowledge_objects collection if missing
    if COLLECTION_KNOWLEDGE not in existing_names:
        await _qdrant_client.create_collection(
            collection_name=COLLECTION_KNOWLEDGE,
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
        )
        await _qdrant_client.create_payload_index(
            collection_name=COLLECTION_KNOWLEDGE,
            field_name="repository_id",
            field_schema="keyword",
        )
        logger.info(f"Qdrant collection '{COLLECTION_KNOWLEDGE}' created with index.")
    else:
        logger.info(f"Qdrant collection '{COLLECTION_KNOWLEDGE}' already exists.")

    # Create repository_files collection if missing
    if COLLECTION_FILES not in existing_names:
        await _qdrant_client.create_collection(
            collection_name=COLLECTION_FILES,
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
        )
        await _qdrant_client.create_payload_index(
            collection_name=COLLECTION_FILES,
            field_name="repository_id",
            field_schema="keyword",
        )
        logger.info(f"Qdrant collection '{COLLECTION_FILES}' created with index.")
    else:
        logger.info(f"Qdrant collection '{COLLECTION_FILES}' already exists.")

    # Create repository_modules collection if missing
    if COLLECTION_MODULES not in existing_names:
        await _qdrant_client.create_collection(
            collection_name=COLLECTION_MODULES,
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
        )
        await _qdrant_client.create_payload_index(
            collection_name=COLLECTION_MODULES,
            field_name="repository_id",
            field_schema="keyword",
        )
        logger.info(f"Qdrant collection '{COLLECTION_MODULES}' created with index.")
    else:
        logger.info(f"Qdrant collection '{COLLECTION_MODULES}' already exists.")

    logger.info("Qdrant Cloud initialization complete.")


async def upsert_knowledge_object_vector(
    point_id: str,
    repository_id: str,
    category: str,
    summary: str,
    version: int,
):
    """Upsert a KnowledgeObject embedding into Qdrant."""
    client = get_qdrant_client()
    text = f"{category}: {summary}"
    vector = embed_text(text)

    await client.upsert(
        collection_name=COLLECTION_KNOWLEDGE,
        points=[
            PointStruct(
                id=_str_to_int_id(point_id),
                vector=vector,
                payload={
                    "mongo_id": point_id,
                    "repository_id": repository_id,
                    "category": category,
                    "version": version,
                },
            )
        ],
    )


async def upsert_module_vector(
    module_id: str,
    repository_id: str,
    module_name: str,
    description: str,
    files: List[str],
):
    """Upsert a Repository Map module embedding into Qdrant."""
    client = get_qdrant_client()
    text = f"Module: {module_name}\nDescription: {description}"
    vector = embed_text(text)

    await client.upsert(
        collection_name=COLLECTION_MODULES,
        points=[
            PointStruct(
                id=_str_to_int_id(module_id),
                vector=vector,
                payload={
                    "mongo_id": module_id,
                    "repository_id": repository_id,
                    "module_name": module_name,
                    "files": files,
                },
            )
        ],
    )


async def upsert_file_chunks(
    mongo_id: str,
    repository_id: str,
    path: str,
    chunks: List[str],
):
    """Upsert multiple embedding chunks for a single RepositoryFile into Qdrant."""
    if not chunks:
        return
        
    client = get_qdrant_client()
    
    # Prefix chunks with file path so the vector carries context
    texts_to_embed = [f"{path}\n{chunk}" for chunk in chunks]
    vectors = embed_texts(texts_to_embed)

    points = []
    for i, (chunk_text, vector) in enumerate(zip(chunks, vectors)):
        # Generate stable ID for this specific chunk
        chunk_id_str = f"{mongo_id}_chunk_{i}"
        points.append(
            PointStruct(
                id=_str_to_int_id(chunk_id_str),
                vector=vector,
                payload={
                    "mongo_id": mongo_id,
                    "repository_id": repository_id,
                    "path": path,
                    "chunk_index": i,
                },
            )
        )

    await client.upsert(
        collection_name=COLLECTION_FILES,
        points=points,
    )


async def delete_file_vector(mongo_id: str):
    """Remove all file chunks from Qdrant when the file is deleted from the repo."""
    client = get_qdrant_client()
    await client.delete(
        collection_name=COLLECTION_FILES,
        points_selector=Filter(
            must=[FieldCondition(key="mongo_id", match=MatchValue(value=mongo_id))]
        ),
    )


async def delete_repository_modules(repository_id: str):
    """Remove all module vectors for a repository."""
    client = get_qdrant_client()
    await client.delete(
        collection_name=COLLECTION_MODULES,
        points_selector=Filter(
            must=[FieldCondition(key="repository_id", match=MatchValue(value=repository_id))]
        ),
    )


async def search_knowledge_objects(
    query: str,
    repository_id: str,
    top_k: int = 5,
) -> List[ScoredPoint]:
    """Semantic search over KnowledgeObject summaries."""
    client = get_qdrant_client()
    vector = embed_text(query)

    results = await client.query_points(
        collection_name=COLLECTION_KNOWLEDGE,
        query=vector,
        query_filter=Filter(
            must=[FieldCondition(key="repository_id", match=MatchValue(value=repository_id))]
        ),
        limit=top_k,
        with_payload=True,
    )
    return results.points


async def search_repository_files(
    query: str,
    repository_id: str,
    top_k: int = 8,
) -> List[ScoredPoint]:
    """Semantic search over cached repository file contents."""
    client = get_qdrant_client()
    vector = embed_text(query)

    results = await client.query_points(
        collection_name=COLLECTION_FILES,
        query=vector,
        query_filter=Filter(
            must=[FieldCondition(key="repository_id", match=MatchValue(value=repository_id))]
        ),
        limit=top_k,
        with_payload=True,
    )
    return results.points


async def search_repository_modules(
    query: str,
    repository_id: str,
    top_k: int = 2,
) -> List[ScoredPoint]:
    """Semantic search over high-level repository modules."""
    client = get_qdrant_client()
    vector = embed_text(query)

    results = await client.query_points(
        collection_name=COLLECTION_MODULES,
        query=vector,
        query_filter=Filter(
            must=[FieldCondition(key="repository_id", match=MatchValue(value=repository_id))]
        ),
        limit=top_k,
        with_payload=True,
    )
    return results.points


def _str_to_int_id(mongo_id: str) -> int:
    """
    Qdrant requires integer or UUID point IDs.
    Convert MongoDB ObjectId hex string to a stable integer via hashing.
    """
    return abs(hash(mongo_id)) % (2**53)
