"""add 'adzuna' to atsprovider enum

Revision ID: e5f6a7b8c9d0
Revises: d4e3f2a1b0c9
Create Date: 2026-07-05

Idempotent Postgres enum addition (autocommit block + IF NOT EXISTS); no-op on
SQLite, where the enum is a VARCHAR.
"""
from typing import Union

from alembic import op

revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, None] = "d4e3f2a1b0c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            op.execute("ALTER TYPE atsprovider ADD VALUE IF NOT EXISTS 'adzuna'")


def downgrade() -> None:
    pass  # Postgres cannot drop enum values without recreating the type.
