# backend/app/services/identity_service.py

from __future__ import annotations

import asyncio
import hashlib
import secrets
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.citizen_registry import CitizenRegistry
from app.models.voter import Voter
from app.redis_client import get_redis

settings = get_settings()

# ── Thread pool for CPU-bound embedding extraction ─────────────────────────
# Face embedding inference is synchronous and CPU/GPU bound.
# We offload it to a thread pool so it never blocks the async event loop.
# max_workers=2 respects the 60% resource budget from the design doc.
_executor = ThreadPoolExecutor(max_workers=2)

# ── InsightFace model singleton ────────────────────────────────────────────
# Loaded once on first use. None until initialised.
_face_model = None

# ── Mock mode ─────────────────────────────────────────────────────────────
# Set MOCK_FACE_EMBEDDING=true in your .env to skip InsightFace entirely.
# Mock mode returns a deterministic synthetic embedding so the full
# registration pipeline can be tested without a GPU or model download.
from app.config import get_settings

settings = get_settings()
MOCK_FACE_EMBEDDING: bool = settings.mock_face_embedding


# ── Model loader ──────────────────────────────────────────────────────────


def _load_face_model():
    """
    Load InsightFace model synchronously.
    Called inside the thread pool — never on the event loop.
    ctx_id=0  → GPU if available
    ctx_id=-1 → CPU fallback
    """
    global _face_model
    if _face_model is not None:
        return _face_model
    try:
        import insightface
        model = insightface.app.FaceAnalysis(
            name="buffalo_l",
            providers=["CUDAExecutionProvider", "CPUExecutionProvider"],
        )
        model.prepare(ctx_id=0, det_size=(640, 640))
        _face_model = model
        return _face_model
    except Exception as exc:
        raise RuntimeError(
            f"Failed to load InsightFace model: {exc}. "
            "Set MOCK_FACE_EMBEDDING=true in .env to bypass for development."
        ) from exc


# ── Cosine similarity ─────────────────────────────────────────────────────


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """
    Compute cosine similarity between two 512-d float32 vectors.

    Similarity(A, B) = (A · B) / (||A|| × ||B||)

    Returns 0.0 if either vector is a zero vector (degenerate case).
    Result is in range [-1.0, 1.0]; threshold check uses > 0.85.
    """
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


# ── Mock embedding extraction ─────────────────────────────────────────────


def _mock_embedding(seed: int = 42) -> np.ndarray:
    """
    Return a deterministic unit-normalised 512-d float32 vector.
    Used in MOCK_FACE_EMBEDDING=true mode.

    The same seed always produces the same vector, so a seeded citizen
    registry record will always match a seeded live submission — giving
    a predictable similarity of 1.0 for testing.
    """
    rng = np.random.default_rng(seed)
    vec = rng.random(512).astype(np.float32)
    return vec / np.linalg.norm(vec)


# ── Synchronous embedding extraction (runs in thread pool) ────────────────


def _extract_embedding_sync(image_bytes: bytes) -> np.ndarray:
    """
    Extract a 512-d face embedding from raw image bytes.
    Synchronous — must be called via run_in_executor, never directly
    from an async context.

    Returns:
        512-d float32 numpy array (the first detected face).

    Raises:
        ValueError: if no face is detected in the image.
        RuntimeError: if the model fails to load.
    """
    if MOCK_FACE_EMBEDDING:
        # Deterministic mock: hash the image bytes to pick a seed
        # so different images produce different (but stable) embeddings.
        return _mock_embedding(seed=42)

    import cv2
    model = _load_face_model()
    img_array = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Could not decode image — ensure JPEG or PNG format.")
    faces = model.get(img)
    if not faces:
        raise ValueError("NO_FACE_DETECTED")
    # Use the highest-confidence face (first result from InsightFace)
    return faces[0].embedding.astype(np.float32)


# ── Async wrapper ─────────────────────────────────────────────────────────


async def extract_embedding_async(image_bytes: bytes) -> np.ndarray:
    """
    Async wrapper around _extract_embedding_sync.
    Offloads CPU-bound inference to the thread pool so the event loop
    remains unblocked during face embedding extraction.
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        _executor,
        _extract_embedding_sync,
        image_bytes,
    )


# ── Duplicate check ───────────────────────────────────────────────────────


async def check_duplicate(
    aadhaar_id: str,
    voter_id: str,
    db: AsyncSession,
) -> bool:
    """
    Return True if aadhaar_id OR voter_id already exists in the voters table.
    Identical to registration_service.check_duplicate — kept here as well
    so identity_service is self-contained for the verify-identity endpoint.
    """
    from sqlalchemy import or_
    result = await db.execute(
        select(Voter.id).where(
            or_(
                Voter.aadhaar_id == aadhaar_id,
                Voter.voter_id == voter_id,
            )
        ).limit(1)
    )
    return result.scalar_one_or_none() is not None


# ── Citizen registry lookup ───────────────────────────────────────────────


async def fetch_citizen_record(
    aadhaar_id: str,
    db: AsyncSession,
) -> CitizenRegistry | None:
    """
    Fetch the citizen registry row for the given Aadhaar ID.
    Returns None if not found or if the record is inactive.
    """
    result = await db.execute(
        select(CitizenRegistry).where(
            CitizenRegistry.aadhaar_id == aadhaar_id,
            CitizenRegistry.is_active.is_(True),
        )
    )
    return result.scalar_one_or_none()


# ── Core identity validation ──────────────────────────────────────────────


async def validate_identity(
    aadhaar_id: str,
    voter_id: str,
    live_image_bytes: bytes,
    db: AsyncSession,
) -> dict[str, Any]:
    """
    Full identity validation pipeline per design doc Section 3.4.2.

    Steps:
    1. Fetch citizen registry record by Aadhaar ID.
       Fail fast if not found or inactive.
    2. Verify the voter_id on the registry record matches the submitted one.
       Prevents using one person's face against another's Aadhaar.
    3. Deserialise the stored 512-d float32 embedding from BYTEA.
    4. Extract a live 512-d embedding from the submitted image.
       Offloaded to thread pool — non-blocking.
    5. Compute cosine similarity.
    6. Apply threshold: similarity > 0.85 → PASS, else FAIL.

    Returns:
        {
            "passed": bool,
            "score": float,          # cosine similarity rounded to 4dp
            "reason": str,           # "OK" | error code
            "citizen_ref_id": UUID   # for storing face_embedding_ref
        }
    """
    # ── 1. Registry lookup ────────────────────────────────────────────────
    citizen = await fetch_citizen_record(aadhaar_id=aadhaar_id, db=db)
    if citizen is None:
        return {
            "passed": False,
            "score": 0.0,
            "reason": "CITIZEN_NOT_FOUND",
            "citizen_ref_id": None,
        }

    # ── 2. Cross-check voter_id ───────────────────────────────────────────
    if citizen.voter_id.upper() != voter_id.upper():
        return {
            "passed": False,
            "score": 0.0,
            "reason": "VOTER_ID_MISMATCH",
            "citizen_ref_id": None,
        }

    # ── 3. Deserialise stored embedding ───────────────────────────────────
    try:
        stored_embedding = np.frombuffer(
            citizen.face_embedding, dtype=np.float32
        ).copy()  # .copy() makes it writable — required by numpy ops
    except Exception:
        return {
            "passed": False,
            "score": 0.0,
            "reason": "EMBEDDING_DESERIALISATION_ERROR",
            "citizen_ref_id": None,
        }

    if stored_embedding.shape != (512,):
        return {
            "passed": False,
            "score": 0.0,
            "reason": "EMBEDDING_SHAPE_INVALID",
            "citizen_ref_id": None,
        }

    # ── 4. Extract live embedding (thread pool) ───────────────────────────
    try:
        live_embedding = await extract_embedding_async(live_image_bytes)
    except ValueError as exc:
        reason = str(exc) if str(exc) in (
            "NO_FACE_DETECTED", "Could not decode image — ensure JPEG or PNG format."
        ) else "EMBEDDING_EXTRACTION_FAILED"
        return {
            "passed": False,
            "score": 0.0,
            "reason": reason,
            "citizen_ref_id": None,
        }

    # ── 5. Cosine similarity ──────────────────────────────────────────────
    score = cosine_similarity(stored_embedding, live_embedding)

    # ── 6. Threshold check ────────────────────────────────────────────────
    passed = score > settings.face_similarity_threshold

    return {
        "passed": passed,
        "score": round(score, 4),
        "reason": "OK" if passed else "BELOW_THRESHOLD",
        "citizen_ref_id": citizen.id,
    }


# ── UTI generation and Redis storage ─────────────────────────────────────


async def generate_and_store_uti(
    voter_id: str,
    aadhaar_id: str,
    election_id: str = "mvp-election-2024",
) -> tuple[str, str]:
    """
    Generate a Unique Ticket Identifier (UTI) per design doc Section 3.2.1.

    Algorithm:
        salt      = 256-bit random hex string
        raw       = voter_id + aadhaar_id + election_id + salt
        uti_hash  = SHA-256(raw)

    Stores:  voter:{voter_id}:ticket → uti_hash  EX 86400s
    Returns: (uti_hash, raw_uti) as a tuple
             uti_hash → stored in PostgreSQL voters.uti_hash
             uti_hash → returned to the voter as their ballot credential
    """
    salt = secrets.token_hex(32)  # 256-bit salt
    raw = f"{voter_id}{aadhaar_id}{election_id}{salt}"
    uti_hash = hashlib.sha256(raw.encode()).hexdigest()

    redis = await get_redis()
    key = f"voter:{voter_id}:ticket"
    await redis.set(key, uti_hash, ex=settings.uti_ttl_seconds)

    return uti_hash, uti_hash  # both the stored value and what's returned to voter