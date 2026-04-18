# backend/app/routers/registration.py

from __future__ import annotations
import json
from fastapi import Form, File, UploadFile
from typing import List, Optional
import uuid
from datetime import datetime, timedelta, timezone
from app.services.liveness_service import create_liveness_session
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.voter import (
    RegistrationInitiateRequest,
    RegistrationInitiateResponse,
    RegistrationDuplicateError,
    LivenessSubmitResponse,
    LivenessFailResponse,
    VerifyIdentityResponse,       # add this
    IdentityMismatchError, 
)
from app.services.liveness_service import create_liveness_session
from app.services.registration_service import check_duplicate, create_pending_voter
from app.config import get_settings

settings = get_settings()
router = APIRouter()


# ── POST /api/v1/registration/initiate ────────────────────────────────────


@router.post(
    "/registration/initiate",
    status_code=status.HTTP_201_CREATED,
    response_model=RegistrationInitiateResponse,
    responses={
        409: {
            "model": RegistrationDuplicateError,
            "description": "Voter ID or Aadhaar ID already registered",
        }
    },
    summary="Initiate voter registration",
    description=(
        "Validates Aadhaar ID and Voter ID for duplicates, creates a "
        "pending voter record, and returns a randomised liveness challenge "
        "session with a 90-second nonce."
    ),
)
async def initiate_registration(
    body: RegistrationInitiateRequest,
    db: AsyncSession = Depends(get_db),
) -> RegistrationInitiateResponse:
    """
    Registration Initiation Flow
    ────────────────────────────
    1. Validate request fields (handled by Pydantic schema).
    2. Check for duplicate aadhaar_id OR voter_id in the voters table.
    3. Create a pending Voter row so the slot is reserved atomically.
    4. Generate a liveness session: 3 random challenges + 90-second nonce
       stored in Redis under liveness:{session_id}:nonce.
    5. Return registration_id, liveness_session_id, challenges, nonce,
       and nonce expiry timestamp to the client.
    """

    # ── Step 1: Duplicate prevention ──────────────────────────────────────
    is_duplicate = await check_duplicate(
        aadhaar_id=body.aadhaar_id,
        voter_id=body.voter_id,
        db=db,
    )
    if is_duplicate:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "DUPLICATE_REGISTRATION",
                "message": "Voter ID or Aadhaar ID already registered.",
            },
        )

    # ── Step 2: Reserve a pending voter slot ──────────────────────────────
    registration_id = uuid.uuid4()
    voter = await create_pending_voter(
        registration_id=registration_id,
        aadhaar_id=body.aadhaar_id,
        voter_id=body.voter_id,
        full_name=body.full_name,
        db=db,
    )

    # ── Step 3: Create liveness session in Redis ──────────────────────────
    liveness_session_id = uuid.uuid4()
    liveness_data = await create_liveness_session(
        session_id=str(liveness_session_id)
    )

    # ── Step 4: Build response ────────────────────────────────────────────
    nonce_expires_at = datetime.now(tz=timezone.utc) + timedelta(
        seconds=settings.liveness_nonce_ttl_seconds
    )

    return RegistrationInitiateResponse(
        registration_id=registration_id,
        liveness_session_id=liveness_session_id,
        challenges=liveness_data["challenges"],
        nonce=liveness_data["nonce"],
        nonce_expires_at=nonce_expires_at,
    )

# ── POST /api/v1/registration/liveness ────────────────────────────────────

@router.post(
    "/registration/liveness",
    status_code=status.HTTP_200_OK,
    response_model=LivenessSubmitResponse,
    responses={
        422: {
            "model": LivenessFailResponse,
            "description": "One or more liveness challenges failed",
        }
    },
    summary="Submit liveness challenge results",
)
async def submit_liveness(
    session_id: uuid.UUID = Form(...),
    nonce: str = Form(...),
    challenge_results: str = Form(
        ...,
        description="JSON array of ChallengeResult objects"
    ),
    face_frames: Optional[List[UploadFile]] = File(default=None),
) -> LivenessSubmitResponse:
    """
    Accepts multipart/form-data with:
    - session_id: UUID from initiate response
    - nonce: hex string from initiate response
    - challenge_results: JSON-encoded array of challenge completion events
    - face_frames: one image file per challenge (optional at this stage)

    Delegates verification to liveness_service which reads/deletes the
    Redis nonce and validates challenge completion order.
    """
    from app.services.liveness_service import verify_liveness_session

    # Parse challenge_results JSON string from form field
    try:
        parsed_results = json.loads(challenge_results)
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "INVALID_CHALLENGE_RESULTS",
                "message": "challenge_results must be a valid JSON array.",
            },
        )

    result = await verify_liveness_session(
        session_id=str(session_id),
        nonce=nonce,
        challenge_results=parsed_results,
    )

    if not result["passed"]:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "liveness_passed": False,
                "failed_challenge": result.get("failed_challenge"),
                "reason": result.get("reason", "CHALLENGE_FAILED"),
            },
        )

    return LivenessSubmitResponse(
        liveness_passed=True,
        session_id=session_id,
    )


# ── POST /api/v1/registration/verify-identity ─────────────────────────────
# Placeholder route so the router is complete and importable.
# Full implementation arrives in Step 5.

# ── POST /api/v1/registration/verify-identity ─────────────────────────────

@router.post(
    "/registration/verify-identity",
    status_code=status.HTTP_200_OK,
    response_model=VerifyIdentityResponse,
    responses={
        403: {
            "model": IdentityMismatchError,
            "description": "Face does not match citizen registry record",
        },
        404: {"description": "Voter registration session not found"},
        409: {"description": "Voter already active"},
    },
    summary="Submit live image for identity verification and complete registration",
)
async def verify_identity(
    session_id: uuid.UUID = Form(...),
    aadhaar_id: str = Form(...),
    voter_id: str = Form(...),
    live_image: UploadFile = File(
        ...,
        description="Live face image — JPEG or PNG, max 2 MB",
    ),
    db: AsyncSession = Depends(get_db),
) -> VerifyIdentityResponse:
    """
    Identity Verification + Registration Completion Flow
    ────────────────────────────────────────────────────
    1. Validate file size (≤ 2 MB) and content type.
    2. Load the pending voter row — must exist and be status=pending.
    3. Guard against double-activation (idempotency).
    4. Read live image bytes.
    5. Delegate to identity_service.validate_identity:
       - citizen registry lookup
       - voter_id cross-check
       - cosine similarity (stored embedding vs live embedding)
       - threshold check > 0.85
    6. On failure → update voter status to identity_failed, return 403.
    7. On success:
       a. Generate UTI (SHA-256 of voter_id+aadhaar_id+election_id+salt)
       b. Store UTI in Redis: voter:{voter_id}:ticket  EX 86400
       c. Update voter row:
          - registration_status = active
          - uti_hash = uti
          - face_embedding_ref = citizen_ref_id
          - verified_at = now()
       d. Return UTI and voter_ref_id to client.
    """
    from app.services.identity_service import (
        validate_identity,
        generate_and_store_uti,
    )
    from datetime import datetime, timezone

    # ── 1. File validation ────────────────────────────────────────────────
    MAX_IMAGE_BYTES = 2 * 1024 * 1024  # 2 MB

    if live_image.content_type not in ("image/jpeg", "image/png", "image/jpg"):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail={
                "error": "UNSUPPORTED_IMAGE_TYPE",
                "message": "live_image must be JPEG or PNG.",
            },
        )

    image_bytes = await live_image.read()

    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={
                "error": "IMAGE_TOO_LARGE",
                "message": "live_image must be ≤ 2 MB.",
            },
        )

    if len(image_bytes) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "EMPTY_IMAGE",
                "message": "live_image file is empty.",
            },
        )

    # ── 2. Load pending voter row ─────────────────────────────────────────
    from sqlalchemy import select as sa_select
    from app.models.voter import Voter

    result = await db.execute(
        sa_select(Voter).where(
            Voter.aadhaar_id == aadhaar_id,
            Voter.voter_id == voter_id.upper(),
        )
    )
    voter = result.scalar_one_or_none()

    if voter is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "VOTER_NOT_FOUND",
                "message": "No registration session found for these credentials. "
                           "Please call /initiate first.",
            },
        )

    # ── 3. Idempotency guard ──────────────────────────────────────────────
    if voter.registration_status == "active":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "ALREADY_ACTIVE",
                "message": "This voter is already registered and active.",
            },
        )

    if voter.registration_status == "suspended":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "ACCOUNT_SUSPENDED",
                "message": "This voter account has been suspended.",
            },
        )

    # ── 4. Identity validation ────────────────────────────────────────────
    identity_result = await validate_identity(
        aadhaar_id=aadhaar_id,
        voter_id=voter_id,
        live_image_bytes=image_bytes,
        db=db,
    )

    # ── 5. Handle failure ─────────────────────────────────────────────────
    if not identity_result["passed"]:
        # Persist failure status so audit trail is complete
        voter.registration_status = "identity_failed"
        await db.flush()

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "IDENTITY_MISMATCH",
                "similarity_score": identity_result["score"],
                "reason": identity_result["reason"],
                "message": "Face does not match citizen registry record.",
            },
        )

    # ── 6. Generate UTI and store in Redis ────────────────────────────────
    uti_hash, _ = await generate_and_store_uti(
        voter_id=voter_id,
        aadhaar_id=aadhaar_id,
    )

    # ── 7. Activate voter in PostgreSQL ───────────────────────────────────
    voter.registration_status = "active"
    voter.uti_hash = uti_hash
    voter.face_embedding_ref = identity_result["citizen_ref_id"]
    voter.verified_at = datetime.now(tz=timezone.utc)
    await db.flush()

    return VerifyIdentityResponse(
        registration_status="active",
        uti=uti_hash,
        voter_ref_id=voter.id,
        message="Registration complete. Keep your UTI secure.",
    )