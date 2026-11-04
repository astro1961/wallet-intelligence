"""Drop duplicate taken_at column from balance_snapshots.

Revision ID: 004_drop_balance_snapshot_taken_at
Revises: 003_balance_snapshot_block_time
Create Date: 2026-11-05 03:00:00.000000

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "004_drop_balance_snapshot_taken_at"
down_revision: str | None = "003_balance_snapshot_block_time"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("balance_snapshots", "taken_at")


def downgrade() -> None:
    op.add_column("balance_snapshots", sa.Column("taken_at", sa.DateTime(timezone=True), nullable=True))
