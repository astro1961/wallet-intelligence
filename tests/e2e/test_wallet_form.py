"""E2E: форма добавления кошелька (WalletFormScreen)."""

from __future__ import annotations

from textual.widgets import Input, Label

from app.application import WalletTrackerApp
from app.database.models import Wallet

_FORM_ADDR = "0xaaaabbbbccccddddeeeeffff000011112222333a"


async def _open_add_form(app, pilot):
    app.nav_to("wallets")
    await pilot.pause()
    app.screen.action_add_wallet()
    await pilot.pause()
    return app.screen


async def test_add_wallet_via_form(app_env) -> None:
    """Заполнение формы и сохранение создаёт кошелёк в БД."""
    app = WalletTrackerApp()
    async with app.run_test(size=(140, 40)) as pilot:
        form = await _open_add_form(app, pilot)
        form.query_one("#wallet-address", Input).value = _FORM_ADDR
        form.query_one("#wallet-name", Input).value = "FormWallet"
        form.action_save()
        await pilot.pause()

        with app.state.session_factory() as session:
            rows = session.query(Wallet).filter_by(address=_FORM_ADDR).all()
        assert len(rows) == 1
        assert rows[0].name == "FormWallet"


async def test_form_rejects_empty_address(app_env) -> None:
    """Пустой адрес → ошибка формы, кошелёк не создаётся."""
    app = WalletTrackerApp()
    async with app.run_test(size=(140, 40)) as pilot:
        form = await _open_add_form(app, pilot)
        form.action_save()
        await pilot.pause()

        err = form.query_one("#form-error", Label)
        assert "Address is required" in str(err.render())

        with app.state.session_factory() as session:
            assert session.query(Wallet).count() == 0
