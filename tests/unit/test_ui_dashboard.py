"""Unit tests for Dashboard screen (netwatch style dense monitoring TUI)."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from app.database.models import (
    Activity,
    BalanceSnapshot,
    DeFiPosition,
    Network,
    Project,
    SyncJob,
    Wallet,
)
from app.database.repository import GroupRepository, WalletRepository


@pytest.mark.asyncio
async def test_dashboard_counters_fresh_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Requirement 7: dashboard counters are 0 on a fresh database."""
    db_file = tmp_path / "fresh_dashboard.db"
    monkeypatch.setenv("WIT_DB_PATH", str(db_file))

    from app.application import WalletTrackerApp

    app = WalletTrackerApp()
    async with app.run_test(size=(120, 35)):
        assert app.screen.id == "dashboard"
        counters = app.screen.get_counters()
        assert counters["wallets"] == 0
        assert counters["groups"] == 0
        assert counters["projects"] == 0
        assert counters["activities"] == 0
        # Networks from config.yaml
        assert counters["networks"] >= 0


@pytest.mark.asyncio
async def test_dashboard_counters_seeded_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Requirement 7: counters match inserted rows when seeded through repository."""
    db_file = tmp_path / "seeded_dashboard.db"
    monkeypatch.setenv("WIT_DB_PATH", str(db_file))

    from app.application import WalletTrackerApp

    app = WalletTrackerApp()

    # Seed DB directly using repositories / session
    assert app.state.session_factory is not None
    with app.state.session_factory() as session:
        wallet_repo = WalletRepository(session)
        group_repo = GroupRepository(session)

        # Insert 1 network
        net = Network(name="Ethereum Mainnet", chain_type="evm", chain_id=1)
        session.add(net)
        session.flush()

        # Insert 2 groups
        g1 = group_repo.create(name="Personal")
        g2 = group_repo.create(name="Farming")

        # Insert 3 wallets
        w1 = wallet_repo.add(address="0x1111111111111111111111111111111111111111", chain_type="evm", group_id=g1.id)
        wallet_repo.add(address="0x2222222222222222222222222222222222222222", chain_type="evm", group_id=g2.id)
        wallet_repo.add(address="0x3333333333333333333333333333333333333333", chain_type="evm")

        # Insert 1 project
        proj = Project(name="TestNetAlpha", description="Testnet Alpha Project")
        session.add(proj)

        # Insert 1 activity
        act = Activity(
            wallet_id=w1.id,
            network_id=net.id,
            activity_type="tx",
            occurred_at=datetime.now(UTC),
            status="confirmed",
            source="manual",
        )
        session.add(act)

        session.commit()

    async with app.run_test(size=(120, 35)):
        assert app.screen.id == "dashboard"
        # Refresh counters on screen
        app.screen.refresh_counters()
        counters = app.screen.get_counters()
        assert counters["wallets"] == 3
        assert counters["groups"] == 2
        assert counters["projects"] == 1
        assert counters["activities"] == 1


@pytest.mark.asyncio
async def test_dashboard_netwatch_panels_structure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Dashboard netwatch layout has 4 panels and bottom status line."""
    db_file = tmp_path / "structure_dashboard.db"
    monkeypatch.setenv("WIT_DB_PATH", str(db_file))

    from app.application import WalletTrackerApp

    app = WalletTrackerApp()
    async with app.run_test(size=(120, 35)):
        screen = app.screen
        assert screen.id == "dashboard"

        # Check required panels
        p1 = screen.query_one("#panel-metrics")
        assert p1 is not None
        p2 = screen.query_one("#panel-wallets")
        assert p2 is not None
        p3 = screen.query_one("#panel-activity")
        assert p3 is not None
        p4 = screen.query_one("#panel-trend")
        assert p4 is not None

        # Bottom status line
        status_line = screen.query_one("#dashboard-status-line")
        assert status_line is not None

        # Base empty states compatibility elements
        assert screen.query_one(".screen-title") is not None
        assert screen.query_one(".screen-desc") is not None
        assert screen.query_one(".screen-stage") is not None


@pytest.mark.asyncio
async def test_dashboard_metrics_big_numbers_and_changes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Panel 1: big numbers for TOTAL BALANCE, WALLETS, TRACKED TX, DEFI POS, LAST SYNC + ▲/▼ badge."""
    db_file = tmp_path / "metrics_dashboard.db"
    monkeypatch.setenv("WIT_DB_PATH", str(db_file))

    from app.application import WalletTrackerApp

    app = WalletTrackerApp()
    assert app.state.session_factory is not None

    now = datetime.now(UTC)
    with app.state.session_factory() as session:
        net = Network(name="Ethereum", chain_type="evm", chain_id=1, enabled=True)
        session.add(net)
        session.flush()

        w1 = Wallet(address="0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", name="Alpha", chain_type="evm")
        session.add(w1)
        session.flush()

        # Snapshots: earlier 1,000, latest 1,200 (+20%)
        s1 = BalanceSnapshot(
            wallet_id=w1.id,
            network_id=net.id,
            balance=Decimal(1000),
            snapshot_at=now - timedelta(hours=25),
        )
        s2 = BalanceSnapshot(
            wallet_id=w1.id,
            network_id=net.id,
            balance=Decimal(1200),
            snapshot_at=now,
        )
        session.add_all([s1, s2])

        # DeFi position
        defi = DeFiPosition(
            wallet_id=w1.id,
            network_id=net.id,
            protocol="Aave v3",
            position_type="lending",
            amount=Decimal(500),
            usd_value=Decimal(500),
        )
        session.add(defi)

        # Sync job
        job = SyncJob(
            wallet_id=w1.id,
            network_id=net.id,
            job_type="balance",
            status="completed",
            finished_at=now,
        )
        session.add(job)

        session.commit()

    async with app.run_test(size=(120, 35)):
        screen = app.screen
        screen.refresh_data()

        metrics_panel = screen.query_one("#panel-metrics")
        rendered_text = metrics_panel.renderable if hasattr(metrics_panel, "renderable") else str(metrics_panel.render())
        metrics_str = str(rendered_text)

        assert "TOTAL BALANCE" in metrics_str
        assert "1,200" in metrics_str or "1200" in metrics_str
        assert "▲" in metrics_str
        assert "WALLETS" in metrics_str
        assert "TRACKED TX" in metrics_str
        assert "DEFI POS" in metrics_str
        assert "LAST SYNC" in metrics_str


@pytest.mark.asyncio
async def test_dashboard_wallets_panel_sorting_and_folding(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Panel 2: sorting by balance/change and group folding."""
    db_file = tmp_path / "wallets_sort_dashboard.db"
    monkeypatch.setenv("WIT_DB_PATH", str(db_file))

    from app.application import WalletTrackerApp

    app = WalletTrackerApp()
    assert app.state.session_factory is not None

    now = datetime.now(UTC)
    with app.state.session_factory() as session:
        repo_group = GroupRepository(session)
        g1 = repo_group.create(name="Vault")
        g2 = repo_group.create(name="Trading")

        net = Network(name="Polygon", chain_type="evm", chain_id=137)
        session.add(net)
        session.flush()

        w1 = Wallet(address="0x1111111111111111111111111111111111111111", name="W1", group_id=g1.id)
        w2 = Wallet(address="0x2222222222222222222222222222222222222222", name="W2", group_id=g1.id)
        w3 = Wallet(address="0x3333333333333333333333333333333333333333", name="W3", group_id=g2.id)
        session.add_all([w1, w2, w3])
        session.flush()

        # Balances: W1: 500 (+25%), W2: 2500 (-10%), W3: 1000 (no change)
        session.add_all([
            BalanceSnapshot(wallet_id=w1.id, network_id=net.id, balance=Decimal(400), snapshot_at=now - timedelta(hours=25)),
            BalanceSnapshot(wallet_id=w1.id, network_id=net.id, balance=Decimal(500), snapshot_at=now),
            BalanceSnapshot(wallet_id=w2.id, network_id=net.id, balance=Decimal(2777), snapshot_at=now - timedelta(hours=25)),
            BalanceSnapshot(wallet_id=w2.id, network_id=net.id, balance=Decimal(2500), snapshot_at=now),
            BalanceSnapshot(wallet_id=w3.id, network_id=net.id, balance=Decimal(1000), snapshot_at=now),
        ])
        session.commit()

    async with app.run_test(size=(120, 35)):
        screen = app.screen
        screen.refresh_data()

        # Verify initial rendering shows groups and shortened addresses
        w_panel = screen.query_one("#panel-wallets")
        rendered = str(w_panel.renderable if hasattr(w_panel, "renderable") else w_panel.render())
        assert "0x1111" in rendered or "W1" in rendered or "Vault" in rendered
        assert "0x2222" in rendered or "W2" in rendered
        assert "Polygon" in rendered or "POLYGON" in rendered

        # Test toggle fold
        screen.action_toggle_fold()
        screen.refresh_data()
        assert len(screen._folded_groups) > 0

        # Unfold again
        screen.action_toggle_fold()
        screen.refresh_data()
        assert len(screen._folded_groups) == 0

        # Test sort by change
        screen.action_sort_wallets("change")
        assert screen._sort_by == "change"

        # Test sort by balance
        screen.action_sort_wallets("balance")
        assert screen._sort_by == "balance"


@pytest.mark.asyncio
async def test_dashboard_activity_feed_colored_badges(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Panel 3: recent activities feed with color badges for transfer/swap/claim/sell."""
    db_file = tmp_path / "activity_dashboard.db"
    monkeypatch.setenv("WIT_DB_PATH", str(db_file))

    from app.application import WalletTrackerApp

    app = WalletTrackerApp()
    assert app.state.session_factory is not None

    now = datetime.now(UTC)
    with app.state.session_factory() as session:
        net = Network(name="Arbitrum", chain_type="evm", chain_id=42161)
        w = Wallet(address="0x4444444444444444444444444444444444444444", name="Main")
        session.add_all([net, w])
        session.flush()

        types = ["transfer", "swap", "claim", "sell"]
        for i, t in enumerate(types):
            session.add(
                Activity(
                    wallet_id=w.id,
                    network_id=net.id,
                    activity_type=t,
                    amount=Decimal(10 + i * 5),
                    occurred_at=now - timedelta(minutes=i * 10),
                    status="confirmed",
                    source="chain",
                )
            )
        session.commit()

    async with app.run_test(size=(120, 35)):
        screen = app.screen
        screen.refresh_data()

        act_panel = screen.query_one("#panel-activity")
        rendered = str(act_panel.renderable if hasattr(act_panel, "renderable") else act_panel.render())
        assert "SWAP" in rendered
        assert "TRANSFER" in rendered
        assert "CLAIM" in rendered
        assert "SELL" in rendered


@pytest.mark.asyncio
async def test_dashboard_balance_trend_sparkline_and_saturation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Panel 4: sparkline, saturation bar, and min/max/current stats."""
    db_file = tmp_path / "trend_dashboard.db"
    monkeypatch.setenv("WIT_DB_PATH", str(db_file))

    from app.application import WalletTrackerApp

    app = WalletTrackerApp()
    assert app.state.session_factory is not None

    now = datetime.now(UTC)
    with app.state.session_factory() as session:
        net = Network(name="Ethereum", chain_type="evm", chain_id=1)
        w = Wallet(address="0x5555555555555555555555555555555555555555", name="Hodl")
        session.add_all([net, w])
        session.flush()

        # Progression: 100 -> 200 -> 500 -> 800 -> 1000
        for i, val in enumerate([100, 200, 500, 800, 1000]):
            session.add(
                BalanceSnapshot(
                    wallet_id=w.id,
                    network_id=net.id,
                    balance=Decimal(val),
                    snapshot_at=now - timedelta(hours=10 - i),
                )
            )
        session.commit()

    async with app.run_test(size=(120, 35)):
        screen = app.screen
        screen.refresh_data()

        trend_panel = screen.query_one("#panel-trend")
        rendered = str(trend_panel.renderable if hasattr(trend_panel, "renderable") else trend_panel.render())
        assert "BALANCE TREND" in rendered
        assert "Saturation" in rendered
        # Contains sparkline UTF-8 block character
        assert any(c in rendered for c in " ▂▃▄▅▆▇█")
        assert "100" in rendered
        assert "1,000" in rendered or "1000" in rendered


@pytest.mark.asyncio
async def test_dashboard_zoom_panels_1_to_4(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Requirement 5: keys 1-4 toggle zoom/focus on panels, repeat returns to full view."""
    db_file = tmp_path / "zoom_dashboard.db"
    monkeypatch.setenv("WIT_DB_PATH", str(db_file))

    from app.application import WalletTrackerApp

    app = WalletTrackerApp()
    async with app.run_test(size=(120, 35)):
        screen = app.screen
        assert screen.id == "dashboard"
        assert screen._zoomed_panel is None

        # Zoom Panel 1
        screen.zoom_panel(1)
        assert screen._zoomed_panel == 1
        assert "zoomed" in screen.query_one("#panel-metrics").classes
        assert "panel-hidden" in screen.query_one("#panel-wallets").classes

        # Repeat Panel 1 -> returns to full view
        screen.zoom_panel(1)
        assert screen._zoomed_panel is None
        assert "zoomed" not in screen.query_one("#panel-metrics").classes
        assert "panel-hidden" not in screen.query_one("#panel-wallets").classes

        # Zoom Panel 2
        screen.zoom_panel(2)
        assert screen._zoomed_panel == 2
        assert "zoomed" in screen.query_one("#panel-wallets").classes

        # Escape returns to full view
        screen.action_escape_action()
        assert screen._zoomed_panel is None

        # Zoom Panel 3
        screen.zoom_panel(3)
        assert screen._zoomed_panel == 3
        screen.zoom_panel(3)
        assert screen._zoomed_panel is None

        # Zoom Panel 4
        screen.zoom_panel(4)
        assert screen._zoomed_panel == 4
        screen.zoom_panel(4)
        assert screen._zoomed_panel is None


@pytest.mark.asyncio
async def test_dashboard_status_line_and_issues(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Requirement 6: status line with sync state and issue counter."""
    db_file = tmp_path / "status_dashboard.db"
    monkeypatch.setenv("WIT_DB_PATH", str(db_file))

    from app.application import WalletTrackerApp

    app = WalletTrackerApp()
    assert app.state.session_factory is not None

    with app.state.session_factory() as session:
        net = Network(name="Ethereum", chain_type="evm", chain_id=1)
        w = Wallet(address="0x6666666666666666666666666666666666666666")
        session.add_all([net, w])
        session.flush()

        # Failed sync jobs
        j1 = SyncJob(wallet_id=w.id, network_id=net.id, job_type="balance", status="failed", error_message="Timeout")
        j2 = SyncJob(wallet_id=w.id, network_id=net.id, job_type="txs", status="failed", error_message="Rate limit")
        session.add_all([j1, j2])
        session.commit()

    async with app.run_test(size=(120, 35)):
        screen = app.screen
        screen.refresh_data()

        status_widget = screen.query_one("#dashboard-status-line")
        rendered = str(status_widget.renderable if hasattr(status_widget, "renderable") else status_widget.render())
        assert "sync:" in rendered
        assert "issues: 2" in rendered
