"""Unit tests for Stage 5C: cursor synchronization and neutral filter reset."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from textual.widgets import DataTable

from app.application import WalletTrackerApp
from app.config import load_config
from app.core.project_manager import ProjectManager
from app.database.models import Base, Wallet
from app.state import AppState
from app.ui.screens.projects import ProjectsScreen


def create_test_app() -> tuple[WalletTrackerApp, int, int]:
    """Create test application with in-memory SQLite and two sample projects."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_fact = sessionmaker(bind=engine, expire_on_commit=False)

    with session_fact() as s:
        w = Wallet(address="0xd8da6bf26964af9d7eed9e03e53415d37aa96045", name="vitalik")
        s.add(w)
        s.flush()
        pm = ProjectManager(s)
        # First created: Arbitrum Odyssey (id=1, status='active')
        p1 = pm.create_project(name="Arbitrum Odyssey", category="airdrop", status="active")
        # Second created: LayerZero (id=2, status='completed')
        p2 = pm.create_project(name="LayerZero", category="bridge", status="completed")
        pm.link_wallet(p1.id, w.id, source="manual")
        pm.add_task(p1.id, title="Bridge", wallet_id=w.id, status="done")
        s.commit()
        p1_id, p2_id = p1.id, p2.id

    cfg = load_config()
    state = AppState(config=cfg, engine=engine, session_factory=session_fact)
    app = WalletTrackerApp(state=state)
    return app, p1_id, p2_id


@pytest.mark.asyncio
async def test_show_participation_second_row_not_overwritten():
    """1. show_participation(project_id_of_second_row) -> panel shows that project after a pause."""
    app, p1_id, p2_id = create_test_app()
    async with app.run_test(size=(140, 45)) as pilot:
        await pilot.press("4")
        await pilot.pause()

        assert isinstance(app.screen, ProjectsScreen)
        table = app.screen.query_one("#projects-table", DataTable)

        # In newest_first catalog listing:
        # Row 0 is LayerZero (p2_id)
        # Row 1 (second row) is Arbitrum Odyssey (p1_id)
        assert table.cursor_row == 0

        # Explicitly call show_participation for the second row's project
        app.screen.show_participation(p1_id)
        await pilot.pause()

        # The panel must not be overwritten by cursor highlight event; table cursor moves to row 1
        assert "Arbitrum Odyssey" in app.screen.participation_text
        assert "LayerZero" not in app.screen.participation_text
        assert table.cursor_row == 1


@pytest.mark.asyncio
async def test_table_move_cursor_follows_again():
    """2. table.move_cursor(0) afterwards -> panel follows the cursor again."""
    app, p1_id, p2_id = create_test_app()
    async with app.run_test(size=(140, 45)) as pilot:
        await pilot.press("4")
        await pilot.pause()

        assert isinstance(app.screen, ProjectsScreen)
        table = app.screen.query_one("#projects-table", DataTable)

        # First move to second row
        app.screen.show_participation(p1_id)
        await pilot.pause()
        assert "Arbitrum Odyssey" in app.screen.participation_text

        # Now move cursor back to row 0
        table.move_cursor(row=0)
        await pilot.pause()

        # Panel follows the cursor back to LayerZero
        assert "LayerZero" in app.screen.participation_text
        assert "Arbitrum Odyssey" not in app.screen.participation_text
        assert table.cursor_row == 0


@pytest.mark.asyncio
async def test_filter_hiding_selected_project_resets_to_neutral_placeholder():
    """3. Filter that hides the selected project -> panel shows a neutral placeholder, not stale data."""
    app, p1_id, p2_id = create_test_app()
    async with app.run_test(size=(140, 45)) as pilot:
        await pilot.press("4")
        await pilot.pause()

        assert isinstance(app.screen, ProjectsScreen)

        # Select LayerZero (status='completed')
        app.screen.show_participation(p2_id)
        await pilot.pause()
        assert "LayerZero" in app.screen.participation_text

        # Filter by status='active', which hides LayerZero
        app.screen.set_status_filter("active")
        await pilot.pause()

        # Panel must be reset to neutral empty placeholder, not retain stale LayerZero data
        assert "LayerZero" not in app.screen.participation_text
        assert app.screen.participation_text == ""
        assert app.screen.selected_project_id is None

        # Filter by status='archived' (matching nothing) also keeps neutral empty placeholder without traceback
        app.screen.set_status_filter("archived")
        await pilot.pause()
        assert app.screen.participation_text == ""
        assert app.screen.selected_project_id is None
        assert "No projects yet — press a to add one." in app.screen.projects_text
