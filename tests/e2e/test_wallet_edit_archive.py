"""E2E: редактирование и архивация кошелька."""

from __future__ import annotations

from textual.widgets import Input

from app.application import WalletTrackerApp
from app.database.models import Wallet
from tests.fixtures.factories import make_wallet


async def test_edit_wallet_name(app_env) -> None:
    """Редактирование через форму меняет имя в БД."""
    app = WalletTrackerApp()
    async with app.run_test(size=(140, 40)) as pilot:
        with app.state.session_factory() as session:
            w = make_wallet(session, name="OldName")
            wid = w.id

        app.nav_to("wallets")
        await pilot.pause()
        app.screen.selected_wallet_id = wid
        app.screen.action_edit_wallet()
        await pilot.pause()

        form = app.screen
        form.query_one("#wallet-name", Input).value = "NewName"
        form.action_save()
        await pilot.pause()

        with app.state.session_factory() as session:
            assert session.get(Wallet, wid).name == "NewName"


async def test_archive_wallet(app_env) -> None:
    """Архивация выставляет archived=True и убирает кошелёк из активных."""
    app = WalletTrackerApp()
    async with app.run_test(size=(140, 40)) as pilot:
        with app.state.session_factory() as session:
            w = make_wallet(session, name="ToArchive")
            wid = w.id

        app.nav_to("wallets")
        await pilot.pause()
        app.screen.archive_selected_wallet(wid)
        await pilot.pause()

        with app.state.session_factory() as session:
            assert session.get(Wallet, wid).archived is True
