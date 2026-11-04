"""Unit tests for WalletTrackerApp boot and exit lifecycle."""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.mark.asyncio
async def test_app_boots_to_dashboard(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Requirement 1: app boots -> dashboard active, no exception."""
    db_file = tmp_path / "boot_test.db"
    monkeypatch.setenv("WIT_DB_PATH", str(db_file))

    from app.application import WalletTrackerApp

    app = WalletTrackerApp()
    async with app.run_test(size=(120, 35)):
        assert app.is_running
        assert app.screen.id == "dashboard"
        assert app.state.active_screen == "dashboard"


@pytest.mark.asyncio
async def test_app_quit_with_q_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Requirement 4: q exits, is_running is False afterwards."""
    db_file = tmp_path / "quit_test.db"
    monkeypatch.setenv("WIT_DB_PATH", str(db_file))

    from app.application import WalletTrackerApp

    app = WalletTrackerApp()
    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.press("q")
        await pilot.pause()

    assert not app.is_running


@pytest.mark.asyncio
async def test_app_constructible_no_args(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """WalletTrackerApp must be constructible with no arguments and read WIT_DB_PATH."""
    db_file = tmp_path / "no_args.db"
    monkeypatch.setenv("WIT_DB_PATH", str(db_file))

    from app.application import WalletTrackerApp

    app = WalletTrackerApp()
    assert app.config is not None
    assert app.config.database.path == str(db_file)
    assert app.state is not None
    assert app.state.sync_state == "idle"
    assert app.state.last_update is None
