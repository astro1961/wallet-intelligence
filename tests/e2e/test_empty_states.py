"""E2E: пустые состояния — чистая БД, заглушки в панелях."""

from __future__ import annotations

from app.application import WalletTrackerApp


def _panel_text(app, selector: str) -> str:
    panel = app.screen.query_one(selector)
    renderable = getattr(panel, "renderable", None)
    return str(renderable if renderable is not None else panel.render())


async def test_dashboard_empty_wallets(app_env) -> None:
    """На чистой БД панель кошельков показывает empty state."""
    app = WalletTrackerApp()
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        assert "No wallets tracked yet" in _panel_text(app, "#panel-wallets")


async def test_wallets_screen_empty(app_env) -> None:
    """Экран Wallets на чистой БД открывается и не падает."""
    app = WalletTrackerApp()
    async with app.run_test(size=(140, 40)) as pilot:
        app.nav_to("wallets")
        await pilot.pause()
        assert app.screen.id == "wallets"
