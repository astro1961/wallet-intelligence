"""Unit tests for StatusBar widget and refresh hotkey."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from app.ui.widgets.status_bar import StatusBar


@pytest.mark.asyncio
async def test_status_bar_reflects_last_update_on_refresh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Requirement 6: status bar reflects last_update after pressing r."""
    db_file = tmp_path / "status_bar.db"
    monkeypatch.setenv("WIT_DB_PATH", str(db_file))

    from app.application import WalletTrackerApp

    app = WalletTrackerApp()
    async with app.run_test(size=(120, 35)) as pilot:
        status_bar = app.query_one(StatusBar)
        assert status_bar is not None
        assert status_bar.last_update is None
        assert "Never" in str(status_bar.render())

        # Press 'r' to refresh
        await pilot.press("r")
        await pilot.pause()

        assert status_bar.last_update is not None
        assert isinstance(status_bar.last_update, datetime)
        assert app.state.last_update is not None
        # Should now show the updated time
        rendered = str(status_bar.render())
        assert "Never" not in rendered
        assert status_bar.last_update.strftime("%H:%M") in rendered
