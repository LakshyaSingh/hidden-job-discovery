"""DATABASE_URL normalization.

Managed Postgres providers hand out URLs written for libpq. SQLAlchemy forwards
any query parameter it does not consume straight to the driver, so a parameter
asyncpg does not recognize is not ignored, it raises TypeError on the first
connection and takes down the API and every worker at once. This has already
happened twice, once for sslmode and once for channel_binding, so the contract
gets tests.
"""
import inspect

import asyncpg
import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import Settings

# Every kwarg name asyncpg.connect() will accept.
_ASYNCPG_KWARGS = set(inspect.signature(asyncpg.connect).parameters)


def connect_kwargs(raw_url: str) -> dict:
    """What asyncpg.connect() would actually be called with."""
    engine = create_async_engine(Settings(database_url=raw_url).database_url)
    _, kwargs = engine.dialect.create_connect_args(engine.url)
    return kwargs


# Real URL shapes, as each provider hands them out.
PROVIDER_URLS = [
    pytest.param(
        "postgresql://u:p@ep-cool-frog-a1b2.us-west-2.aws.neon.tech/neondb"
        "?sslmode=require&channel_binding=require",
        id="neon",
    ),
    pytest.param(
        "postgres://u:p@dpg-abc123-a.oregon-postgres.render.com/jobscraper",
        id="render-external",
    ),
    pytest.param(
        "postgresql://postgres:p@db.abcdefgh.supabase.co:5432/postgres"
        "?sslmode=require",
        id="supabase",
    ),
    pytest.param(
        "postgres://u:p@ec2-1-2-3-4.compute-1.amazonaws.com:5432/d123"
        "?sslmode=require&sslrootcert=/etc/ssl/certs/ca.pem",
        id="heroku-with-ca-bundle",
    ),
]


@pytest.mark.parametrize("raw", PROVIDER_URLS)
def test_provider_urls_produce_only_kwargs_asyncpg_accepts(raw):
    unknown = set(connect_kwargs(raw)) - _ASYNCPG_KWARGS
    assert not unknown, f"asyncpg.connect() would reject: {sorted(unknown)}"


@pytest.mark.parametrize("raw", PROVIDER_URLS)
def test_remote_providers_always_get_tls(raw):
    """asyncpg spells this `ssl`; a surviving `sslmode` means plaintext."""
    kwargs = connect_kwargs(raw)
    assert kwargs.get("ssl") == "require"
    assert "sslmode" not in kwargs


def test_scheme_is_rewritten_for_the_async_driver():
    for raw in ("postgres://u:p@example.com/db", "postgresql://u:p@example.com/db"):
        assert Settings(database_url=raw).database_url.startswith(
            "postgresql+asyncpg://"
        )


def test_local_development_is_left_unencrypted():
    """A docker-compose or localhost Postgres serves no certificate."""
    for host in ("localhost", "127.0.0.1", "db"):
        kwargs = connect_kwargs(f"postgresql://jobs:jobs@{host}:5432/jobscraper")
        assert "ssl" not in kwargs, f"{host} should not require TLS"


def test_an_explicit_sslmode_is_honoured_not_overridden():
    kwargs = connect_kwargs("postgresql://u:p@example.com/db?sslmode=disable")
    assert kwargs.get("ssl") == "disable"


def test_sqlite_urls_are_untouched():
    raw = "sqlite+aiosqlite:///./dev.db"
    assert Settings(database_url=raw).database_url == raw
