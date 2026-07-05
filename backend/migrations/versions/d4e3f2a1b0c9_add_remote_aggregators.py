"""add 'remotive' and 'jobicy' to atsprovider enum

Revision ID: d4e3f2a1b0c9
Revises: c3d2e1f0a9b8
Create Date: 2026-07-05

Idempotent Postgres enum additions (autocommit block + IF NOT EXISTS); no-op on
SQLite, where the enum is a VARCHAR.
"""
from typing import Union

from alembic import op

revision: str = "d4e3f2a1b0c9"
down_revision: Union[str, None] = "c3d2e1f0a9b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            op.execute("ALTER TYPE atsprovider ADD VALUE IF NOT EXISTS 'remotive'")
            op.execute("ALTER TYPE atsprovider ADD VALUE IF NOT EXISTS 'jobicy'")


def downgrade() -> None:
    pass  # Postgres cannot drop enum values without recreating the type.
