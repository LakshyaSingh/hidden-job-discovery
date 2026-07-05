"""Application settings loaded from environment / .env."""
from __future__ import annotations

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Async SQLAlchemy URL. docker-compose provides postgres on localhost:5432.
    database_url: str = (
        "postgresql+asyncpg://jobs:jobs@localhost:5432/jobscraper"
    )

    @field_validator("database_url")
    @classmethod
    def _use_async_driver(cls, v: str) -> str:
        """Managed Postgres hosts (Render, Neon, Heroku, Supabase) hand out
        `postgres://` or `postgresql://` URLs. SQLAlchemy's async engine needs
        the asyncpg driver, so normalize the scheme automatically."""
        if v.startswith("postgres://"):
            v = "postgresql://" + v[len("postgres://"):]
        if v.startswith("postgresql://"):
            v = "postgresql+asyncpg://" + v[len("postgresql://"):]
        return v

    # "development" enables conveniences like auto-creating tables on startup.
    # In "production" the app relies on Alembic migrations instead.
    environment: str = "development"

    # When true, the API creates tables on startup (handy for local/SQLite dev).
    # Leave false in production and run `alembic upgrade head` on deploy.
    auto_create_tables: bool = True

    # Comma-separated origins allowed to call the API (the Next.js dev server).
    cors_origins: str = "http://localhost:3000"

    # Secret guarding admin/write endpoints (crawl trigger, company create).
    # When empty, those endpoints are OPEN — set this in any public deployment.
    admin_api_key: str = ""

    # How long a freshly discovered job stays flagged is_new (hours).
    new_job_window_hours: int = 48

    # Workday has no listing-level detail, so we fetch each job's detail page.
    # Cap how many per company per crawl to bound request volume.
    workday_max_jobs: int = 200

    # Aggregator volume caps (bound against the free Postgres size limit).
    themuse_max_pages: int = 100  # 20 jobs/page
    remotive_max_jobs: int = 600
    jobicy_max_jobs: int = 300

    # Per-domain politeness: minimum seconds between requests to the same host.
    request_min_interval_seconds: float = 0.5
    request_timeout_seconds: float = 20.0
    request_max_retries: int = 3

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
