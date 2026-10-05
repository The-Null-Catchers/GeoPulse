import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv("DATABASE_URL", "postgresql://geopulse:geopulse@localhost:5432/geopulse")
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    jwt_secret: str = os.getenv("JWT_SECRET", "")
    origins: tuple[str, ...] = tuple(os.getenv("CORS_ORIGINS", "http://localhost:3000").split(","))
    routing_url: str = os.getenv("ROUTING_URL", "")

    webhook_encryption_key: str = os.getenv("WEBHOOK_ENCRYPTION_KEY", "")
    webhook_allowed_hosts: tuple[str, ...] = tuple(
        h.strip().lower() for h in os.getenv("WEBHOOK_ALLOWED_HOSTS", "").split(",") if h.strip()
    )

    def validate(self):
        if len(self.jwt_secret) < 32:
            raise RuntimeError("JWT_SECRET must be at least 32 characters")


settings = Settings()
