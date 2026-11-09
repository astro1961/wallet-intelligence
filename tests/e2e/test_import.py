"""E2E: импорт кошельков — preview и apply."""

from __future__ import annotations

import pytest
from textual.widgets import Label, TextArea

from app.application import WalletTrackerApp
from app.database.models import Wallet

pytestmark = pytest.mark.skip(reason="Import screen disabled (only Dashboard/Wallets)")

_IMPORT_TEXT = (
    "0xaaaabbbbccccddddeeeeffff000011112222aaa1\n"
    "0xbbbcccccddddeeeeffff0000111122223333bbb2\n"
)


async def test_import_preview_and_apply(app_env) -> None:
    """Preview считает новые адреса, apply создаёт кошельки."""
    app = WalletTrackerApp()
    async with app.run_test(size=(140, 40)) as pilot:
        app.nav_to("import")
        await pilot.pause()
        screen = app.screen

        screen.query_one("#import-text", TextArea).text = _IMPORT_TEXT
        await screen.do_preview()
        await pilot.pause()

        counts = screen.query_one("#counts-line", Label)
        assert "2 new" in str(counts.render())

        await screen.do_apply()
        await pilot.pause()

        with app.state.session_factory() as session:
            assert session.query(Wallet).count() == 2
