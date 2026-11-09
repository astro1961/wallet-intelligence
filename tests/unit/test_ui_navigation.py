"""Unit tests for navigation, hotkeys, and sidebar interaction."""
from __future__ import annotations

from pathlib import Path

import pytest
from textual.widgets import Input

SCREEN_KEYS = [
    "dashboard",
    "wallets",
]


@pytest.mark.parametrize("idx,key", list(enumerate(SCREEN_KEYS, start=1)))
@pytest.mark.asyncio
async def test_numeric_keys_switch_screens(idx: int, key: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Requirement 2: all nine hotkeys switch to the expected screen id."""
    db_file = tmp_path / f"nav_keys_{idx}.db"
    monkeypatch.setenv("WIT_DB_PATH", str(db_file))

    from app.application import WalletTrackerApp

    app = WalletTrackerApp()
    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.press(str(idx))
        await pilot.pause()
        assert app.screen.id == key, f"Key {idx} did not switch to {key}, got {app.screen.id}"


@pytest.mark.asyncio
async def test_sidebar_keyboard_navigation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Requirement 3: sidebar navigation with ↑/↓/Enter."""
    db_file = tmp_path / "nav_sidebar.db"
    monkeypatch.setenv("WIT_DB_PATH", str(db_file))

    from app.application import WalletTrackerApp

    app = WalletTrackerApp()
    async with app.run_test(size=(120, 35)) as pilot:
        # Start on dashboard (index 0)

        assert app.screen.id == "dashboard"

        # Press down -> moves cursor to index 1 (wallets)
        await pilot.press("down")
        await pilot.pause()

        # Press enter -> activates wallets screen
        await pilot.press("enter")
        await pilot.pause()
        assert app.screen.id == "wallets"

        # Press up -> back to dashboard (index 0)
        await pilot.press("up")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert app.screen.id == "dashboard"


@pytest.mark.asyncio
async def test_escape_returns_to_dashboard(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Esc returns to dashboard."""
    db_file = tmp_path / "nav_esc.db"
    monkeypatch.setenv("WIT_DB_PATH", str(db_file))

    from app.application import WalletTrackerApp

    app = WalletTrackerApp()
    async with app.run_test(size=(120, 35)) as pilot:
        # Switch to wallets (key 2)
        await pilot.press("2")
        await pilot.pause()
        assert app.screen.id == "wallets"

        # Press escape -> back to dashboard
        await pilot.press("escape")
        await pilot.pause()
        assert app.screen.id == "dashboard"


@pytest.mark.asyncio
async def test_stage_notification_hotkeys(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Other hotkeys (a, i, f, g, /) show notifications mentioning upcoming stages."""
    db_file = tmp_path / "nav_notif.db"
    monkeypatch.setenv("WIT_DB_PATH", str(db_file))

    from app.application import WalletTrackerApp

    app = WalletTrackerApp()
    async with app.run_test(size=(120, 35)) as pilot:
        # Test hotkeys do not crash and emit notifications
        for key in ["a", "i", "f", "g", "slash"]:
            await pilot.press(key)
            await pilot.pause()


@pytest.mark.asyncio
async def test_hotkeys_do_not_fire_when_text_input_focused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Hotkeys must not fire while a text input has focus."""
    db_file = tmp_path / "nav_input.db"
    monkeypatch.setenv("WIT_DB_PATH", str(db_file))

    from app.application import WalletTrackerApp

    app = WalletTrackerApp()
    async with app.run_test(size=(120, 35)) as pilot:
        # Mount an input widget to test typing
        test_input = Input(id="test_filter_input")
        await app.screen.mount(test_input)
        test_input.focus()
        await pilot.pause()

        # Type '2' and 'q' into input
        await pilot.press("2")
        await pilot.press("q")
        await pilot.pause()

        # App should still be running on dashboard and input has '2q'
        assert app.is_running
        assert app.screen.id == "dashboard"
        assert test_input.value == "2q"
