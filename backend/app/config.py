"""Environment-based configuration.

All secrets (database passwords, LLM API keys, JWT secret) come from environment
variables. Nothing here is ever sent to the browser.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: Literal["development", "test", "production"] = "development"

    # --- Databases -------------------------------------------------------
    # Admin URL is used only by bootstrap/migration scripts (creates roles, schemas).
    admin_database_url: str = "postgresql+psycopg://postgres@localhost:5432/workmate"
    # Application role: read/write on the `app` schema, insert into `analytics` for imports.
    app_database_url: str = "postgresql+psycopg://workmate_app:workmate_app_pw@localhost:5432/workmate"
    # Read-only role used ONLY for executing validated analytical SQL.
    readonly_database_url: str = (
        "postgresql+psycopg://workmate_reader:workmate_reader_pw@localhost:5432/workmate"
    )
    db_pool_size: int = 5
    db_max_overflow: int = 5

    # --- Query execution limits -----------------------------------------
    query_timeout_ms: int = 5000
    query_row_limit: int = 1000

    # --- LLM ----------------------------------------------------------------
    llm_provider: Literal["none", "anthropic", "openai"] = "none"
    llm_model: str = ""
    llm_api_key: SecretStr | None = None
    llm_base_url: str = ""  # optional override (e.g. OpenAI-compatible gateway)
    llm_timeout_s: float = 45.0
    llm_max_retries: int = 2  # transport-level retries per call
    sql_repair_attempts: int = 2  # LLM SQL repair attempts after a validation/execution failure
    # Rough cost estimate inputs (USD per 1M tokens) used only for eval reporting.
    llm_input_cost_per_mtok: float = 3.0
    llm_output_cost_per_mtok: float = 15.0

    # --- Auth ---------------------------------------------------------------
    jwt_secret: SecretStr = SecretStr("dev-only-change-me-0123456789abcdef")
    jwt_ttl_minutes: int = 60 * 12
    allow_demo_login: bool = True
    allow_registration: bool = True
    cookie_secure: bool = False

    # --- Rate limiting ------------------------------------------------------
    analysis_rate_limit_per_minute: int = 10

    # --- Uploads ------------------------------------------------------------
    upload_dir: str = "/tmp/ai-workmate-uploads"
    upload_max_bytes: int = 10 * 1024 * 1024
    upload_max_rows: int = 200_000

    # --- Analytics defaults -----------------------------------------------
    default_reporting_timezone: str = "UTC"
    anomaly_z_threshold: float = 4.0
    anomaly_lookback_days: int = 60

    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    @property
    def llm_enabled(self) -> bool:
        return self.llm_provider != "none" and self.llm_api_key is not None and bool(
            self.llm_api_key.get_secret_value()
        )

    @property
    def resolved_llm_model(self) -> str:
        if self.llm_model:
            return self.llm_model
        return {"anthropic": "claude-sonnet-4-5", "openai": "gpt-4.1-mini"}.get(self.llm_provider, "")


@lru_cache
def get_settings() -> Settings:
    return Settings()
