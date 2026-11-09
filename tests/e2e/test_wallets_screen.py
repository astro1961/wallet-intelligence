"""E2E: экран Wallets — пустое состояние и поиск."""

from __future__ import annotations

from textual.widgets import DataTable, Input

from app.application import WalletTrackerApp
from tests.fixtures.factories import make_wallet


async def test_empty_state_visible_on_clean_db(app_env) -> None:
    """На чистой БД показан empty-state кошельков."""
    app = WalletTrackerApp()
    async with app.run_test(size=(140, 40)) as pilot:
        app.nav_to("wallets")
        await pilot.pause()
        empty = app.screen.query_one("#empty-state")
        assert empty.display is True
        assert "No wallets" in str(empty.render())


async def test_search_filters_table(app_env) -> None:
    """Поиск по имени сужает таблицу до совпадений."""
    app = WalletTrackerApp()
    async with app.run_test(size=(140, 40)) as pilot:
        with app.state.session_factory() as session:
            make_wallet(session, address="0xaaaabbbbccccddddeeeeffff00001111222233a1", name="Alpha")
            make_wallet(session, address="0xbbbcccccddddeeeeffff0000111122223333a2", name="Beta")

        app.nav_to("wallets")
        await pilot.pause()
        table = app.screen.query_one("#wallet-table", DataTable)
        assert table.row_count == 2

        app.screen.query_one("#wallet-search", Input).value = "Alpha"
        app.screen._apply_search()
        await pilot.pause()
        assert table.row_count == 1
