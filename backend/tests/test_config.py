"""Database URL normalization.

Managed Postgres URLs are written for libpq, not for asyncpg. Getting this
wrong is not a degraded connection, it is no connection: the provider answers
"SSL/TLS required" and every process that touches the database fails at once.
"""
from app.config import Settings


def _url(raw: str) -> str:
    return Settings(database_url=raw).database_url


def test_scheme_is_normalized_for_asyncpg():
    """Render, Heroku and Supabase all hand out one of these two schemes."""
    assert _url("postgres://u:p@host.render.com/db").startswith(
        "postgresql+asyncpg://"
    )
    assert _url("postgresql://u:p@host.render.com/db").startswith(
        "postgresql+asyncpg://"
    )


def test_sslmode_is_translated_to_asyncpgs_spelling():
    """asyncpg ignores libpq's sslmode outright, so it has to be rewritten.

    Left as-is, the URL connects in plaintext and the server refuses it.
    """
    out = _url("postgres://u:p@host.render.com/db?sslmode=require")
    assert "ssl=require" in out
    assert "sslmode" not in out


def test_remote_host_gets_tls_even_when_the_url_is_silent():
    out = _url("postgresql://u:p@dpg-abc123-a.oregon-postgres.render.com/db")
    assert "ssl=require" in out


def test_local_hosts_are_left_unencrypted():
    """A docker-compose Postgres serves no certificate."""
    for host in ("localhost", "127.0.0.1", "db"):
        out = _url(f"postgresql://jobs:jobs@{host}:5432/jobscraper")
        assert "ssl" not in out, host


def test_an_explicit_choice_is_respected():
    assert "ssl=disable" in _url("postgres://u:p@host.example.com/db?sslmode=disable")
    assert "ssl=verify-full" in _url(
        "postgres://u:p@host.example.com/db?ssl=verify-full"
    )


def test_other_query_parameters_survive():
    out = _url("postgres://u:p@host.example.com/db?sslmode=require&application_name=jobs")
    assert "application_name=jobs" in out
    assert "ssl=require" in out


def test_sqlite_is_untouched():
    assert _url("sqlite+aiosqlite:///./dev.db") == "sqlite+aiosqlite:///./dev.db"
