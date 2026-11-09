"""E2E: навигация по всем 9 экранам приложения (Textual headless)."""

from __future__ import annotations

import pytest

from app.application import WalletTrackerApp

ALL_SCREENS = [
    "dashboard",
    "wallets",
    "activities",
    "projects",
    "defi",
    "networks",
    "graph",
    "import",
    "settings",
]


@pytest.mark.parametrize("screen_id", ALL_SCREENS)
async def test_navigate_to_screen(app_env, screen_id: str) -> None:
    """Каждый экран монтируется, принимает фокус и не падает."""
    app = WalletTrackerApp()
    async with app.run_test(size=(140, 40)) as pilot:
        app.nav_to(screen_id)
        await pilot.pause()
        assert app.screen.id == screen_id, f"expected screen {screen_id}, got {app.screen.id}"


async def test_cycle_through_all_screens(app_env) -> None:
    """Полный цикл по всем экранам и возврат на dashboard без исключений."""
    app = WalletTrackerApp()
    async with app.run_test(size=(140, 40)) as pilot:
        for screen_id in ALL_SCREENS:
            app.nav_to(screen_id)
            await pilot.pause()
            assert app.screen.id == screen_id
        app.nav_to("dashboard")
        await pilot.pause()
        assert app.screen.id == "dashboard"
