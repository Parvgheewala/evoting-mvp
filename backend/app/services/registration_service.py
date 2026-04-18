# backend/app/services/registration_service.py

from __future__ import annotations

import uuid

from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.voter import Voter


async def check_duplicate(
    aadhaar_id: str,
    voter_id: str,
    db: AsyncSession,
) -> bool:
    """
    Return True if any voter row already holds this aadhaar_id OR voter_id.
    Uses OR so that either ID alone is sufficient to block re-registration.
    """
    result = await db.execute(
        select(Voter.id).where(
            or_(
                Voter.aadhaar_id == aadhaar_id,
                Voter.voter_id == voter_id,
            )
        ).limit(1)
    )
    return result.scalar_one_or_none() is not None


async def create_pending_voter(
    registration_id: uuid.UUID,
    aadhaar_id: str,
    voter_id: str,
    full_name: str,
    db: AsyncSession,
) -> Voter:
    """
    Insert a voter row with status='pending'.
    This slot-reservation prevents a second concurrent initiation request
    from passing the duplicate check while this session is in-flight.
    """
    voter = Voter(
        id=registration_id,
        aadhaar_id=aadhaar_id,
        voter_id=voter_id,
        full_name=full_name,
        registration_status="pending",
    )
    db.add(voter)
    await db.flush()   # write to DB within the transaction; get the ID back
    return voter