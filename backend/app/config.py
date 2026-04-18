# backend/app/config.py

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Database
    database_url: str

    mock_face_embedding: bool = False

    # Redis
    redis_url: str

    # Pulsar
    pulsar_url: str

    # Security
    secret_key: str
    jwt_algorithm: str = "HS256"
    jwt_expiry_minutes: int = 60

    # Face Matching
    face_similarity_threshold: float = 0.85

    # UTI Lifecycle
    uti_ttl_seconds: int = 86400

    # Liveness
    liveness_nonce_ttl_seconds: int = 90

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        # Docker-injected env vars take priority over .env file
        "case_sensitive": False,
    }


@lru_cache()
def get_settings() -> Settings:
    return Settings()