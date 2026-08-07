"""Application settings loaded from environment / .env."""
from __future__ import annotations

from functools import lru_cache
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Hosts where TLS is not expected: a local or docker-compose Postgres serves no
# certificate, so requiring it would break local development.
_LOCAL_DB_HOSTS = {"localhost", "127.0.0.1", "::1", "db", ""}

# libpq's sslmode values mapped onto the ones asyncpg accepts. asyncpg has no
# equivalent of "allow" (try plaintext first, then TLS); "prefer" is the
# closest, and errs toward encryption.
_SSLMODE_TO_ASYNCPG = {
    "disable": "disable",
    "allow": "prefer",
    "prefer": "prefer",
    "require": "require",
    "verify-ca": "verify-ca",
    "verify-full": "verify-full",
}

# libpq parameters that asyncpg's connect() does not accept as keyword
# arguments. SQLAlchemy forwards every query parameter it does not consume
# straight to the driver, so one of these left in the URL raises TypeError on
# the very first connection, taking down the API and every worker at once.
#
# Managed providers append them freely: Neon hands out URLs ending
# `?sslmode=require&channel_binding=require`, and the ssl* family appears
# wherever a provider pins its own CA bundle. Dropping those is safe here
# because `ssl=require` still encrypts the connection; it just does not verify
# the server certificate against a specific root.
_LIBPQ_ONLY_PARAMS = frozenset(
    {
        "channel_binding",
        "gssencmode",
        "options",
        "sslcert",
        "sslcrl",
        "sslkey",
        "sslrootcert",
    }
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Async SQLAlchemy URL. docker-compose provides postgres on localhost:5432.
    database_url: str = (
        "postgresql+asyncpg://jobs:jobs@localhost:5432/jobscraper"
    )

    @field_validator("database_url")
    @classmethod
    def _use_async_driver(cls, v: str) -> str:
        """Normalize a managed-Postgres URL for asyncpg.

        Two adjustments, both because the URLs these providers hand out are
        written for libpq rather than for asyncpg:

        1. Scheme. Render, Neon, Heroku and Supabase all give out
           `postgres://` or `postgresql://`; SQLAlchemy's async engine needs
           the `postgresql+asyncpg://` driver.

        2. TLS. libpq spells this `sslmode`, asyncpg spells it `ssl`, and
           asyncpg silently ignores the parameter it does not recognize, so a
           URL ending `?sslmode=require` connects in plaintext. Managed
           Postgres rejects that with "SSL/TLS required", which takes down
           every process that touches the database at once. Any non-local host
           therefore gets `ssl=require` unless the URL asks for something else.
           Local hosts are left alone: a docker-compose Postgres has no
           certificate, and requiring TLS there would break local development.
        """
        if v.startswith("postgres://"):
            v = "postgresql://" + v[len("postgres://"):]
        if v.startswith("postgresql://"):
            v = "postgresql+asyncpg://" + v[len("postgresql://"):]
        if not v.startswith("postgresql+asyncpg://"):
            return v  # SQLite and friends need none of this

        parts = urlsplit(v)
        params = dict(parse_qsl(parts.query, keep_blank_values=True))

        sslmode = params.pop("sslmode", None)
        if "ssl" not in params:
            if sslmode:
                params["ssl"] = _SSLMODE_TO_ASYNCPG.get(sslmode, sslmode)
            elif (parts.hostname or "") not in _LOCAL_DB_HOSTS:
                params["ssl"] = "require"

        for key in _LIBPQ_ONLY_PARAMS:
            params.pop(key, None)

        return urlunsplit(parts._replace(query=urlencode(params)))

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

    # How many companies to crawl at once. Each one holds a database session,
    # so keep this comfortably under the managed Postgres connection limit
    # (Render's free tier is small). The crawl is dominated by round trips to
    # the database rather than by CPU, so concurrency buys a lot here; the
    # per-host throttle in scrapers/http.py still paces the ATS APIs.
    crawl_concurrency: int = 6

    # Workday has no listing-level detail, so we fetch each job's detail page.
    # Cap how many per company per crawl to bound request volume.
    workday_max_jobs: int = 200

    # Aggregator volume caps (bound against the free Postgres size limit).
    themuse_max_pages: int = 99  # 20 jobs/page; The Muse 400s beyond page ~99
    remotive_max_jobs: int = 600
    jobicy_max_jobs: int = 300
    adzuna_max_jobs: int = 1000
    adzuna_app_id: str = ""
    adzuna_app_key: str = ""

    # Brave Search for ATS board-token harvesting.
    brave_search_api_key: str = ""
    # One query per (host, role): 6 hosts x 8 roles. The full sweep runs weekly,
    # so ~200 queries a month, well inside Brave's free allowance.
    brave_search_max_queries: int = 48

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
