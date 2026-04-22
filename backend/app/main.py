from contextlib import asynccontextmanager
from app.routers import registration
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import logging
from app.models.voter import Voter
from app.models.citizen_registry import CitizenRegistry
from app.database import engine, Base
from app.redis_client import close_redis
from app.routers import health


logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""

    # ── Phase 1: Infrastructure ───────────────────────────────────────────
    logger.info("Starting E-Voting backend ...")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables initialised.")

    # ── Phase 2: Registration services — eager import check ───────────────
    # Importing here ensures any missing dependency (insightface, cv2, etc.)
    # raises at startup with a clear error rather than on the first request.
    try:
        from app.services import liveness_service, identity_service  # noqa: F401
        from app.services import registration_service                 # noqa: F401
        logger.info("Phase 2 services loaded: liveness, identity, registration.")
    except ImportError as exc:
        logger.error(f"Phase 2 service import failed: {exc}")
        logger.error(
            "If InsightFace is not installed, set MOCK_FACE_EMBEDDING=true in .env"
        )
        raise

    # ── Redis connectivity check ──────────────────────────────────────────
    try:
        from app.redis_client import get_redis
        redis = await get_redis()
        await redis.ping()
        logger.info("Redis connection verified.")
    except Exception as exc:
        logger.error(f"Redis connectivity check failed at startup: {exc}")
        raise

    logger.info("E-Voting backend startup complete. All Phase 2 services ready.")
    yield

    # ── Shutdown ──────────────────────────────────────────────────────────
    logger.info("Shutting down E-Voting backend ...")
    await engine.dispose()
    logger.info("Database engine disposed.")


app = FastAPI(
    title="E-Voting MVP API",
    description="High-Concurrency Mobile E-Voting Backend",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Only health router registered in Phase 1
# registration, voting, audit routers added in later phases
app.include_router(health.router, prefix="/api/v1/health", tags=["health"])
app.include_router(registration.router, prefix="/api/v1", tags=["registration"])