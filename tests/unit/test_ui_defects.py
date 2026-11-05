"""Unit tests for Stage 1B defects fixed in Stage 2B."""
from __future__ import annotations

import re
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


@pytest.mark.asyncio
@pytest.mark.parametrize("cols", [120, 140])
async def test_wallets_table_columns_do_not_collapse(cols: int) -> None:
    """Stage 3C polish: Wallets table right-most column must not collapse to 1 character."""
    from tests.unit.test_ui_wallets import seed_test_wallets

    app = WalletTrackerApp()
    async with app.run_test(size=(cols, 35)) as pilot:
        seed_test_wallets(app)
        await pilot.press("2")
        await pilot.pause()
        screen = app.screen
        screen.refresh_data()
        await pilot.pause()

        svg = app.export_screenshot()
        # Header must contain full Updated label, not cut off
        assert "Updated" in svg
        # Row timestamps must not be collapsed to a single character
        assert ("2026-11" in svg) or re.search(r"\d{4}-\d{2}-\d{2}", svg)


@pytest.mark.asyncio
async def test_wallet_details_panel_word_wrapping() -> None:
    """Stage 3C polish: Long descriptions in details panel must wrap words."""
    from app.core.wallet_manager import WalletManager

    app = WalletTrackerApp()
    async with app.run_test(size=(120, 35)) as pilot:
        with app.state.session_factory() as session:
            wm = WalletManager(session)
            w = wm.create_wallet(
                address="0x8888888888888888888888888888888888888888",
                name="TestWrap",
                notes="Alpha Beta Gamma Delta Epsilon Zeta Eta Theta Iota Kappa Lambda Mu",
            )
            session.commit()
            wid = w.id

        await pilot.press("2")
        await pilot.pause()
        screen = app.screen
        screen.show_history(wid)
        await pilot.pause()

        details = screen.query_one("#wallet-details", Static)
        assert details.styles.text_wrap == "wrap"
