"""add jobs.is_us

Revision ID: b2f1a7c4d9e0
Revises: 859556036f98
Create Date: 2026-07-04

Adds a nullable country flag used to keep the board US-only. Existing rows stay
NULL until the next crawl backfills them (ingest sets is_us on every sighting).

Idempotent: guarded with the DB inspector so a concurrent or repeated
`alembic upgrade head` (e.g. the crawler and the API booting at the same time)
can never fail with "column/index already exists" and brick startup.
"""
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "b2f1a7c4d9e0"
down_revision: Union[str, None] = "859556036f98"
branch_labels = None
depends_on = None


def _has_column(inspector, table: str, column: str) -> bool:
    return any(c["name"] == column for c in inspector.get_columns(table))


def _has_index(inspector, table: str, index: str) -> bool:
    return any(i["name"] == index for i in inspector.get_indexes(table))


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not _has_column(inspector, "jobs", "is_us"):
        op.add_column("jobs", sa.Column("is_us", sa.Boolean(), nullable=True))
    if not _has_index(inspector, "jobs", "ix_jobs_is_us"):
        op.create_index("ix_jobs_is_us", "jobs", ["is_us"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if _has_index(inspector, "jobs", "ix_jobs_is_us"):
        op.drop_index("ix_jobs_is_us", table_name="jobs")
    if _has_column(inspector, "jobs", "is_us"):
        op.drop_column("jobs", "is_us")
