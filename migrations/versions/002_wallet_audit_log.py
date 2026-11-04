"""Add wallet audit log table.

Revision ID: 002_wallet_audit_log
Revises: 001_initial_schema
Create Date: 2026-11-04 20:00:00.000000

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "002_wallet_audit_log"
down_revision: str | None = "001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "wallet_audit_log",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("wallet_id", sa.Integer(), nullable=False),
        sa.Column("field", sa.String(length=64), nullable=False),
        sa.Column("old_value", sa.Text(), nullable=True),
        sa.Column("new_value", sa.Text(), nullable=True),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["wallet_id"], ["wallets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("wallet_audit_log", schema=None) as batch_op:
        batch_op.create_index("ix_wallet_audit_log_wallet_id", ["wallet_id"], unique=False)
        batch_op.create_index("ix_wallet_audit_log_changed_at", ["changed_at"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("wallet_audit_log", schema=None) as batch_op:
        batch_op.drop_index("ix_wallet_audit_log_changed_at")
        batch_op.drop_index("ix_wallet_audit_log_wallet_id")

    op.drop_table("wallet_audit_log")
