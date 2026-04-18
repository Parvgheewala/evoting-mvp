# backend/app/schemas/voter.py

from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


# ── Registration Initiation ────────────────────────────────────────────────


class RegistrationInitiateRequest(BaseModel):
    """POST /api/v1/registration/initiate — request body."""

    aadhaar_id: str = Field(
        ...,
        min_length=12,
        max_length=12,
        pattern=r"^\d{12}$",
        description="12-digit Aadhaar number",
        examples=["123456789012"],
    )
    voter_id: str = Field(
        ...,
        min_length=6,
        max_length=20,
        pattern=r"^[A-Z]{2,3}\d{6,10}$",
        description="Voter ID (EPIC card number)",
        examples=["ABC1234567"],
    )
    full_name: str = Field(
        ...,
        min_length=2,
        max_length=255,
        description="Voter's full name as on government ID",
        examples=["Ravi Kumar"],
    )

    @field_validator("aadhaar_id")
    @classmethod
    def aadhaar_must_be_digits(cls, v: str) -> str:
        if not v.isdigit():
            raise ValueError("aadhaar_id must contain only digits")
        return v

    @field_validator("voter_id")
    @classmethod
    def voter_id_uppercase(cls, v: str) -> str:
        return v.upper()


class RegistrationInitiateResponse(BaseModel):
    """POST /api/v1/registration/initiate — 201 response."""

    registration_id: uuid.UUID = Field(
        description="Unique ID for this registration session"
    )
    liveness_session_id: uuid.UUID = Field(
        description="Session ID for liveness challenge flow"
    )
    challenges: List[str] = Field(
        description="Ordered list of 3 randomised liveness challenge names"
    )
    nonce: str = Field(
        description="Base64-encoded 128-bit session nonce (hex string)"
    )
    nonce_expires_at: datetime = Field(
        description="ISO 8601 timestamp when the nonce expires (90 seconds)"
    )


class RegistrationDuplicateError(BaseModel):
    """POST /api/v1/registration/initiate — 409 conflict response."""

    error: Literal["DUPLICATE_REGISTRATION"] = "DUPLICATE_REGISTRATION"
    message: str = "Voter ID or Aadhaar ID already registered."


# ── Liveness Submission ────────────────────────────────────────────────────


class ChallengeResult(BaseModel):
    """Single challenge completion event inside a liveness submission."""

    challenge: str = Field(
        description="Challenge name, e.g. 'blink_twice'",
        examples=["blink_twice"],
    )
    passed: bool = Field(description="Whether the challenge was completed")
    timestamp_ms: Optional[int] = Field(
        default=None,
        description="Client-side epoch ms when the challenge completed",
    )


class LivenessSubmitRequest(BaseModel):
    """
    POST /api/v1/registration/liveness
    Sent as multipart/form-data; this schema covers the JSON fields.
    face_frames files are handled separately via UploadFile.
    """

    session_id: uuid.UUID
    nonce: str = Field(description="Nonce received from initiate response")
    challenge_results: List[ChallengeResult]


class LivenessSubmitResponse(BaseModel):
    """POST /api/v1/registration/liveness — 200 response."""

    liveness_passed: bool
    session_id: uuid.UUID


class LivenessFailResponse(BaseModel):
    """POST /api/v1/registration/liveness — 422 response."""

    liveness_passed: Literal[False] = False
    failed_challenge: Optional[str] = None
    reason: str


# ── Identity Verification + Registration Completion ────────────────────────


class VerifyIdentityResponse(BaseModel):
    """POST /api/v1/registration/verify-identity — 200 response."""

    registration_status: Literal["active"] = "active"
    uti: str = Field(
        description="64-char hex SHA-256 UTI — keep this secure",
        min_length=64,
        max_length=64,
    )
    voter_ref_id: uuid.UUID = Field(
        description="UUID of the newly created Voter record"
    )
    message: str = "Registration complete. Keep your UTI secure."


class IdentityMismatchError(BaseModel):
    """POST /api/v1/registration/verify-identity — 403 response."""

    error: Literal["IDENTITY_MISMATCH"] = "IDENTITY_MISMATCH"
    similarity_score: float = Field(ge=0.0, le=1.0)
    message: str = "Face does not match citizen registry record."


# ── Internal / shared ─────────────────────────────────────────────────────


class VoterPublicView(BaseModel):
    """Read-only projection of a voter record (no PII fields)."""

    id: uuid.UUID
    voter_id: str
    registration_status: str
    registered_at: datetime
    verified_at: Optional[datetime] = None

    model_config = {"from_attributes": True}