import redis.asyncio as aioredis
from app.config import get_settings

settings = get_settings()

# ── Single shared pool instance ────────────────────────────────
_redis_pool: aioredis.Redis | None = None


async def get_redis() -> aioredis.Redis:
    """
    Returns a shared async Redis connection pool.
    Initialised once on first call, reused on all subsequent calls.
    """
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
            max_connections=50,
        )
    return _redis_pool


async def close_redis():
    """
    Gracefully close the Redis connection pool on shutdown.
    """
    global _redis_pool
    if _redis_pool is not None:
        await _redis_pool.aclose()
        _redis_pool = None