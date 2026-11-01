"""Application settings, read from environment variables and `.env`."""

from datetime import datetime
from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All configuration for SpotWise. Use `get_settings()` instead of `os.getenv`."""

    # env_ignore_empty: a blank line like `LLM_MODEL=` in .env falls back to the default
    model_config = SettingsConfigDict(env_file=".env", env_ignore_empty=True, extra="ignore")

    # Database
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/spotwise"

    # Data sources
    entsoe_token: SecretStr | None = None
    price_area: str = "FI"
    vat_rate: float = 0.255
    timezone: str = "Europe/Helsinki"

    # Agent: "rules" = free rule-based answers (default), "llm" = Claude via LangGraph
    agent_mode: Literal["rules", "llm"] = "rules"

    # LLM (only used when agent_mode = "llm", and by the optional eval judge)
    anthropic_api_key: SecretStr | None = None
    llm_model: str | None = None
    judge_model: str | None = None

    # Tracing (off when keys are missing)
    langfuse_public_key: SecretStr | None = None
    langfuse_secret_key: SecretStr | None = None
    langfuse_host: str = "https://cloud.langfuse.com"

    # API
    cors_origins: str = "http://localhost:5173"
    chat_rate_limit_per_min: int = 20

    # Evals
    eval_now: datetime | None = None
    eval_database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/spotwise_eval"

    @property
    def cors_origin_list(self) -> list[str]:
        """CORS origins as a list (the env var is a comma-separated string)."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    """Return the cached settings instance."""
    return Settings()
