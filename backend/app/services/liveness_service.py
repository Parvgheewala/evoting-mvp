# backend/app/services/liveness_service.py

from __future__ import annotations

import json
import logging
import random
import secrets
from datetime import datetime, timezone
from typing import Any

from app.config import get_settings
from app.redis_client import get_redis

settings = get_settings()
logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════
# SECURITY CONTRACT — read before modifying this module
#
# 1. The backend NEVER trusts any "passed" field submitted by the client.
#    Challenge pass/fail is computed exclusively from frames_meta signals.
#
# 2. frames_meta is REQUIRED. Any call to verify_liveness_session()
#    without a valid frames_meta list will return passed=False.
#
# 3. The session nonce is consumed (deleted from Redis) ONLY after ALL
#    validation steps pass. Failed attempts leave the nonce intact so
#    the voter can retry within the TTL window.
#
# 4. Nonce comparison uses secrets.compare_digest() to prevent
#    timing-based oracle attacks.
#
# 5. Frame timestamps must be strictly monotonically increasing.
#    Duplicate or reversed timestamps indicate a replay attack.
# ══════════════════════════════════════════════════════════════════════════

# ── Challenge pool ─────────────────────────────────────────────────────────
# Defined server-side so the client cannot pre-cache a fixed sequence.

CHALLENGE_POOL: list[str] = [
    "blink_twice",       # EAR threshold transitions
    "turn_head_left",    # Head pose yaw < -20°
    "turn_head_right",   # Head pose yaw > +20°
    "smile",             # Lip corner distance increase > 15%
    "nod",               # Head pose pitch oscillation ±15°
]

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


# ── Session creation (unchanged) ───────────────────────────────────────────


async def create_liveness_session(session_id: str) -> dict[str, Any]:
    """
    Generate a randomised liveness challenge session and persist it in Redis.

    Steps:
    1. Sample 3 challenges from the pool without replacement.
    2. Generate a 128-bit cryptographically secure nonce (hex, 32 chars).
    3. Store session payload in Redis with 90-second TTL.
    4. Return challenges + nonce to the caller.
    """
    if len(CHALLENGE_POOL) < 3:
        raise RuntimeError("CHALLENGE_POOL must contain at least 3 entries.")

    challenges: list[str] = random.sample(CHALLENGE_POOL, k=3)
    nonce: str = secrets.token_hex(16)  # 128-bit → 32 hex chars

    payload = json.dumps(
        {
            "challenges":  challenges,
            "nonce":       nonce,
            "created_at":  datetime.now(tz=timezone.utc).isoformat(),
            "session_id":  session_id,
        },
        separators=(",", ":"),
    )

    redis = await get_redis()
    key = _build_redis_key(session_id)
    await redis.set(key, payload, ex=settings.liveness_nonce_ttl_seconds)

    instructions = {c: CHALLENGE_INSTRUCTIONS[c] for c in challenges}

    return {
        "challenges":   challenges,
        "nonce":        nonce,
        "instructions": instructions,
    }


# ══════════════════════════════════════════════════════════════════════════
# TRACK B — Frame-level validation helpers
# These functions operate purely on the frames_meta list submitted by the
# client. They reproduce the same detection logic as the mobile validators
# (B2) so the backend can independently verify the claimed challenge results.
# The backend NEVER reads any client-supplied "passed" field.
# ══════════════════════════════════════════════════════════════════════════


# ── Frame schema validation ────────────────────────────────────────────────

REQUIRED_FRAME_KEYS = {"leftEyeOpen", "rightEyeOpen", "yaw", "pitch", "timestamp"}
MIN_FRAMES = 5
MAX_FRAMES = 150


def _validate_frame_schema(frame: Any) -> bool:
    """Return True if the frame dict contains all required keys with numeric values."""
    if not isinstance(frame, dict):
        return False
    for key in REQUIRED_FRAME_KEYS:
        val = frame.get(key)
        if not isinstance(val, (int, float)):
            return False
    return True


def _validate_frame_consistency(frames: list[dict]) -> dict[str, Any]:
    """
    Validate the frame buffer for basic integrity:

    1. Minimum frame count (≥ MIN_FRAMES).
    2. All frames pass schema validation.
    3. Timestamps are strictly monotonically increasing (no replay).
    4. Total capture window is plausible (100ms – 30s).
    5. Frames show non-zero signal variance (not a static image).

    Returns:
        {"valid": bool, "reason": str}
    """
    if not isinstance(frames, list):
        return {"valid": False, "reason": "FRAMES_NOT_A_LIST"}

    if len(frames) < MIN_FRAMES:
        return {
            "valid":  False,
            "reason": f"INSUFFICIENT_FRAMES: got {len(frames)}, need {MIN_FRAMES}",
        }

    if len(frames) > MAX_FRAMES:
        return {
            "valid":  False,
            "reason": f"TOO_MANY_FRAMES: got {len(frames)}, max {MAX_FRAMES}",
        }

    # Schema check
    for i, frame in enumerate(frames):
        if not _validate_frame_schema(frame):
            return {"valid": False, "reason": f"INVALID_FRAME_SCHEMA at index {i}"}

    # Monotonic timestamp check
    timestamps = [f["timestamp"] for f in frames]
    for i in range(1, len(timestamps)):
        if timestamps[i] <= timestamps[i - 1]:
            return {
                "valid":  False,
                "reason": f"NON_MONOTONIC_TIMESTAMP at index {i}",
            }

    # Plausible capture window: between 100ms and 30 seconds
    window_ms = timestamps[-1] - timestamps[0]
    if window_ms < 100:
        return {"valid": False, "reason": "CAPTURE_WINDOW_TOO_SHORT"}
    if window_ms > 30_000:
        return {"valid": False, "reason": "CAPTURE_WINDOW_TOO_LONG"}

    # Variance check — a static image submission produces zero signal variance.
    # We check that at least one signal has non-trivial variance across frames.
    yaw_vals   = [f["yaw"]   for f in frames]
    pitch_vals = [f["pitch"] for f in frames]
    ear_vals   = [(f["leftEyeOpen"] + f["rightEyeOpen"]) / 2 for f in frames]

    yaw_range   = max(yaw_vals)   - min(yaw_vals)
    pitch_range = max(pitch_vals) - min(pitch_vals)
    ear_range   = max(ear_vals)   - min(ear_vals)

    if yaw_range < 0.5 and pitch_range < 0.5 and ear_range < 0.02:
        return {"valid": False, "reason": "STATIC_IMAGE_DETECTED: no signal variance"}

    return {"valid": True, "reason": "OK"}


# ── Per-challenge signal validators ───────────────────────────────────────
# Each function mirrors the mobile validator (B2) exactly.
# Inputs are raw frame dicts from frames_meta — no client trust.


def _detect_blinks(frames: list[dict]) -> int:
    """
    Count blink events in the frame sequence.
    A blink = EAR transitions open (>0.5) → closed (<0.3) → open (>0.5).
    """
    blink_count = 0
    eye_was_closed = False

    for f in frames:
        avg_ear = (f["leftEyeOpen"] + f["rightEyeOpen"]) / 2
        if not eye_was_closed and avg_ear < 0.3:
            eye_was_closed = True
        elif eye_was_closed and avg_ear > 0.5:
            blink_count += 1
            eye_was_closed = False

    return blink_count


def _detect_head_turn(frames: list[dict], direction: str) -> bool:
    """
    Return True if yaw exceeds ±20° in the required direction.
    direction: "left" → yaw < -20, "right" → yaw > +20
    """
    if direction == "left":
        return any(f["yaw"] < -20 for f in frames)
    return any(f["yaw"] > 20 for f in frames)


def _detect_nod(frames: list[dict]) -> bool:
    """
    Return True if pitch oscillates by at least 30° total (±15° swing).
    """
    if len(frames) < 4:
        return False
    pitches = [f["pitch"] for f in frames]
    return (max(pitches) - min(pitches)) >= 30


def _detect_smile(frames: list[dict]) -> bool:
    """
    Return True if any frame carries a smileScore > 0.7.
    smileScore is an optional field added by the mobile client.
    Falls back to True in MVP if the field is absent but challenge
    was included — production would require the field to be present.
    """
    scores = [f.get("smileScore") for f in frames if "smileScore" in f]
    if not scores:
        # smileScore not present — accept in MVP, reject in production
        logger.warning(
            "smile challenge: smileScore field absent in frames. "
            "Accepting in MVP mode."
        )
        return True
    return any(s > 0.7 for s in scores)


def _validate_challenge_from_frames(
    challenge: str,
    frames: list[dict],
) -> dict[str, Any]:
    """
    Compute whether a specific challenge was completed by inspecting
    raw frame signal values. Never reads a client-supplied "passed" field.

    Returns:
        {"passed": bool, "reason": str}
    """
    if challenge == "blink_twice":
        blinks = _detect_blinks(frames)
        passed = blinks >= 2
        return {
            "passed": passed,
            "reason": "OK" if passed else f"BLINK_COUNT_INSUFFICIENT: got {blinks}",
        }

    if challenge == "turn_head_left":
        passed = _detect_head_turn(frames, "left")
        return {
            "passed": passed,
            "reason": "OK" if passed else "YAW_THRESHOLD_NOT_MET: need yaw < -20°",
        }

    if challenge == "turn_head_right":
        passed = _detect_head_turn(frames, "right")
        return {
            "passed": passed,
            "reason": "OK" if passed else "YAW_THRESHOLD_NOT_MET: need yaw > +20°",
        }

    if challenge == "smile":
        passed = _detect_smile(frames)
        return {
            "passed": passed,
            "reason": "OK" if passed else "SMILE_SCORE_INSUFFICIENT",
        }

    if challenge == "nod":
        passed = _detect_nod(frames)
        return {
            "passed": passed,
            "reason": "OK" if passed else "PITCH_OSCILLATION_INSUFFICIENT: need ±15°",
        }

    # Unknown challenge — fail safe
    return {"passed": False, "reason": f"UNKNOWN_CHALLENGE: {challenge}"}


# ── Session verification ───────────────────────────────────────────────────


async def verify_liveness_session(
    session_id: str,
    nonce: str,
    challenge_results: list[dict[str, Any]],
    frames_meta: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Validate a completed liveness challenge session.

    Security model:
    ──────────────
    • The backend IGNORES any "passed" field submitted by the client.
    • Challenge pass/fail is computed ONLY from frames_meta signal values.
    • If frames_meta is absent the session is rejected (FRAMES_REQUIRED).

    Validation steps:
    1.  Fetch session payload from Redis — absent = expired/invalid.
    2.  Validate nonce with constant-time comparison.
    3.  Validate frame buffer consistency (count, schema, monotonic ts,
        variance — rejects static image submissions).
    4.  For each expected challenge, compute result from frame signals.
        Client-supplied "passed" values are completely ignored.
    5.  On full pass, DELETE the Redis key (single-use nonce consumption).

    Args:
        session_id:        UUID string from the initiate response.
        nonce:             Hex nonce string from the initiate response.
        challenge_results: Submitted by client — used ONLY to extract
                           challenge names. "passed" values are discarded.
        frames_meta:       List of FrameData dicts from the mobile client.

    Returns:
        On success:  {"passed": True, "failed_challenge": None, "reason": "OK"}
        On failure:  {"passed": False, "reason": str, "failed_challenge": str|None}
    """
    redis = await get_redis()
    key   = _build_redis_key(session_id)

    # ── 1. Fetch stored session ────────────────────────────────────────────
    raw: str | None = await redis.get(key)
    if raw is None:
        return {
            "passed":           False,
            "reason":           "SESSION_EXPIRED_OR_INVALID",
            "failed_challenge": None,
        }

    try:
        session_data: dict[str, Any] = json.loads(raw)
    except json.JSONDecodeError:
        await redis.delete(key)
        return {
            "passed":           False,
            "reason":           "SESSION_CORRUPTED",
            "failed_challenge": None,
        }

    # ── 2. Nonce validation ────────────────────────────────────────────────
    stored_nonce: str = session_data.get("nonce", "")
    if not secrets.compare_digest(stored_nonce, nonce):
        return {
            "passed":           False,
            "reason":           "NONCE_MISMATCH",
            "failed_challenge": None,
        }

    # ── 3. Frame buffer validation ────────────────────────────────────────
    if not frames_meta:
        return {
            "passed":           False,
            "reason":           "FRAMES_REQUIRED: frames_meta must be provided",
            "failed_challenge": None,
        }

    consistency = _validate_frame_consistency(frames_meta)
    if not consistency["valid"]:
        logger.warning(
            f"[liveness] Frame consistency failed for session {session_id}: "
            f"{consistency['reason']}"
        )
        return {
            "passed":           False,
            "reason":           consistency["reason"],
            "failed_challenge": None,
        }

    # ── 4. Challenge verification from frame signals ───────────────────────
    # Use the SERVER-ISSUED challenge list, not what the client claims.
    expected_challenges: list[str] = session_data.get("challenges", [])

    for challenge in expected_challenges:
        result = _validate_challenge_from_frames(challenge, frames_meta)

        if not result["passed"]:
            logger.info(
                f"[liveness] Challenge '{challenge}' FAILED for session "
                f"{session_id}: {result['reason']}"
            )
            return {
                "passed":           False,
                "reason":           result["reason"],
                "failed_challenge": challenge,
            }

        logger.debug(
            f"[liveness] Challenge '{challenge}' PASSED for session {session_id}"
        )

    # ── 5. Consume the nonce (single-use replay prevention) ───────────────
    # DELETE only after ALL checks pass.
    await redis.delete(key)

    logger.info(
        f"[liveness] Session {session_id} PASSED all "
        f"{len(expected_challenges)} challenges."
    )
    return {"passed": True, "failed_challenge": None, "reason": "OK"}


# ── Utility: fetch session metadata without consuming ─────────────────────


async def get_liveness_session_meta(session_id: str) -> dict[str, Any] | None:
    """
    Read session data without consuming the nonce.
    Used for debugging and admin inspection only.
    Returns None if the session does not exist or has expired.
    """
    redis = await get_redis()
    key   = _build_redis_key(session_id)
    raw   = await redis.get(key)
    if raw is None:
        return None
    try:
        data = json.loads(raw)
        ttl  = await redis.ttl(key)
        data["ttl_remaining_seconds"] = ttl
        return data
    except json.JSONDecodeError:
        return None