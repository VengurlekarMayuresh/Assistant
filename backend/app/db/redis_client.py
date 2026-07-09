import json
import logging
from typing import Any, Optional

import redis.asyncio as redis
from app.config import settings

logger = logging.getLogger(__name__)

# Global Redis client
_redis_client: Optional[redis.Redis] = None

# Default Time-To-Live (TTL) for session data in seconds (e.g., 30 minutes)
SESSION_TTL = 1800


async def init_redis():
    """Initialize the global Redis connection pool."""
    global _redis_client
    try:
        _redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
        # Ping to verify connection
        await _redis_client.ping()
        logger.info(f"Connected to Redis at {settings.REDIS_URL}")
    except Exception as e:
        logger.error(f"Failed to connect to Redis: {e}")
        _redis_client = None


async def close_redis():
    """Close the global Redis connection."""
    global _redis_client
    if _redis_client:
        await _redis_client.close()
        logger.info("Redis connection closed.")


def get_redis() -> Optional[redis.Redis]:
    """Get the Redis client instance. May return None if not connected."""
    return _redis_client


async def get_session_data(session_id: str, key: str) -> Optional[Any]:
    """
    Retrieve JSON data from the Redis session cache.
    Returns None if the key doesn't exist or Redis is unavailable.
    """
    r = get_redis()
    if not r:
        return None
    
    redis_key = f"session:{session_id}:{key}"
    try:
        data = await r.get(redis_key)
        if data:
            return json.loads(data)
    except Exception as e:
        logger.warning(f"Failed to get Redis key {redis_key}: {e}")
    return None


async def set_session_data(session_id: str, key: str, value: Any, ttl: int = SESSION_TTL):
    """
    Store JSON serializable data in the Redis session cache with a TTL.
    Does nothing if Redis is unavailable.
    """
    r = get_redis()
    if not r:
        return
    
    redis_key = f"session:{session_id}:{key}"
    try:
        json_data = json.dumps(value)
        await r.setex(redis_key, ttl, json_data)
    except Exception as e:
        logger.warning(f"Failed to set Redis key {redis_key}: {e}")
