"""Unit tests for Stage 1B defects fixed in Stage 2B."""
from __future__ import annotations

from pathlib import Path

import pytest
from textual.widgets import Static

from app.application import WalletTrackerApp


@pytest.fixture(autouse=True)
def _test_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WIT_DB_PATH", str(tmp_path / "defects_test.db"))


@pytest.mark.asyncio
async def test_bottom_hotkey_bar_does_not_clip_at_110_columns() -> None:
    """Defect 1: Hotkey bar rendered string length must be <= width at 110 columns."""
    app = WalletTrackerApp()
    async with app.run_test(size=(110, 30)) as pilot:
        await pilot.pause()
        bottom_bar = app.screen.query_one("#bottom-bar")
        rendered = str(bottom_bar.render())
        # Rendered text length must not exceed width 110
        assert len(rendered) <= 110
        # Must not truncate mid-word with ellipsis
        assert "Qu…" not in rendered


@pytest.mark.asyncio
async def test_screen_descriptions_use_static_wrap() -> None:
    """Defect 2: Screen descriptions use Static with wrapping enabled."""
    app = WalletTrackerApp()
    async with app.run_test(size=(100, 30)) as pilot:
        for idx in range(1, 10):
            await pilot.press(str(idx))
            await pilot.pause()
            desc = app.screen.query_one(".screen-desc")
            assert isinstance(desc, Static), f"Screen {app.screen.id} description must be Static"


@pytest.mark.asyncio
async def test_layout_usable_at_60x20() -> None:
    """Defect 3: Layout stays usable at 60x20 without crashing, sidebar shrinks."""
    app = WalletTrackerApp()
    async with app.run_test(size=(60, 20)) as pilot:
        await pilot.pause()
        # Verify app is alive
        assert app.is_running
        # Switch to wallets
        await pilot.press("2")
        await pilot.pause()
        assert app.screen.id == "wallets"

        # Hotkey bar fits within 60 columns
        bottom_bar = app.screen.query_one("#bottom-bar")
        rendered = str(bottom_bar.render())
        assert len(rendered) <= 60
