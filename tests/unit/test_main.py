"""Unit tests for CLI entry point main.py."""
from __future__ import annotations

from pathlib import Path

import pytest

from main import main as main_func


def test_main_launches_app_and_returns_zero(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Requirement 8: main.py main() starts the app (monkeypatched run) and returns 0."""
    db_file = tmp_path / "main_test.db"
    run_called = []

    from app.application import WalletTrackerApp

    def fake_run(self, *args, **kwargs):
        run_called.append(True)
        return 0

    monkeypatch.setattr(WalletTrackerApp, "run", fake_run)

    rc = main_func(["--db", str(db_file), "--log-level", "DEBUG"])
    assert rc == 0
    assert len(run_called) == 1
    assert db_file.exists()


def test_main_version(capsys: pytest.CaptureFixture) -> None:
    with pytest.raises(SystemExit) as exc:
        main_func(["--version"])
    assert exc.value.code == 0
    captured = capsys.readouterr()
    assert "0.1.0" in captured.out
