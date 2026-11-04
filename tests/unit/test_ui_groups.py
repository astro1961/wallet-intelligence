"""Unit tests for group operations from the Wallets screen tree."""
from __future__ import annotations

from pathlib import Path

import pytest
from textual.widgets import Tree

from app.application import WalletTrackerApp
from app.core.group_manager import GroupManager
from app.core.wallet_manager import WalletManager
from app.database.models import Wallet, WalletGroup
from app.database.session import session_scope


@pytest.fixture(autouse=True)
def _test_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WIT_DB_PATH", str(tmp_path / "groups_test.db"))


@pytest.mark.asyncio
async def test_group_tree_hierarchy_and_unassigned() -> None:
    app = WalletTrackerApp()
    async with app.run_test(size=(140, 40)) as pilot:
        with session_scope(app.state.session_factory) as s:
            gm = GroupManager(s)
            p = gm.create_group("ParentGroup")
            gm.create_group("ChildGroup", parent_id=p.id)

        await pilot.press("2")
        await pilot.pause()
        screen = app.screen
        screen.refresh_data()
        await pilot.pause()

        tree = screen.query_one("#group-tree", Tree)
        labels = [str(node.label) for node in tree.root.children]
        assert any("ParentGroup" in l for l in labels)
        assert any("Unassigned" in l for l in labels)


@pytest.mark.asyncio
async def test_group_create_action() -> None:
    app = WalletTrackerApp()
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.press("2")
        await pilot.pause()
        screen = app.screen

        screen.create_group_action("NewGroup", parent_id=None)
        await pilot.pause()

        with session_scope(app.state.session_factory) as s:
            grp = s.query(WalletGroup).filter_by(name="NewGroup").first()
            assert grp is not None


@pytest.mark.asyncio
async def test_group_rename_action() -> None:
    app = WalletTrackerApp()
    async with app.run_test(size=(140, 40)) as pilot:
        with session_scope(app.state.session_factory) as s:
            gm = GroupManager(s)
            g = gm.create_group("OldName")
            gid = g.id

        await pilot.press("2")
        await pilot.pause()
        screen = app.screen

        screen.rename_group_action(gid, "RenamedGroup")
        await pilot.pause()

        with session_scope(app.state.session_factory) as s:
            grp = s.get(WalletGroup, gid)
            assert grp.name == "RenamedGroup"


@pytest.mark.asyncio
async def test_group_move_action() -> None:
    app = WalletTrackerApp()
    async with app.run_test(size=(140, 40)) as pilot:
        with session_scope(app.state.session_factory) as s:
            gm = GroupManager(s)
            p1 = gm.create_group("Parent1")
            p2 = gm.create_group("Parent2")
            c = gm.create_group("Child", parent_id=p1.id)
            cid, p2id = c.id, p2.id

        await pilot.press("2")
        await pilot.pause()
        screen = app.screen

        screen.move_group_action(cid, p2id)
        await pilot.pause()

        with session_scope(app.state.session_factory) as s:
            grp = s.get(WalletGroup, cid)
            assert grp.parent_id == p2id


@pytest.mark.asyncio
async def test_group_delete_preserves_wallets() -> None:
    app = WalletTrackerApp()
    async with app.run_test(size=(140, 40)) as pilot:
        with session_scope(app.state.session_factory) as s:
            gm = GroupManager(s)
            wm = WalletManager(s)
            g = gm.create_group("ToDelete")
            w = wm.create_wallet(
                address="0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed",
                name="SafeWallet",
                group_id=g.id,
            )
            gid, wid = g.id, w.id

        await pilot.press("2")
        await pilot.pause()
        screen = app.screen

        screen.delete_group_action(gid, reassign_to=None)
        await pilot.pause()

        with session_scope(app.state.session_factory) as s:
            assert s.get(WalletGroup, gid) is None
            wallet = s.get(Wallet, wid)
            assert wallet is not None
            assert wallet.group_id is None
