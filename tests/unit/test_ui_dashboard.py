"""Unit tests for Dashboard screen real counters."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.database.models import Activity, Network, Project
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
