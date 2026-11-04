"""Unit tests for Alembic migration schema and reproducibility."""
from __future__ import annotations

from pathlib import Path


def test_migration_contains_real_ddl():
    root = Path(__file__).resolve().parent.parent.parent
    versions = sorted((root / "migrations" / "versions").glob("*.py"))
    assert versions, "no migration revision files found"

    text = "\n".join(v.read_text(encoding="utf-8") for v in versions)
    creates = text.count("op.create_table(")
    assert creates >= 20, f"revision emits only {creates} op.create_table() calls"
    assert "create_all" not in text, "migration delegates to create_all"
    assert "from app.database.models import" not in text, "migration imports live models"
