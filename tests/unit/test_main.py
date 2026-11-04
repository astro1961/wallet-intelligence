"""Unit tests for CLI entry point main.py."""
from __future__ import annotations

from pathlib import Path

import pytest

from main import main


def test_main_runs_and_exits_cleanly(tmp_path: Path, capsys: pytest.CaptureFixture):
    db_file = tmp_path / "main_test.db"
    # Running with --db flag should initialize DB and exit 0 cleanly with stage notice
    with pytest.raises(SystemExit) as exc:
        main(["--db", str(db_file), "--log-level", "DEBUG"])
    assert exc.value.code == 0
    captured = capsys.readouterr()
    assert "Stage 1A initialized successfully" in captured.out
    assert db_file.exists()


def test_main_version(capsys: pytest.CaptureFixture):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    captured = capsys.readouterr()
    assert "0.1.0" in captured.out
