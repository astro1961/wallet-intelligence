"""Unit tests for Import screen in Textual TUI."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from textual.widgets import Button, DataTable, Label

from app.application import WalletTrackerApp
from app.database.models import Wallet
from app.database.session import session_scope

CSV_DATA = (
    "address,name,group,network,tags\n"
    "0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed,Valid1,Mining,ethereum,gpu\n"
    "0xINVALID_ADDRESS,Invalid1,Mining,ethereum,gpu\n"
    "0xfB6916095ca1df60bB79Ce92cE3Ea74c37c5d359,Valid2,Staking,arbitrum,pos\n"
)


@pytest.fixture(autouse=True)
def _test_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WIT_DB_PATH", str(tmp_path / "import_test.db"))


@pytest.mark.asyncio
async def test_import_preview_does_not_write_to_db() -> None:
    app = WalletTrackerApp()
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.press("8")
        await pilot.pause()
        screen = app.screen
        assert screen.id == "import"

        screen.set_text(CSV_DATA)
        await pilot.pause()
        await screen.do_preview()
        await pilot.pause()

        with session_scope(app.state.session_factory) as s:
            assert s.query(Wallet).count() == 0


@pytest.mark.asyncio
async def test_import_csv_preview_and_apply() -> None:
    app = WalletTrackerApp()
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.press("8")
        await pilot.pause()
        screen = app.screen

        screen.set_text(CSV_DATA)
        await pilot.pause()
        await screen.do_preview()
        await pilot.pause()

        table = screen.query_one("#preview-table", DataTable)
        assert len(table.rows) == 3

        # Counts line
        counts_lbl = screen.query_one("#counts-line", Label)
        assert "2 new" in str(counts_lbl.render())
        assert "1 errors" in str(counts_lbl.render())

        # Apply
        await screen.do_apply()
        await pilot.pause()

        with session_scope(app.state.session_factory) as s:
            assert s.query(Wallet).count() == 2

        report_lbl = screen.query_one("#report-line", Label)
        assert "Added: 2" in str(report_lbl.render())


@pytest.mark.asyncio
async def test_import_json_preview_and_apply() -> None:
    json_data = json.dumps([
        {"address": "0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed", "name": "Json1", "tags": "hot,main"},
        {"address": "0xfB6916095ca1df60bB79Ce92cE3Ea74c37c5d359", "name": "Json2", "tags": "cold"},
    ])
    app = WalletTrackerApp()
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.press("8")
        await pilot.pause()
        screen = app.screen

        screen.set_text(json_data)
        await pilot.pause()
        await screen.do_preview()
        await pilot.pause()

        table = screen.query_one("#preview-table", DataTable)
        assert len(table.rows) == 2

        await screen.do_apply()
        await pilot.pause()

        with session_scope(app.state.session_factory) as s:
            assert s.query(Wallet).count() == 2


@pytest.mark.asyncio
async def test_large_paste_worker_execution() -> None:
    """Pastes >= 2000 rows run in background worker and preview completes cleanly."""
    lines = ["address,name,tags"]
    for i in range(2005):
        lines.append(f"0x{'a' * 40},w_{i},batch")
    large_csv = "\n".join(lines)

    app = WalletTrackerApp()
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.press("8")
        await pilot.pause()
        screen = app.screen

        screen.set_text(large_csv)
        await pilot.pause()
        await screen.do_preview()
        await pilot.pause()

        table = screen.query_one("#preview-table", DataTable)
        assert len(table.rows) == 2005
        btn = screen.query_one("#preview-btn", Button)
        assert "Preview" in str(btn.label)
