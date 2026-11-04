"""Independent acceptance gate — Stage 2B (wallets/groups/import wired into the TUI).

Owned by Hermes. Pinned in docs/DEVLOG.md; the build agent must not edit it.

Run from the project root:
    env -u WIT_DB_PATH .venv/bin/python -m pytest acceptance/gate_stage2b.py -q
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

def seed_db() -> dict:
    """Seed three wallets; returns ids and the row count."""
    from app.config import load_config
    from app.database.models import Wallet
    from app.database.session import init_db, session_factory, session_scope
    from app.core.group_manager import GroupManager
    from app.core.wallet_manager import WalletManager

    engine = init_db(load_config())
    with session_scope(session_factory(engine)) as s:
        g, w = GroupManager(s), WalletManager(s)
        farm = g.create_group("Farm")
        sub = g.create_group("Farm #1", farm.id)
        g.create_group("Exchanges")
        w.create_wallet(address="0xfb6916095ca1df60bb79ce92ce3ea74c37c5d359", name="Alpha",
                        group_id=farm.id, tags=["hot"])
        b = w.create_wallet(address="0xfb6916095ca1df60bb79ce92ce3ea74c37c5d35a", name="Beta",
                            group_id=sub.id, tags=["cold"])
        w.create_wallet(address="0xfb6916095ca1df60bb79ce92ce3ea74c37c5d35b", name="Gamma")
        w.update_wallet(b.id, notes="updated in gate")
        return {"farm": farm.id, "sub": sub.id, "beta": b.id, "count": s.query(Wallet).count()}


CSV = (
    "address,name,group,network,tags\n"
    "0xfb6916095ca1df60bb79ce92ce3ea74c37c5d359,Wallet001,Farm #1,ethereum,farming\n"
    "0xBROKEN,Wallet002,Farm #1,ethereum,farming\n"
    "0xfb6916095ca1df60bb79ce92ce3ea74c37c5d35a,Wallet003,Farm #2,arbitrum,cold\n"
)


@pytest.fixture(autouse=True)
def _db(tmp_path, monkeypatch):
    monkeypatch.setenv("WIT_DB_PATH", str(tmp_path / "tui2b.db"))


def _app():
    from app.application import WalletTrackerApp
    return WalletTrackerApp()


@pytest.mark.asyncio
async def test_wallets_screen_mounts_tree_and_table():
    from textual.widgets import DataTable, Tree
    app = _app()
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.press("2")
        await pilot.pause()
        screen = app.screen
        assert screen.query(Tree) or screen.query_one("#group-tree"), "no group tree on Wallets"
        assert screen.query(DataTable), "no textual DataTable on Wallets"
        assert screen.query_one("#wallet-table") is not None


@pytest.mark.asyncio
async def test_wallets_table_shows_seeded_rows_and_group_filter():
    from textual.widgets import DataTable
    app = _app()
    async with app.run_test(size=(140, 40)) as pilot:
        ids = seed_db()
        await pilot.press("2")
        await pilot.pause()
        screen = app.screen
        screen.refresh_data()
        await pilot.pause()
        table = screen.query_one("#wallet-table", DataTable)
        assert len(table.rows) == ids["count"] == 3, f"table rows {len(table.rows)} != 3"
        screen.set_group_filter(ids["farm"])
        await pilot.pause()
        assert len(table.rows) == 2, f"group filter must include subgroups: {len(table.rows)}"
        screen.set_group_filter(None)
        await pilot.pause()
        assert len(table.rows) == 3


@pytest.mark.asyncio
async def test_add_wallet_modal_opens_saves_and_refreshes():
    from textual.screen import ModalScreen
    from textual.widgets import DataTable
    app = _app()
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.press("2")
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()
        assert isinstance(app.screen, ModalScreen), "pressing 'a' must open a modal form"
        modal = app.screen
        new_id = modal.save_wallet({
            "address": "0xfb6916095ca1df60bb79ce92ce3ea74c37c5d359",
            "name": "FromModal",
            "chain_type": "evm",
        })
        await pilot.press("escape")
        await pilot.pause()
        assert app.screen.id == "wallets", "Esc must return to the wallets screen"
        table = app.screen.query_one("#wallet-table", DataTable)
        assert len(table.rows) == 1, f"table not refreshed after save: {len(table.rows)}"
        assert new_id is not None


@pytest.mark.asyncio
async def test_wallet_history_panel_after_edit():
    app = _app()
    async with app.run_test(size=(140, 40)) as pilot:
        ids = seed_db()
        await pilot.press("2")
        await pilot.pause()
        screen = app.screen
        screen.show_history(ids["beta"])
        await pilot.pause()
        text = getattr(screen, "history_text", "") or ""
        assert re.search(r"notes|updated in gate|audit|история", text, re.I), \
            f"history panel does not show the audit entry (history_text={text!r})"


@pytest.mark.asyncio
async def test_import_screen_preview_then_apply():
    from textual.widgets import DataTable
    app = _app()
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.press("8")
        await pilot.pause()
        screen = app.screen
        assert app.screen.id == "import"
        screen.set_text(CSV)
        await pilot.pause()
        await screen.do_preview()
        await pilot.pause()
        tables = screen.query(DataTable)
        assert tables, "preview table not rendered"
        rows = max(len(t.rows) for t in tables)
        assert rows >= 3, f"preview must list every input row, got {rows}"
        from app.database.models import Wallet
        from app.database.session import init_db, session_factory, session_scope
        from app.config import load_config
        engine = init_db(load_config())
        with session_scope(session_factory(engine)) as s:
            assert s.query(Wallet).count() == 0, "preview must not write to the DB"
        await screen.do_apply()
        await pilot.pause()
        with session_scope(session_factory(engine)) as s:
            assert s.query(Wallet).count() == 2, "apply must insert the two valid rows"


@pytest.mark.asyncio
async def test_empty_state_text_and_resize():
    app = _app()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.press("2")
        await pilot.pause()
        src = (ROOT / "app" / "ui" / "screens" / "wallets.py").read_text(encoding="utf-8")
        assert re.search(r"пока нет|No wallets|Add your first|Добавьте", src, re.I), \
            "no human empty state in the wallets screen"
        await pilot.resize_terminal(60, 20)
        await pilot.pause()
        await pilot.resize_terminal(140, 40)
        await pilot.pause()


def test_ui_layer_still_offline():
    offenders = []
    for p in (ROOT / "app" / "ui").rglob("*.py"):
        t = p.read_text(encoding="utf-8")
        if re.search(r"\b(httpx|requests|aiohttp)\b", t):
            offenders.append(p.name)
    assert not offenders, f"UI must not talk to network yet: {offenders}"
