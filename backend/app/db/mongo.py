"""
MongoDB Motor async client.

Collections:
  - repositories
  - repository_files
  - knowledge_objects
  - chat_sessions
  - chat_messages
  - agent_action_logs

TTL Policy: All documents expire 15 days after creation.
"""
import logging
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase, AsyncIOMotorCollection
from app.config import settings

logger = logging.getLogger(__name__)

# Module-level singleton — created once on startup
_client: AsyncIOMotorClient | None = None
_db: AsyncIOMotorDatabase | None = None


def get_client() -> AsyncIOMotorClient:
    """Return the singleton Motor client (must call init_db first)."""
    if _client is None:
        raise RuntimeError("MongoDB client not initialized. Call init_db() on startup.")
    return _client


def get_database() -> AsyncIOMotorDatabase:
    """Return the singleton Motor database handle."""
    if _db is None:
        raise RuntimeError("MongoDB not initialized. Call init_db() on startup.")
    return _db


def get_collection(name: str) -> AsyncIOMotorCollection:
    """Return a named collection from the singleton database."""
    return get_database()[name]


async def init_db():
    """
    Initialize MongoDB Motor client and create indexes.
    Call once at FastAPI startup.
    """
    global _client, _db

    logger.info(f"Connecting to MongoDB at {settings.MONGODB_URL} ...")
    _client = AsyncIOMotorClient(settings.MONGODB_URL)
    _db = _client[settings.MONGODB_DB_NAME]

    # ── TTL Configuration ──────────────────────────────────────────────────
    TTL_SECONDS = 15 * 24 * 60 * 60  # 15 days = 1,296,000 seconds

    # ── Indexes ───────────────────────────────────────────────────────────
    await _db["repositories"].create_index("url", unique=True)
    await _db["repositories"].create_index("owner")
    await _db["repositories"].create_index("created_at", expireAfterSeconds=TTL_SECONDS)

    await _db["repository_files"].create_index([("repository_id", 1), ("path", 1)], unique=True)
    await _db["repository_files"].create_index("path")
    await _db["repository_files"].create_index("last_updated", expireAfterSeconds=TTL_SECONDS)

    await _db["knowledge_objects"].create_index([("repository_id", 1), ("category", 1)])
    await _db["knowledge_objects"].create_index("repository_id")
    await _db["knowledge_objects"].create_index("last_updated", expireAfterSeconds=TTL_SECONDS)

    await _db["chat_sessions"].create_index("repository_id")
    await _db["chat_sessions"].create_index([("created_at", -1)])
    await _db["chat_sessions"].create_index("created_at", expireAfterSeconds=TTL_SECONDS)

    await _db["chat_messages"].create_index([("session_id", 1), ("created_at", 1)])
    await _db["chat_messages"].create_index("created_at", expireAfterSeconds=TTL_SECONDS)

    await _db["agent_action_logs"].create_index([("session_id", 1), ("created_at", 1)])
    await _db["agent_action_logs"].create_index("created_at", expireAfterSeconds=TTL_SECONDS)

    logger.info("MongoDB indexes + TTL policies (15-day expiry) created successfully.")


async def close_db():
    """Close Motor client. Call on FastAPI shutdown."""
    global _client
    if _client:
        _client.close()
        logger.info("MongoDB connection closed.")
