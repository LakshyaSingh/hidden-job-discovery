"""Shared test fixtures."""
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base


@pytest_asyncio.fixture
async def session_factory(tmp_path):
    """A sessionmaker over a fresh SQLite database with all tables created.

    Exposed separately from `session` because code that fans out concurrently
    opens a session per task instead of sharing one.
    """
    db_path = tmp_path / "test.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest_asyncio.fixture
async def session(session_factory):
    """A fresh SQLite-backed AsyncSession with all tables created."""
    async with session_factory() as s:
        yield s
