# backend/app/models/citizen_registry.py

import uuid
from datetime import datetime
from sqlalchemy import (
    Column, String, Boolean, Date, DateTime,
    LargeBinary, Index, text
)
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base


class CitizenRegistry(Base):
    """
    Government citizen reference table.
    Contains pre-stored 512-float face embeddings (serialised as BYTEA).
    In production: populated from authenticated government data sources.
    In MVP: seeded with synthetic test data.

    Embeddings are NEVER returned over the API — only similarity scores are surfaced.
    """
    __tablename__ = "citizen_registry"

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
    )
    voter_id = Column(
        String(20),
        nullable=False,
        unique=True,
    )
    full_name = Column(String(255), nullable=False)
    date_of_birth = Column(Date, nullable=False)
    constituency = Column(String(100), nullable=True)

    # 512-float vector serialised to raw bytes (2048 bytes per record)
    # numpy: np.array(dtype=np.float32, shape=(512,)).tobytes()
    face_embedding = Column(LargeBinary, nullable=False)

    # Which model generated this embedding
    embedding_model = Column(
        String(50),
        nullable=False,
        default="insightface-r100",
        server_default="'insightface-r100'",
    )

    # Source of the reference photograph
    photo_source = Column(
        String(50),
        nullable=True,
        # 'aadhaar' | 'passport' | 'electoral_roll'
    )

    is_active = Column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("TRUE"),
    )

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
        server_default=text("NOW()"),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
        server_default=text("NOW()"),
        onupdate=datetime.utcnow,
    )

    # ── Table-level indexes ─────────────────────────────────────────────────
    __table_args__ = (
        Index("idx_citizen_aadhaar", "aadhaar_id"),
        Index("idx_citizen_voter", "voter_id"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<CitizenRegistry id={self.id} aadhaar_id={self.aadhaar_id}>"
        )