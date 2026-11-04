"""Integration tests for Alembic database migrations."""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from app.database import models as m


def test_alembic_upgrade_head_and_idempotency(tmp_path: Path):
    db_file = tmp_path / "migration_test.db"
    env = os.environ.copy()
    env["WIT_DB_PATH"] = str(db_file)
    env["PYTHONPATH"] = str(Path.cwd())

    # First migration run: creates all tables
    res1 = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
        check=False,
    )
    assert res1.returncode == 0, f"alembic upgrade head failed: {res1.stdout}\n{res1.stderr}"
    assert db_file.exists()

    conn = sqlite3.connect(str(db_file))
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    conn.close()

    assert "alembic_version" in tables
    assert m.Wallet.__tablename__ in tables
    assert len(tables) >= 23  # 22 models + alembic_version

    # Second migration run: must be idempotent and succeed without errors
    res2 = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
        check=False,
    )
    assert res2.returncode == 0, f"second alembic upgrade head failed: {res2.stdout}\n{res2.stderr}"
