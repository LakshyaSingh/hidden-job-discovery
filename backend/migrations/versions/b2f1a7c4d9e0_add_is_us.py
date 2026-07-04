"""add jobs.is_us

Revision ID: b2f1a7c4d9e0
Revises: 859556036f98
Create Date: 2026-07-04

Adds a nullable country flag used to keep the board US-only. Existing rows stay
NULL until the next crawl backfills them (ingest sets is_us on every sighting).
"""
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "b2f1a7c4d9e0"
down_revision: Union[str, None] = "859556036f98"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("is_us", sa.Boolean(), nullable=True))
    op.create_index("ix_jobs_is_us", "jobs", ["is_us"])


def downgrade() -> None:
    op.drop_index("ix_jobs_is_us", table_name="jobs")
    op.drop_column("jobs", "is_us")
