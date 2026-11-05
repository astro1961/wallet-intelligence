"""Unit tests for Wallets screen in Textual TUI."""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from textual.screen import ModalScreen
from textual.widgets import DataTable, Tree

from app.application import WalletTrackerApp
from app.core.group_manager import GroupManager
from app.core.wallet_manager import WalletManager
from app.database.models import Wallet
from app.database.session import session_scope


def seed_test_wallets(app: WalletTrackerApp) -> dict:
    """Seed sample groups and wallets into the app's database."""
    with session_scope(app.state.session_factory) as s:
        gm = GroupManager(s)
        wm = WalletManager(s)
        farm = gm.create_group("Farm")
        sub = gm.create_group("SubFarm", parent_id=farm.id)
        trading = gm.create_group("Trading")

        w1 = wm.create_wallet(
            address="0x1111111111111111111111111111111111111111",
            name="Alpha",
            group_id=farm.id,
            tags=["defi", "main"],
            notes="Alpha notes",
        )
        w2 = wm.create_wallet(
            address="0x2222222222222222222222222222222222222222",
            name="Beta",
            group_id=sub.id,
            tags=["airdrop"],
            notes="Beta notes",
        )
        w3 = wm.create_wallet(
            address="0x3333333333333333333333333333333333333333",
            name="Gamma",
            group_id=None,
            tags=[],
        )
        wm.update_wallet(w2.id, notes="Beta updated notes")
        return {
            "farm": farm.id,
            "sub": sub.id,
            "trading": trading.id,
            "w1": w1.id,
            "w2": w2.id,
            "w3": w3.id,
        }


@pytest.fixture(autouse=True)
def _test_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WIT_DB_PATH", str(tmp_path / "wallets_test.db"))


@pytest.mark.asyncio
async def test_wallets_screen_structure_and_empty_state() -> None:
    app = WalletTrackerApp()
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.press("2")
        await pilot.pause()
        screen = app.screen
        assert screen.id == "wallets"
        assert screen.query(Tree) or screen.query_one("#group-tree")
        table = screen.query_one("#wallet-table", DataTable)
        assert table is not None
        assert len(table.rows) == 0

        # Check empty state message exists
        assert screen.query_one("#empty-state") is not None


@pytest.mark.asyncio
async def test_wallets_table_rendering_and_group_filter() -> None:
    app = WalletTrackerApp()
    async with app.run_test(size=(140, 40)) as pilot:
        ids = seed_test_wallets(app)
        await pilot.press("2")
        await pilot.pause()
        screen = app.screen
        screen.refresh_data()
        await pilot.pause()

        table = screen.query_one("#wallet-table", DataTable)
        assert len(table.rows) == 3

        # Filter by root group 'Farm' (must include 'SubFarm' -> 2 wallets)
        screen.set_group_filter(ids["farm"])
        await pilot.pause()
        assert len(table.rows) == 2

        # Filter by subgroup 'SubFarm' (1 wallet)
        screen.set_group_filter(ids["sub"])
        await pilot.pause()
        assert len(table.rows) == 1

        # Clear filter
        screen.set_group_filter(None)
        await pilot.pause()
        assert len(table.rows) == 3


@pytest.mark.asyncio
async def test_wallets_search_filter() -> None:
    app = WalletTrackerApp()
    async with app.run_test(size=(140, 40)) as pilot:
        seed_test_wallets(app)
        await pilot.press("2")
        await pilot.pause()
        screen = app.screen
        screen.refresh_data()
        await pilot.pause()

        table = screen.query_one("#wallet-table", DataTable)
        assert len(table.rows) == 3

        # Press '/' to focus search input
        await pilot.press("slash")
        await pilot.pause()
        search_input = screen.query_one("#wallet-search")
        assert search_input.has_focus

        # Search by tag 'airdrop'
        search_input.value = "airdrop"
        await pilot.pause(0.3)
        assert len(table.rows) == 1

        # Clear search
        search_input.value = ""
        await pilot.pause(0.3)
        assert len(table.rows) == 3


@pytest.mark.asyncio
async def test_wallet_form_modal_create_and_validation() -> None:
    app = WalletTrackerApp()
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.press("2")
        await pilot.pause()

        # Press 'a' to open Add Wallet modal
        await pilot.press("a")
        await pilot.pause()
        assert isinstance(app.screen, ModalScreen)
        modal = app.screen

        # Programmatic save_wallet check
        new_id = modal.save_wallet({
            "address": "0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed",
            "name": "NewWallet",
            "chain_type": "evm",
            "tags": ["test"],
        })
        assert new_id > 0

        # Close modal with Esc
        await pilot.press("escape")
        await pilot.pause()
        assert app.screen.id == "wallets"

        # Table refreshed
        table = app.screen.query_one("#wallet-table", DataTable)
        assert len(table.rows) == 1


@pytest.mark.asyncio
async def test_wallet_history_panel_shows_audit_entries() -> None:
    app = WalletTrackerApp()
    async with app.run_test(size=(140, 40)) as pilot:
        ids = seed_test_wallets(app)
        await pilot.press("2")
        await pilot.pause()
        screen = app.screen

        screen.show_history(ids["w2"])
        await pilot.pause()

        assert hasattr(screen, "history_text")
        text = screen.history_text
        assert "Beta updated notes" in text
        assert re.search(r"notes|audit|история", text, re.IGNORECASE)


@pytest.mark.asyncio
async def test_archive_wallet_flow() -> None:
    app = WalletTrackerApp()
    async with app.run_test(size=(140, 40)) as pilot:
        ids = seed_test_wallets(app)
        await pilot.press("2")
        await pilot.pause()
        screen = app.screen
        screen.refresh_data()
        await pilot.pause()

        table = screen.query_one("#wallet-table", DataTable)
        assert len(table.rows) == 3

        # Trigger archive on first row
        screen.archive_selected_wallet(ids["w1"])
        await pilot.pause()

        # Table refreshed, active wallets is now 2
        assert len(table.rows) == 2
        with session_scope(app.state.session_factory) as s:
            w = s.get(Wallet, ids["w1"])
            assert w.archived is True


@pytest.mark.asyncio
async def test_cursor_move_to_row_0_updates_details() -> None:
    """move_cursor(0) -> panel contains the first wallet's name/address."""
    app = WalletTrackerApp()
    async with app.run_test(size=(140, 45)) as pilot:
        seed_test_wallets(app)
        await pilot.press("2")
        await pilot.pause()
        screen = app.screen
        screen.refresh_data()
        await pilot.pause()

        table = screen.query_one("#wallet-table", DataTable)
        details = screen.query_one("#wallet-details")

        table.move_cursor(row=0)
        await pilot.pause()
        content = str(getattr(details, "renderable", details.render()))
        assert "Alpha" in content
        assert "0x1111111111111111111111111111111111111111" in content


@pytest.mark.asyncio
async def test_cursor_move_to_row_1_updates_details_and_clears_first() -> None:
    """move_cursor(1) -> panel contains the second wallet's name/address and no longer the first."""
    app = WalletTrackerApp()
    async with app.run_test(size=(140, 45)) as pilot:
        seed_test_wallets(app)
        await pilot.press("2")
        await pilot.pause()
        screen = app.screen
        screen.refresh_data()
        await pilot.pause()

        table = screen.query_one("#wallet-table", DataTable)
        details = screen.query_one("#wallet-details")

        table.move_cursor(row=0)
        await pilot.pause()
        first = str(getattr(details, "renderable", details.render()))
        assert "Alpha" in first

        table.move_cursor(row=1)
        await pilot.pause()
        second = str(getattr(details, "renderable", details.render()))
        assert "Beta" in second
        assert "Alpha" not in second


@pytest.mark.asyncio
async def test_press_enter_on_row_fills_history_text() -> None:
    """press('enter') on a row -> history_text is filled (regression guard)."""
    app = WalletTrackerApp()
    async with app.run_test(size=(140, 45)) as pilot:
        seed_test_wallets(app)
        await pilot.press("2")
        await pilot.pause()
        screen = app.screen
        screen.refresh_data()
        await pilot.pause()

        table = screen.query_one("#wallet-table", DataTable)
        table.move_cursor(row=1)
        await pilot.pause()
        table.focus()
        await pilot.press("enter")
        await pilot.pause()

        assert hasattr(screen, "history_text")
        assert "Beta" in screen.history_text
        assert "Beta updated notes" in screen.history_text


@pytest.mark.asyncio
async def test_empty_table_keeps_placeholder_without_traceback() -> None:
    """Empty table -> panel keeps the placeholder, no traceback."""
    app = WalletTrackerApp()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("2")
        await pilot.pause()
        screen = app.screen
        table = screen.query_one("#wallet-table", DataTable)
        assert len(table.rows) == 0
        table.move_cursor(row=0)
        await pilot.pause()

        details = screen.query_one("#wallet-details")
        text = str(getattr(details, "renderable", details.render()))
        assert "Select a wallet and press Enter to view details and audit history." in text
        assert "Traceback" not in text

