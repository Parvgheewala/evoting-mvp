# backend/app/services/liveness_service.py

from __future__ import annotations

import json
import random
import secrets
from datetime import datetime, timezone
from typing import Any

from app.config import get_settings
from app.redis_client import get_redis

settings = get_settings()

# ── Challenge pool ─────────────────────────────────────────────────────────
# Each entry maps to a client-side detection method documented in the
# design doc (Section 3.3.3). The pool is kept server-side so the client
# cannot pre-cache a fixed sequence for replay.

CHALLENGE_POOL: list[str] = [
    "blink_twice",       # EAR threshold transitions
    "turn_head_left",    # Head pose yaw < -20°
    "turn_head_right",   # Head pose yaw > +20°
    "smile",             # Lip corner distance increase > 15%
    "nod",               # Head pose pitch oscillation ±15°
]

# Human-readable instructions returned to the mobile client
CHALLENGE_INSTRUCTIONS: dict[str, str] = {
    "blink_twice":     "Blink twice slowly",
    "turn_head_left":  "Turn your head to the LEFT",
    "turn_head_right": "Turn your head to the RIGHT",
    "smile":           "Smile naturally",
    "nod":             "Nod your head up and down",
}

_REDIS_KEY_PREFIX = "liveness"


def _build_redis_key(session_id: str) -> str:
    return f"{_REDIS_KEY_PREFIX}:{session_id}:nonce"


# ── Session creation ───────────────────────────────────────────────────────


async def create_liveness_session(session_id: str) -> dict[str, Any]:
    """
    Generate a randomised liveness challenge session and persist it in Redis.

    Steps:
    1. Sample 3 challenges from the pool without replacement.
       Randomised order means an attacker cannot pre-record a fixed sequence.
    2. Generate a 128-bit cryptographically secure nonce (hex, 32 chars).
    3. Store the session payload in Redis with a 90-second TTL.
       Key: liveness:{session_id}:nonce
    4. Return challenges + nonce to the caller (router → client).

    The nonce is consumed (deleted) on first successful verify call,
    preventing replay of a previously recorded challenge video.

    Returns:
        {
            "challenges": ["blink_twice", "turn_head_left", "smile"],
            "nonce": "a3f1c2...",                  # 32-char hex
            "instructions": { challenge: instruction, ... }
        }
    """
    if len(CHALLENGE_POOL) < 3:
        raise RuntimeError("CHALLENGE_POOL must contain at least 3 entries.")

    challenges: list[str] = random.sample(CHALLENGE_POOL, k=3)
    nonce: str = secrets.token_hex(16)  # 128-bit → 32 hex chars

    payload = json.dumps(
        {
            "challenges": challenges,
            "nonce": nonce,
            "created_at": datetime.now(tz=timezone.utc).isoformat(),
            "session_id": session_id,
        },
        separators=(",", ":"),  # compact — saves Redis memory
    )
    redis = await get_redis()
    key = _build_redis_key(session_id)
    await redis.set(key, payload, ex=settings.liveness_nonce_ttl_seconds)

    instructions = {c: CHALLENGE_INSTRUCTIONS[c] for c in challenges}

    return {
        "challenges": challenges,
        "nonce": nonce,
        "instructions": instructions,
    }


# ── Session verification ───────────────────────────────────────────────────


async def verify_liveness_session(
    session_id: str,
    nonce: str,
    challenge_results: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Validate a completed liveness challenge session.

    Steps:
    1. Fetch session payload from Redis.
       If absent → session expired or never existed.
    2. Validate nonce matches the stored value.
       Nonce mismatch → replay or tampering attempt.
    3. For each expected challenge (in the issued order), confirm that
       a matching result exists in challenge_results with passed=True.
    4. On success, DELETE the Redis key to prevent replay.
       This is the single-use nonce consumption.

    Args:
        session_id:        UUID string from the initiate response.
        nonce:             Hex nonce string from the initiate response.
        challenge_results: List of dicts, each with at minimum:
                           {"challenge": str, "passed": bool}

    Returns:
        On success:  {"passed": True}
        On failure:  {"passed": False, "reason": str, "failed_challenge": str|None}
    """
    redis = await get_redis()
    key = _build_redis_key(session_id)

    # ── 1. Fetch stored session ────────────────────────────────────────────
    raw: str | None = await redis.get(key)
    if raw is None:
        return {
            "passed": False,
            "reason": "SESSION_EXPIRED_OR_INVALID",
            "failed_challenge": None,
        }

    try:
        session_data: dict[str, Any] = json.loads(raw)
    except json.JSONDecodeError:
        # Corrupted Redis value — treat as invalid
        await redis.delete(key)
        return {
            "passed": False,
            "reason": "SESSION_CORRUPTED",
            "failed_challenge": None,
        }

    # ── 2. Nonce validation ────────────────────────────────────────────────
    stored_nonce: str = session_data.get("nonce", "")
    if not secrets.compare_digest(stored_nonce, nonce):
        # Use compare_digest to prevent timing-based nonce oracle attacks
        return {
            "passed": False,
            "reason": "NONCE_MISMATCH",
            "failed_challenge": None,
        }

    # ── 3. Challenge validation ────────────────────────────────────────────
    expected_challenges: list[str] = session_data.get("challenges", [])

    # Build a lookup of submitted results keyed by challenge name
    # If duplicate challenge names appear, last one wins — safe because
    # the expected list has no duplicates (sampled without replacement).
    results_map: dict[str, bool] = {
        r["challenge"]: bool(r.get("passed", False))
        for r in challenge_results
        if isinstance(r, dict) and "challenge" in r
    }

    for challenge in expected_challenges:
        if not results_map.get(challenge, False):
            # Challenge was not completed or not submitted at all
            return {
                "passed": False,
                "reason": "CHALLENGE_NOT_COMPLETED",
                "failed_challenge": challenge,
            }

    # ── 4. Consume the nonce — single-use replay prevention ───────────────
    # DELETE is issued only after all checks pass.
    # If checks fail we intentionally leave the key so the voter can retry
    # within the TTL window (the design doc does not mandate single-attempt).
    await redis.delete(key)

    return {"passed": True, "failed_challenge": None, "reason": "OK"}


# ── Utility: fetch session metadata without consuming ─────────────────────


async def get_liveness_session_meta(session_id: str) -> dict[str, Any] | None:
    """
    Read session data without consuming the nonce.
    Used for debugging and admin inspection only — NOT called during
    normal voter flow.

    Returns None if the session does not exist or has expired.
    """
    redis = await get_redis()
    key = _build_redis_key(session_id)
    raw = await redis.get(key)
    if raw is None:
        return None
    try:
        data = json.loads(raw)
        ttl = await redis.ttl(key)
        data["ttl_remaining_seconds"] = ttl
        return data
    except json.JSONDecodeError:
        return None