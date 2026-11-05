"""Application configuration.

All settings come from environment variables (or a `.env` file in development).
Secrets such as the database password and JWT signing key are never hard-coded.
"""

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- General ---------------------------------------------------------
    app_name: str = "Smart Inventory"
    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    store_timezone: str = "Africa/Nairobi"
    currency: str = "KES"

    # --- Database --------------------------------------------------------
    database_url: str = Field(
        default="postgresql+psycopg://inventory:inventory@localhost:5432/inventory",
        description="SQLAlchemy URL. Use the postgresql+psycopg:// driver.",
    )
    db_pool_size: int = 5
    db_max_overflow: int = 5

    # --- Security --------------------------------------------------------
    jwt_secret: str = Field(default="change-me-in-env", min_length=16)
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 15
    refresh_token_days: int = 7
    refresh_reuse_grace_seconds: int = 10
    cookie_secure: bool = False  # set true when served over HTTPS
    password_min_length: int = 8
    login_max_failures: int = 5
    lockout_minutes: int = 15
    login_rate_limit_per_minute: int = 20  # per client IP
    password_reset_minutes: int = 30

    # --- URLs / CORS -----------------------------------------------------
    frontend_url: str = "http://localhost:8080"
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)

    # --- Storage ---------------------------------------------------------
    storage_dir: Path = Path("./storage")

    # --- Worker ----------------------------------------------------------
    worker_poll_seconds: float = 2.0
    worker_max_attempts: int = 3

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [o.strip() for o in value.split(",") if o.strip()]
        return value

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if settings.is_production and settings.jwt_secret == "change-me-in-env":  # noqa: S105
        raise RuntimeError("JWT_SECRET must be set to a strong random value in production")
    return settings
