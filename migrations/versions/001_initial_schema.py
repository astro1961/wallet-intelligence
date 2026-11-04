"""Initial database schema with all 22 entities.

Revision ID: 001_initial_schema
Revises:
Create Date: 2026-11-04 18:00:00.000000

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "networks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("chain_type", sa.String(length=32), nullable=False),
        sa.Column("chain_id", sa.Integer(), nullable=True),
        sa.Column("rpc_url", sa.String(length=255), nullable=True),
        sa.Column("explorer_url", sa.String(length=255), nullable=True),
        sa.Column("native_token", sa.String(length=32), nullable=True),
        sa.Column("symbol", sa.String(length=32), nullable=True),
        sa.Column("decimals", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("is_testnet", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("chain_type", "chain_id", name="uq_network_chain_type_chain_id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "projects",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("official_url", sa.String(length=255), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "providers",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("api_key_env", sa.String(length=128), nullable=True),
        sa.Column("base_url", sa.String(length=255), nullable=True),
        sa.Column("rate_limit_per_second", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "wallet_groups",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("parent_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["parent_id"], ["wallet_groups.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "wallet_tags",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("color", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "project_contracts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("network_id", sa.Integer(), nullable=False),
        sa.Column("contract_address", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=True),
        sa.Column("abi", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["network_id"], ["networks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("network_id", "contract_address", name="uq_project_contract_network_address"),
    )
    with op.batch_alter_table("project_contracts", schema=None) as batch_op:
        batch_op.create_index("ix_project_contracts_contract_address", ["contract_address"], unique=False)

    op.create_table(
        "rpc_endpoints",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("network_id", sa.Integer(), nullable=False),
        sa.Column("url", sa.String(length=255), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.Column("is_backup", sa.Boolean(), nullable=False),
        sa.Column("is_healthy", sa.Boolean(), nullable=False),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["network_id"], ["networks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "tokens",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("network_id", sa.Integer(), nullable=False),
        sa.Column("contract_address", sa.String(length=128), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=True),
        sa.Column("decimals", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["network_id"], ["networks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("network_id", "contract_address", name="uq_token_network_address"),
    )
    op.create_table(
        "wallets",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("address", sa.String(length=128), nullable=False),
        sa.Column("address_raw", sa.String(length=128), nullable=True),
        sa.Column("chain_type", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("group_id", sa.Integer(), nullable=True),
        sa.Column("archived", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("first_activity_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["group_id"], ["wallet_groups.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("address", "chain_type", name="uq_wallet_address_chain_type"),
    )
    with op.batch_alter_table("wallets", schema=None) as batch_op:
        batch_op.create_index("ix_wallets_address", ["address"], unique=False)
        batch_op.create_index("ix_wallets_group_id", ["group_id"], unique=False)

    op.create_table(
        "activities",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("wallet_id", sa.Integer(), nullable=False),
        sa.Column("network_id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("tx_hash", sa.String(length=128), nullable=True),
        sa.Column("log_index", sa.Integer(), nullable=True),
        sa.Column("activity_type", sa.String(length=64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("contract_address", sa.String(length=128), nullable=True),
        sa.Column("token_symbol", sa.String(length=32), nullable=True),
        sa.Column("amount", sa.Numeric(precision=38, scale=18), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("is_manual", sa.Boolean(), nullable=False),
        sa.Column("explorer_url", sa.String(length=255), nullable=True),
        sa.Column("extra_data", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["network_id"], ["networks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["wallet_id"], ["wallets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("network_id", "tx_hash", "log_index", name="uq_activity_dedupe"),
    )
    with op.batch_alter_table("activities", schema=None) as batch_op:
        batch_op.create_index("ix_activities_occurred_at", ["occurred_at"], unique=False)

    op.create_table(
        "balance_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("wallet_id", sa.Integer(), nullable=False),
        sa.Column("network_id", sa.Integer(), nullable=False),
        sa.Column("token_id", sa.Integer(), nullable=True),
        sa.Column("raw_balance", sa.String(length=128), nullable=True),
        sa.Column("balance", sa.Numeric(precision=38, scale=18), nullable=False),
        sa.Column("usd_price", sa.Numeric(precision=38, scale=18), nullable=True),
        sa.Column("usd_value", sa.Numeric(precision=38, scale=18), nullable=True),
        sa.Column("snapshot_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["network_id"], ["networks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["token_id"], ["tokens.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["wallet_id"], ["wallets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "defi_positions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("wallet_id", sa.Integer(), nullable=False),
        sa.Column("network_id", sa.Integer(), nullable=False),
        sa.Column("protocol", sa.String(length=100), nullable=False),
        sa.Column("position_type", sa.String(length=64), nullable=False),
        sa.Column("certainty", sa.String(length=32), nullable=False),
        sa.Column("amount", sa.Numeric(precision=38, scale=18), nullable=True),
        sa.Column("usd_value", sa.Numeric(precision=38, scale=18), nullable=True),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("last_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["network_id"], ["networks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["wallet_id"], ["wallets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "notes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("wallet_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["wallet_id"], ["wallets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "project_tasks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("wallet_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("due_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["wallet_id"], ["wallets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "project_wallets",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("wallet_id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("interactions_count", sa.Integer(), nullable=False),
        sa.Column("first_interaction_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_interaction_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["wallet_id"], ["wallets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "wallet_id", name="uq_project_wallet"),
    )
    op.create_table(
        "sync_cursors",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("wallet_id", sa.Integer(), nullable=False),
        sa.Column("network_id", sa.Integer(), nullable=False),
        sa.Column("data_type", sa.String(length=64), nullable=False),
        sa.Column("cursor_value", sa.String(length=255), nullable=False),
        sa.Column("last_block_number", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["network_id"], ["networks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["wallet_id"], ["wallets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("wallet_id", "network_id", "data_type", name="uq_sync_cursor"),
    )
    op.create_table(
        "sync_jobs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("wallet_id", sa.Integer(), nullable=True),
        sa.Column("network_id", sa.Integer(), nullable=True),
        sa.Column("job_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["network_id"], ["networks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["wallet_id"], ["wallets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "transactions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("wallet_id", sa.Integer(), nullable=False),
        sa.Column("network_id", sa.Integer(), nullable=False),
        sa.Column("tx_hash", sa.String(length=128), nullable=False),
        sa.Column("block_number", sa.Integer(), nullable=True),
        sa.Column("from_address", sa.String(length=128), nullable=False),
        sa.Column("to_address", sa.String(length=128), nullable=True),
        sa.Column("value", sa.Numeric(precision=38, scale=18), nullable=True),
        sa.Column("gas_price", sa.Numeric(precision=38, scale=18), nullable=True),
        sa.Column("gas_used", sa.Numeric(precision=38, scale=18), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("is_manual", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["network_id"], ["networks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["wallet_id"], ["wallets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("network_id", "tx_hash", name="uq_transaction_network_tx_hash"),
    )
    with op.batch_alter_table("transactions", schema=None) as batch_op:
        batch_op.create_index("ix_transactions_tx_hash", ["tx_hash"], unique=False)

    op.create_table(
        "wallet_networks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("wallet_id", sa.Integer(), nullable=False),
        sa.Column("network_id", sa.Integer(), nullable=False),
        sa.Column("monitoring_status", sa.String(length=32), nullable=False),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["network_id"], ["networks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["wallet_id"], ["wallets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("wallet_id", "network_id", name="uq_wallet_network"),
    )
    with op.batch_alter_table("wallet_networks", schema=None) as batch_op:
        batch_op.create_index("ix_wallet_networks_network_id", ["network_id"], unique=False)

    op.create_table(
        "wallet_relations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("from_wallet_id", sa.Integer(), nullable=False),
        sa.Column("to_wallet_id", sa.Integer(), nullable=False),
        sa.Column("relation_type", sa.String(length=64), nullable=False),
        sa.Column("confidence", sa.String(length=32), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["from_wallet_id"], ["wallets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["to_wallet_id"], ["wallets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "wallet_socials",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("wallet_id", sa.Integer(), nullable=False),
        sa.Column("platform", sa.String(length=64), nullable=False),
        sa.Column("handle", sa.String(length=128), nullable=False),
        sa.Column("url", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["wallet_id"], ["wallets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "wallet_tag_links",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("wallet_id", sa.Integer(), nullable=False),
        sa.Column("tag_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tag_id"], ["wallet_tags.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["wallet_id"], ["wallets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("wallet_id", "tag_id", name="uq_wallet_tag_link"),
    )


def downgrade() -> None:
    op.drop_table("wallet_tag_links")
    op.drop_table("wallet_socials")
    op.drop_table("wallet_relations")
    with op.batch_alter_table("wallet_networks", schema=None) as batch_op:
        batch_op.drop_index("ix_wallet_networks_network_id")

    op.drop_table("wallet_networks")
    with op.batch_alter_table("transactions", schema=None) as batch_op:
        batch_op.drop_index("ix_transactions_tx_hash")

    op.drop_table("transactions")
    op.drop_table("sync_jobs")
    op.drop_table("sync_cursors")
    op.drop_table("project_wallets")
    op.drop_table("project_tasks")
    op.drop_table("notes")
    op.drop_table("defi_positions")
    op.drop_table("balance_snapshots")
    with op.batch_alter_table("activities", schema=None) as batch_op:
        batch_op.drop_index("ix_activities_occurred_at")

    op.drop_table("activities")
    with op.batch_alter_table("wallets", schema=None) as batch_op:
        batch_op.drop_index("ix_wallets_group_id")
        batch_op.drop_index("ix_wallets_address")

    op.drop_table("wallets")
    op.drop_table("tokens")
    op.drop_table("rpc_endpoints")
    with op.batch_alter_table("project_contracts", schema=None) as batch_op:
        batch_op.drop_index("ix_project_contracts_contract_address")

    op.drop_table("project_contracts")
    op.drop_table("wallet_tags")
    op.drop_table("wallet_groups")
    op.drop_table("providers")
    op.drop_table("projects")
    op.drop_table("networks")
