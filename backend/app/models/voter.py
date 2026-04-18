# backend/app/models/voter.py

import uuid
from datetime import datetime
from sqlalchemy import (
    Column, String, Boolean, DateTime,
    CheckConstraint, Index, ForeignKey, text
)
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base


class Voter(Base):
    """
    Registered voter record. Persisted after successful identity verification.
    registration_status lifecycle: pending → liveness_failed | identity_failed | active | suspended
    """
    __tablename__ = "voters"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    aadhaar_id = Column(
        String(12),
        nullable=False,
        unique=True,
        index=True,
    )
    voter_id = Column(
        String(20),
        nullable=False,
        unique=True,
        index=True,
    )
    full_name = Column(String(255), nullable=False)

    # SHA-256 of phone number — never store raw PII
    phone_hash = Column(String(64), nullable=True)

    # FK to a constituencies table (optional in MVP — nullable)
    constituency_id = Column(UUID(as_uuid=True), nullable=True)

    registration_status = Column(
        String(30),
        nullable=False,
        default="pending",
        server_default="pending",
    )

    # SHA-256 of the generated UTI (stored for audit; raw UTI lives in Redis)
    uti_hash = Column(String(64), nullable=True)

    # Reference to the matching citizen_registry row
    face_embedding_ref = Column(UUID(as_uuid=True), nullable=True)

    registered_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
        server_default=text("NOW()"),
    )
    verified_at = Column(DateTime(timezone=True), nullable=True)
    last_login_at = Column(DateTime(timezone=True), nullable=True)

    # ── Table-level constraints ─────────────────────────────────────────────
    __table_args__ = (
        CheckConstraint(
            "LENGTH(aadhaar_id) = 12",
            name="chk_aadhaar_len",
        ),
        CheckConstraint(
            "registration_status IN "
            "('pending','liveness_failed','identity_failed','active','suspended')",
            name="chk_voter_status",
        ),
        # Composite index for the duplicate-check query (aadhaar OR voter_id)
        Index("idx_voters_aadhaar", "aadhaar_id"),
        Index("idx_voters_voter_id", "voter_id"),
        Index("idx_voters_status", "registration_status"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<Voter id={self.id} voter_id={self.voter_id} "
            f"status={self.registration_status}>"
        )   