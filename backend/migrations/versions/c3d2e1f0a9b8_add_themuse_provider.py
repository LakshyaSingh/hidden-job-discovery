"""add 'themuse' to atsprovider enum

Revision ID: c3d2e1f0a9b8
Revises: b2f1a7c4d9e0
Create Date: 2026-07-04

Postgres needs an explicit ALTER TYPE to add an enum value; it must run outside
a transaction, hence the autocommit block. IF NOT EXISTS makes it idempotent and
safe under a concurrent/repeated upgrade. SQLite stores the enum as VARCHAR, so
no DDL is needed there (fresh databases pick the value up from the model).
"""
from typing import Union

from alembic import op

revision: str = "c3d2e1f0a9b8"
down_revision: Union[str, None] = "b2f1a7c4d9e0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            op.execute("ALTER TYPE atsprovider ADD VALUE IF NOT EXISTS 'themuse'")


def downgrade() -> None:
    # Postgres cannot drop an enum value without recreating the type; no-op.
    pass
