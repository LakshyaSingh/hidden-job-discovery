"""add companies.consecutive_missing

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-08-02

Counts how many crawls in a row found a board gone (404/410). Boards do die:
a company moves off Greenhouse, or changes its token, and the old one 404s on
every sweep forever. The crawler deactivates a board once this passes a
threshold, so dead boards stop costing a request an hour.

Only definitive "not found" responses count. A timeout or a 500 is an ATS
having a bad day, and must never retire a live board.

Idempotent: guarded with the DB inspector so a repeated or concurrent
`alembic upgrade head` (the crawler and the API can boot together) cannot fail
with "column already exists".
"""
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, None] = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def _has_column(inspector, table: str, column: str) -> bool:
    return any(c["name"] == column for c in inspector.get_columns(table))


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not _has_column(inspector, "companies", "consecutive_missing"):
        op.add_column(
            "companies",
            sa.Column(
                "consecutive_missing",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if _has_column(inspector, "companies", "consecutive_missing"):
        op.drop_column("companies", "consecutive_missing")
