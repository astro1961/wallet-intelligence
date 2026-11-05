"""Make transactions unique per wallet, network, and tx_hash.

Revision ID: 006_transactions_unique_per_wallet
Revises: 005_activity_tx_dedup_indexes
Create Date: 2026-11-05 05:00:00.000000

"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = "006_transactions_unique_per_wallet"
down_revision: str | None = "005_activity_tx_dedup_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    indexes_tx = {idx["name"]: idx for idx in insp.get_indexes("transactions")}
    unique_tx = {uc["name"]: uc for uc in insp.get_unique_constraints("transactions")}

    with op.batch_alter_table("transactions", schema=None) as batch_op:
        # Drop legacy unique constraint on (network_id, tx_hash) if present
        if "uq_transaction_network_tx_hash" in unique_tx:
            batch_op.drop_constraint("uq_transaction_network_tx_hash", type_="unique")
        if "uq_transaction_network_tx_hash" in indexes_tx:
            batch_op.drop_index("uq_transaction_network_tx_hash")

        # Ensure uq_transaction_wallet_network_tx is unique on (wallet_id, network_id, tx_hash)
        wallet_idx = indexes_tx.get("uq_transaction_wallet_network_tx")
        if wallet_idx is not None:
            cols = list(wallet_idx.get("column_names") or [])
            if cols != ["wallet_id", "network_id", "tx_hash"]:
                batch_op.drop_index("uq_transaction_wallet_network_tx")
                batch_op.create_index(
                    "uq_transaction_wallet_network_tx",
                    ["wallet_id", "network_id", "tx_hash"],
                    unique=True,
                )
        elif "uq_transaction_wallet_network_tx" in unique_tx:
            cols = list(unique_tx["uq_transaction_wallet_network_tx"].get("column_names") or [])
            if cols != ["wallet_id", "network_id", "tx_hash"]:
                batch_op.drop_constraint("uq_transaction_wallet_network_tx", type_="unique")
                batch_op.create_index(
                    "uq_transaction_wallet_network_tx",
                    ["wallet_id", "network_id", "tx_hash"],
                    unique=True,
                )
        else:
            batch_op.create_index(
                "uq_transaction_wallet_network_tx",
                ["wallet_id", "network_id", "tx_hash"],
                unique=True,
            )

    indexes_act = {idx["name"]: idx for idx in insp.get_indexes("activities")}
    unique_act = {uc["name"]: uc for uc in insp.get_unique_constraints("activities")}

    with op.batch_alter_table("activities", schema=None) as batch_op:
        if "uq_activity_dedupe" in unique_act:
            batch_op.drop_constraint("uq_activity_dedupe", type_="unique")
        if "uq_activity_dedupe" in indexes_act:
            batch_op.drop_index("uq_activity_dedupe")


def downgrade() -> None:
    with op.batch_alter_table("activities", schema=None) as batch_op:
        batch_op.create_unique_constraint(
            "uq_activity_dedupe",
            ["network_id", "tx_hash", "log_index"],
        )
    with op.batch_alter_table("transactions", schema=None) as batch_op:
        batch_op.create_unique_constraint(
            "uq_transaction_network_tx_hash",
            ["network_id", "tx_hash"],
        )
