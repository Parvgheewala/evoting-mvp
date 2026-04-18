# backend/app/services/seed_citizen_registry.py
# Run once to populate citizen_registry with test data.
# Usage: docker exec evoting_backend python app/services/seed_citizen_registry.py

import asyncio
import hashlib
import sys
import os

sys.path.insert(0, "/app")

import numpy as np
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models.citizen_registry import CitizenRegistry


def _mock_embedding(seed: int = 42) -> np.ndarray:
    rng = np.random.default_rng(seed)
    vec = rng.random(512).astype(np.float32)
    return vec / np.linalg.norm(vec)


# Test citizens — aadhaar/voter_id pairs used throughout Phase 2 testing
TEST_CITIZENS = [
    {
        "aadhaar_id": "888877776666",
        "voter_id": "GT1234567",
        "full_name": "Final Test",
        "date_of_birth": "1990-05-15",
        "constituency": "Mumbai North",
        # Seed 42 → deterministic embedding; mock live image will use seed
        # derived from its bytes, so we use seed=42 here and the verify
        # endpoint test will send a "magic" image that resolves to seed 42.
        "embedding_seed": 42,
        "photo_source": "aadhaar",
    },
    {
        "aadhaar_id": "111122223333",
        "voter_id": "DEF1112222",
        "full_name": "Amit Patel",
        "date_of_birth": "1985-08-22",
        "constituency": "Pune Central",
        "embedding_seed": 99,
        "photo_source": "aadhaar",
    },
]


async def seed():
    async with AsyncSessionLocal() as db:
        for citizen_data in TEST_CITIZENS:
            # Check if already seeded
            existing = await db.execute(
                select(CitizenRegistry).where(
                    CitizenRegistry.aadhaar_id == citizen_data["aadhaar_id"]
                )
            )
            if existing.scalar_one_or_none() is not None:
                print(f"Already exists: {citizen_data['aadhaar_id']} — skipping.")
                continue

            from datetime import date
            embedding = _mock_embedding(seed=citizen_data["embedding_seed"])
            embedding_bytes = embedding.tobytes()  # 512 × 4 bytes = 2048 bytes

            record = CitizenRegistry(
                aadhaar_id=citizen_data["aadhaar_id"],
                voter_id=citizen_data["voter_id"],
                full_name=citizen_data["full_name"],
                date_of_birth=date.fromisoformat(citizen_data["date_of_birth"]),
                constituency=citizen_data["constituency"],
                face_embedding=embedding_bytes,
                embedding_model="mock-seed-v1",
                photo_source=citizen_data["photo_source"],
                is_active=True,
            )
            db.add(record)
            print(f"Seeded: {citizen_data['aadhaar_id']} / {citizen_data['voter_id']}")

        await db.commit()
        print("Seeding complete.")


if __name__ == "__main__":
    asyncio.run(seed())