"""Unit tests for Stage 5B: ProjectsScreen, catalog, filters, participation, creation."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.application import WalletTrackerApp
from app.core.project_manager import ProjectManager
from app.database.models import Activity, Base, Network, Wallet
from app.ui.screens.projects import ProjectsScreen


@pytest.fixture
def engine():
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture
def session_factory(engine):
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture
def session(session_factory) -> Session:
    with session_factory() as s:
        yield s


@pytest.fixture
def sample_network(session: Session) -> Network:
    net = Network(name="ethereum", chain_type="evm", chain_id=1, enabled=True)
    session.add(net)
    session.commit()
    return net


def test_empty_projects_screen(session_factory):
    """Empty DB produces empty-state text without traceback."""
    screen = ProjectsScreen(session_factory=session_factory)
    assert screen.projects_text == "No projects yet — press a to add one."
    assert screen.participation_text == ""


def test_catalog_listing_newest_first_and_row_format(session_factory, sample_network: Network):
    """Catalog lists projects newest first with correct row formatting."""
    with session_factory() as s:
        pm = ProjectManager(s)
        pm.create_project("Project Alpha", category="defi", status="active")
        p2 = pm.create_project("Project Beta", category="infrastructure", status="active")
        pm.create_project("Project Gamma", category=None, status="completed")

        # Contracts on p2
        pm.add_contract(p2.id, sample_network.name, "0x1111111111111111111111111111111111111111")
        # Task on p2
        pm.add_task(p2.id, "Audit contracts")

        s.commit()

    screen = ProjectsScreen(session_factory=session_factory)
    screen.refresh_data()
    lines = screen.projects_text.splitlines()

    assert len(lines) == 3
    # Newest first: Gamma, Beta, Alpha
    assert lines[0].startswith("Project Gamma · — · completed · 0 · 0 · 0/0")
    assert lines[1].startswith("Project Beta · infrastructure · active · 1 · 0 · 0/1")
    assert lines[2].startswith("Project Alpha · defi · active · 0 · 0 · 0/0")


def test_catalog_with_contracts_wallets_and_tasks(session_factory, sample_network: Network):
    """Catalog row reflects counters for contracts, wallets, and completed/total tasks."""
    with session_factory() as s:
        pm = ProjectManager(s)
        p = pm.create_project("Uniswap", category="dex", status="active")
        pm.add_contract(p.id, sample_network.name, "0x1f9840a85d5af5bf1d1762f925bdaddc4201f984")
        pm.add_contract(p.id, sample_network.name, "0x68b3465833fb72a70ecdf485e0e4c7bd8665fc45")

        w1 = Wallet(address="0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", name="Swapper")
        s.add(w1)
        s.flush()

        pm.link_wallet(p.id, w1.id, source="manual")
        t1 = pm.add_task(p.id, "Deploy router")
        pm.add_task(p.id, "Provide liquidity")
        pm.complete_task(t1.id)

        s.commit()

    screen = ProjectsScreen(session_factory=session_factory)
    screen.refresh_data()
    assert "Uniswap · dex · active · 2 · 1 · 1/2" in screen.projects_text


def test_status_filter_hides_and_restores(session_factory):
    """set_status_filter('active') hides completed; None restores all."""
    with session_factory() as s:
        pm = ProjectManager(s)
        pm.create_project("Active Project", status="active")
        pm.create_project("Finished Project", status="completed")
        s.commit()

    screen = ProjectsScreen(session_factory=session_factory)
    screen.refresh_data()
    assert "Active Project" in screen.projects_text
    assert "Finished Project" in screen.projects_text

    screen.set_status_filter("active")
    assert "Active Project" in screen.projects_text
    assert "Finished Project" not in screen.projects_text

    screen.set_status_filter(None)
    assert "Active Project" in screen.projects_text
    assert "Finished Project" in screen.projects_text

    screen.set_status_filter("completed")
    assert "Active Project" not in screen.projects_text
    assert "Finished Project" in screen.projects_text


def test_category_filter_narrows_and_restores(session_factory):
    """set_category_filter narrows to specific category; None restores all."""
    with session_factory() as s:
        pm = ProjectManager(s)
        pm.create_project("Aave", category="defi")
        pm.create_project("Arbitrum", category="layer2")
        s.commit()

    screen = ProjectsScreen(session_factory=session_factory)
    screen.refresh_data()
    assert "Aave" in screen.projects_text
    assert "Arbitrum" in screen.projects_text

    screen.set_category_filter("defi")
    assert "Aave" in screen.projects_text
    assert "Arbitrum" not in screen.projects_text

    screen.set_category_filter(None)
    assert "Aave" in screen.projects_text
    assert "Arbitrum" in screen.projects_text


def test_show_participation_panel(session_factory, sample_network: Network):
    """show_participation fills participation_text with wallet details and counters."""
    with session_factory() as s:
        pm = ProjectManager(s)
        p = pm.create_project("zkSync Era", category="layer2", status="active")

        w1 = Wallet(address="0x1111111111111111111111111111111111111111", name="AlphaWallet")
        w2 = Wallet(address="0x2222222222222222222222222222222222222222", name="BetaWallet")
        s.add_all([w1, w2])
        s.flush()

        # w1 has detected activities
        act = Activity(
            wallet_id=w1.id,
            network_id=sample_network.id,
            project_id=p.id,
            activity_type="contract_call",
            tx_hash="0xabcdef1234567890abcdef1234567890abcdef12",
            occurred_at=datetime(2026, 11, 4, 12, 0, tzinfo=UTC),
            status="confirmed",
            source="chain",
        )
        s.add(act)
        s.flush()

        # w2 is linked manually
        pm.link_wallet(p.id, w2.id, source="manual")

        # tasks
        t1 = pm.add_task(p.id, "Bridge funds", wallet_id=w1.id)
        pm.add_task(p.id, "Swap on SyncSwap", wallet_id=w1.id)
        pm.complete_task(t1.id)

        s.commit()
        project_id = p.id

    screen = ProjectsScreen(session_factory=session_factory)
    screen.show_participation(project_id)
    text = screen.participation_text

    assert "Project: zkSync Era (active)" in text
    assert "Wallets: 2  Tasks: 1/2  Interactions: 1" in text
    assert "- AlphaWallet (0x1111...1111) · source: detected · interactions: 1" in text
    assert "- BetaWallet (0x2222...2222) · source: manual · interactions: 0" in text


def test_show_participation_empty_wallets(session_factory):
    """show_participation handles project with no wallets or tasks."""
    with session_factory() as s:
        pm = ProjectManager(s)
        p = pm.create_project("Starknet", status="active")
        s.commit()
        project_id = p.id

    screen = ProjectsScreen(session_factory=session_factory)
    screen.show_participation(project_id)
    text = screen.participation_text

    assert "Project: Starknet (active)" in text
    assert "Wallets: 0  Tasks: 0/0  Interactions: 0" in text


def test_create_project_returns_id_and_updates_catalog(session_factory):
    """create_project inserts Project through ProjectManager and returns id."""
    screen = ProjectsScreen(session_factory=session_factory)
    p_id = screen.create_project("Scroll", category="layer2", status="active")
    assert p_id > 0
    assert "Scroll · layer2 · active · 0 · 0 · 0/0" in screen.projects_text


def test_create_project_duplicate_notification_no_crash(session_factory):
    """create_project with duplicate name surfaces notification instead of crashing."""
    screen = ProjectsScreen(session_factory=session_factory)
    p1_id = screen.create_project("Optimism", category="layer2", status="active")
    assert p1_id > 0

    # Duplicate name (case-insensitive) must not crash
    p2_id = screen.create_project("optimism", category="layer2", status="active")
    assert p2_id <= 0

    # Only one project should exist
    lines = [line for line in screen.projects_text.splitlines() if "Optimism" in line or "optimism" in line]
    assert len(lines) == 1


@pytest.mark.asyncio
async def test_projects_screen_tui_interactive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """TUI interactive test: switch to screen 4, check empty state, create project."""
    db_file = tmp_path / "test_projects_tui.db"
    monkeypatch.setenv("WIT_DB_PATH", str(db_file))

    app = WalletTrackerApp()
    async with app.run_test(size=(120, 35)) as pilot:
        # Switch to projects screen
        await pilot.press("4")
        await pilot.pause()

        assert isinstance(app.screen, ProjectsScreen)
        assert app.screen.id == "projects"
        assert "No projects yet — press a to add one." in app.screen.projects_text

        # Create project programmatically
        new_id = app.screen.create_project("Base", category="layer2", status="active")
        assert new_id > 0
        await pilot.pause()

        assert "Base · layer2 · active · 0 · 0 · 0/0" in app.screen.projects_text

        # Duplicate does not crash the app
        dup_id = app.screen.create_project("base", category="layer2", status="active")
        assert dup_id <= 0
        await pilot.pause()

        # Show participation
        app.screen.show_participation(new_id)
        assert "Project: Base (active)" in app.screen.participation_text


@pytest.mark.asyncio
async def test_projects_screen_modal_add_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Test pressing 'a' opens ProjectCreateModal and creates a project."""
    db_file = tmp_path / "test_projects_modal.db"
    monkeypatch.setenv("WIT_DB_PATH", str(db_file))

    from textual.widgets import Input

    from app.ui.screens.projects import ProjectCreateModal

    app = WalletTrackerApp()
    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.press("4")
        await pilot.pause()
        assert isinstance(app.screen, ProjectsScreen)

        # Press 'a' to open modal
        await pilot.press("a")
        await pilot.pause()
        assert isinstance(app.screen, ProjectCreateModal)

        # Fill in project name
        name_input = app.screen.query_one("#project-name-input", Input)
        name_input.value = "Polygon"
        await pilot.click("#create-project-btn")
        await pilot.pause()

        # Modal dismissed, back on ProjectsScreen
        assert isinstance(app.screen, ProjectsScreen)
        assert "Polygon" in app.screen.projects_text

