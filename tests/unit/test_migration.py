"""Unit tests for Alembic migration schema and reproducibility."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config


def test_migration_contains_real_ddl():
    root = Path(__file__).resolve().parent.parent.parent
    versions = sorted((root / "migrations" / "versions").glob("*.py"))
    assert versions, "no migration revision files found"

    text = "\n".join(v.read_text(encoding="utf-8") for v in versions)
    creates = text.count("op.create_table(")
    assert creates >= 20, f"revision emits only {creates} op.create_table() calls"
    assert "create_all" not in text, "migration delegates to create_all"
    assert "from app.database.models import" not in text, "migration imports live models"


def test_migration_upgrade_downgrade_cycle(tmp_path: Path):
    db_file = tmp_path / "cycle_test.db"
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_file}")

    # Upgrade to head
    command.upgrade(cfg, "head")
    conn = sqlite3.connect(str(db_file))
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    conn.close()
    assert len(tables) == 23
    assert "wallets" in tables
    assert "alembic_version" in tables

    # Downgrade to base
    command.downgrade(cfg, "base")
    conn = sqlite3.connect(str(db_file))
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    conn.close()
    assert tables == {"alembic_version"}

    # Re-upgrade to head
    command.upgrade(cfg, "head")
    conn = sqlite3.connect(str(db_file))
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    conn.close()
    assert len(tables) == 23
    assert "wallets" in tables
