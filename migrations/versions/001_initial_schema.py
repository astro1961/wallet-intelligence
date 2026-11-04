"""Initial database schema with all 22 entities.

Revision ID: 001_initial_schema
Revises:
Create Date: 2026-11-04 18:00:00.000000

"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from app.database.models import Base

# revision identifiers, used by Alembic.
revision: str = "001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind)
