"""Add unique indexes for activity and transaction deduplication.

Revision ID: 005_activity_tx_dedup_indexes
Revises: 004_drop_balance_snapshot_taken_at
Create Date: 2026-11-05 04:00:00.000000

"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "005_activity_tx_dedup_indexes"
down_revision: str | None = "004_drop_balance_snapshot_taken_at"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("activities", schema=None) as batch_op:
        batch_op.create_index(
            "uq_activity_wallet_tx_log",
            ["wallet_id", "tx_hash", "log_index"],
            unique=True,
        )
    with op.batch_alter_table("transactions", schema=None) as batch_op:
        batch_op.create_index(
            "uq_transaction_wallet_network_tx",
            ["wallet_id", "network_id", "tx_hash"],
            unique=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("transactions", schema=None) as batch_op:
        batch_op.drop_index("uq_transaction_wallet_network_tx")
    with op.batch_alter_table("activities", schema=None) as batch_op:
        batch_op.drop_index("uq_activity_wallet_tx_log")
