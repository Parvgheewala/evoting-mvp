from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
import redis.asyncio as aioredis

from app.database import get_db
from app.redis_client import get_redis

router = APIRouter()


# ── Basic liveness check ───────────────────────────────────────
@router.get("/")
async def health_root():
    return {
        "status": "ok",
        "service": "evoting-backend"
    }


# ── PostgreSQL connectivity check ──────────────────────────────
@router.get("/db")
async def health_db(db: AsyncSession = Depends(get_db)):
    result = await db.execute(text("SELECT 1"))
    return {
        "status": "ok",
        "db": "connected",
        "result": result.scalar()
    }


# ── Redis connectivity check ───────────────────────────────────
@router.get("/redis")
async def health_redis(redis: aioredis.Redis = Depends(get_redis)):
    pong = await redis.ping()
    return {
        "status": "ok",
        "redis": "connected",
        "ping": pong
    }


# ── Full system check ──────────────────────────────────────────
@router.get("/full")
async def health_full(
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    db_ok = (await db.execute(text("SELECT 1"))).scalar() == 1
    redis_ok = await redis.ping()
    all_ok = db_ok and redis_ok

    return {
        "status": "ok" if all_ok else "degraded",
        "components": {
            "database": "ok" if db_ok else "error",
            "redis": "ok" if redis_ok else "error",
        },
    }