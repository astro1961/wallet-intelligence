"""Add block_number and taken_at to balance_snapshots.

Revision ID: 003_balance_snapshot_block_time
Revises: 002_wallet_audit_log
Create Date: 2026-11-04 22:00:00.000000

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "003_balance_snapshot_block_time"
down_revision: str | None = "002_wallet_audit_log"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("balance_snapshots", sa.Column("block_number", sa.Integer(), nullable=True))
    op.add_column("balance_snapshots", sa.Column("taken_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("balance_snapshots", "taken_at")
    op.drop_column("balance_snapshots", "block_number")
