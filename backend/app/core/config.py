from pathlib import Path
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


BACKEND_DIR = Path(__file__).resolve().parents[2]
ENV_FILE = BACKEND_DIR / ".env"


def resolve_database_url(value: str) -> str:
    """Resolve relative SQLite database paths from the backend directory."""
    url = make_url(value)
    if url.drivername.split("+", 1)[0] != "sqlite" or not url.database:
        return value

    database_path = Path(url.database)
    if not database_path.is_absolute():
        database_path = BACKEND_DIR / database_path
    return url.set(database=str(database_path)).render_as_string(hide_password=False)


class Settings(BaseSettings):
    app_name: str = "SmartRoster AI API"
    debug: bool = False
    database_url: str = "sqlite:///./smartroster.db"
    cors_origins: list[str] = ["http://localhost:5173"]
    environment: str = "development"
    auth_secret: str | None = None
    auth_issuer: str = "smartroster-ai"
    auth_audience: str = "smartroster-api"
    access_token_minutes: int = 30
    bootstrap_admin_token: str | None = None

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_prefix="BACKEND_",
        extra="ignore",
    )

    @field_validator("database_url")
    @classmethod
    def resolve_database_path(cls, value: str) -> str:
        return resolve_database_url(value)

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("access_token_minutes")
    @classmethod
    def validate_token_expiration(cls, value: int) -> int:
        if value < 1 or value > 1440:
            raise ValueError("access_token_minutes must be between 1 and 1440")
        return value

    @field_validator("auth_secret")
    @classmethod
    def validate_production_secret(cls, value: str | None, info):
        if info.data.get("environment") == "production" and not value:
            raise ValueError("BACKEND_AUTH_SECRET is required in production")
        if value is not None and len(value) < 32:
            raise ValueError("BACKEND_AUTH_SECRET must contain at least 32 characters")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
