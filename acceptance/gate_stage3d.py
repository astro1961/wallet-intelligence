"""Independent acceptance gate — Stage 3D (wallet details follow the table cursor).

Owned by Hermes. Offline (Textual pilot + tmp DB).

Run from the project root:
    env -u WIT_DB_PATH .venv/bin/python -m pytest acceptance/gate_stage3d.py -q
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def seed_db() -> dict:
    from app.config import load_config
    from app.core.wallet_manager import WalletManager
    from app.database.session import init_db, session_factory, session_scope

    engine = init_db(load_config())
    with session_scope(session_factory(engine)) as s:
        wm = WalletManager(s)
        a = wm.create_wallet(address="0xfb6916095ca1df60bb79ce92ce3ea74c37c5d359", name="Alpha")
        b = wm.create_wallet(address="0xfb6916095ca1df60bb79ce92ce3ea74c37c5d35a", name="Beta")
        wm.update_wallet(b.id, notes="Beta has a distinctive note 42")
        return {"alpha": a.id, "beta": b.id}


@pytest.fixture(autouse=True)
def _db(tmp_path, monkeypatch):
    monkeypatch.setenv("WIT_DB_PATH", str(tmp_path / "tui3d.db"))


def _app():
    from app.application import WalletTrackerApp

    return WalletTrackerApp()


@pytest.mark.asyncio
async def test_details_follow_cursor_without_enter():
    """Highlighting a row must update the details panel; Enter is not required."""
    ids = seed_db()
    app = _app()
    async with app.run_test(size=(140, 45)) as pilot:
        await pilot.press("2")
        await pilot.pause()
        screen = app.screen
        screen.refresh_data()
        await pilot.pause()

        table = screen.query_one("#wallet-table")
        details = screen.query_one("#wallet-details")

        table.move_cursor(row=0)
        await pilot.pause()
        first = str(getattr(details, "renderable", details.render()))
        assert "Alpha" in first, f"cursor on row 0 but details show: {first[:200]}"

        table.move_cursor(row=1)
        await pilot.pause()
        second = str(getattr(details, "renderable", details.render()))
        assert "Beta" in second, (
            "details panel did not follow the cursor — it still shows the previous wallet "
            f"(row 1 highlighted, panel: {second[:200]})"
        )
        assert "Alpha" not in second.split("Beta")[0][-40:], "details still carry the old wallet"


@pytest.mark.asyncio
async def test_enter_still_opens_full_history():
    ids = seed_db()
    app = _app()
    async with app.run_test(size=(140, 45)) as pilot:
        await pilot.press("2")
        await pilot.pause()
        screen = app.screen
        screen.refresh_data()
        await pilot.pause()

        table = screen.query_one("#wallet-table")
        table.move_cursor(row=1)
        await pilot.pause()
        table.focus()
        await pilot.press("enter")
        await pilot.pause()

        text = screen.history_text
        assert "Beta" in text, f"Enter no longer fills the history: {text[:200]}"


@pytest.mark.asyncio
async def test_details_do_not_crash_without_rows():
    app = _app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("2")
        await pilot.pause()
        screen = app.screen
        table = screen.query_one("#wallet-table")
        assert table.row_count == 0
        table.move_cursor(row=0)
        await pilot.pause()
        details = screen.query_one("#wallet-details")
        text = str(getattr(details, "renderable", ""))
        assert "Traceback" not in text
