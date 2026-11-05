"""Unit tests for Stage 4B: ActivitiesScreen, DashboardScreen, and sync hotkey."""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

from app.application import WalletTrackerApp
from app.core.sync_engine import SyncEngine
from app.database.models import Activity, BalanceSnapshot, Network, Project, SyncJob, Wallet
from app.providers.base import (
    DataProvider,
    ProviderResult,
    ProviderStatus,
    TransactionItem,
    TransactionListResult,
)
from app.providers.registry import ProviderRegistry
from app.ui.screens.activities import ActivitiesScreen
from app.ui.screens.dashboard import DashboardScreen
from app.ui.widgets.status_bar import StatusBar


class FakeProvider(DataProvider):
    """Offline test provider for balance and transaction data."""

    name = "fake"

    def __init__(
        self,
        native_balance: Decimal | None = None,
        transactions: list[TransactionItem] | None = None,
        balance_status: ProviderStatus = ProviderStatus.OK,
        tx_status: ProviderStatus = ProviderStatus.OK,
        error_msg: str | None = None,
    ) -> None:
        super().__init__()
        self.balance_val = native_balance if native_balance is not None else Decimal(1000000000000000000)
        self.tx_items = transactions if transactions is not None else []
        self.balance_status = balance_status
        self.tx_status = tx_status
        self.error_msg = error_msg

    def get_native_balance(self, address: str, network: str) -> ProviderResult:
        if self.balance_status != ProviderStatus.OK:
            return ProviderResult(
                status=self.balance_status,
                error=self.error_msg or "balance failure",
                source=self.name,
            )
        return ProviderResult(status=ProviderStatus.OK, data=self.balance_val, source=self.name)

    def get_transactions(self, address: str, network: str, cursor: Any = None) -> ProviderResult:
        if self.tx_status != ProviderStatus.OK:
            return ProviderResult(
                status=self.tx_status,
                error=self.error_msg or "tx failure",
                source=self.name,
            )
        return ProviderResult(
            status=ProviderStatus.OK,
            data=TransactionListResult(items=self.tx_items, next_cursor=None),
            source=self.name,
        )


@pytest.mark.asyncio
async def test_activities_feed_loads_sync_engine_rows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """1. Activities feed loads rows produced by SyncEngine and shows type + short hash."""
    db_file = tmp_path / "test_feed.db"
    monkeypatch.setenv("WIT_DB_PATH", str(db_file))

    app = WalletTrackerApp()
    assert app.state.session_factory is not None

    with app.state.session_factory() as session:
        net = Network(name="ethereum", chain_type="evm", chain_id=1, enabled=True)
        w = Wallet(address="0x1111111111111111111111111111111111111111", name="AlphaWallet")
        session.add_all([net, w])
        session.commit()
        w_id = w.id

    tx_hash = "0xabcdef1234567890abcdef1234567890abcdef12"
    tx_item = TransactionItem(
        hash=tx_hash,
        from_address="0x9999999999999999999999999999999999999999",
        to_address="0x1111111111111111111111111111111111111111",
        value=Decimal(1500000000000000000),
        block_number=1000,
        timestamp=datetime(2026, 11, 4, 14, 30, tzinfo=UTC),
    )
    fake_provider = FakeProvider(transactions=[tx_item])
    registry = ProviderRegistry([fake_provider])

    engine = SyncEngine(app.state.session_factory, registry, app.config)
    reports = engine.sync_wallet(w_id)
    assert reports.status == "ok"

    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.press("3")
        await pilot.pause()

        assert isinstance(app.screen, ActivitiesScreen)
        text = app.screen.activity_text

        assert "receive" in text
        assert "0xabcd...ef12" in text
        assert "AlphaWallet" in text
        assert "ethereum" in text
        assert "1.5" in text
        assert " · " in text


@pytest.mark.asyncio
async def test_activities_type_filter_narrows_and_restores(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """2. set_type_filter('receive') narrows the feed; None restores it."""
    db_file = tmp_path / "test_filter.db"
    monkeypatch.setenv("WIT_DB_PATH", str(db_file))

    app = WalletTrackerApp()
    assert app.state.session_factory is not None

    with app.state.session_factory() as session:
        net = Network(name="ethereum", chain_type="evm", chain_id=1, enabled=True)
        w = Wallet(address="0x1111111111111111111111111111111111111111", name="AlphaWallet")
        session.add_all([net, w])
        session.flush()

        act1 = Activity(
            wallet_id=w.id,
            network_id=net.id,
            activity_type="receive",
            tx_hash="0x1111111111111111111111111111111111111111",
            amount=Decimal(10),
            occurred_at=datetime(2026, 11, 4, 10, 0, tzinfo=UTC),
            status="confirmed",
            source="chain",
        )
        act2 = Activity(
            wallet_id=w.id,
            network_id=net.id,
            activity_type="send",
            tx_hash="0x2222222222222222222222222222222222222222",
            amount=Decimal(5),
            occurred_at=datetime(2026, 11, 4, 11, 0, tzinfo=UTC),
            status="confirmed",
            source="chain",
        )
        session.add_all([act1, act2])
        session.commit()

    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.press("3")
        await pilot.pause()

        screen = app.screen
        assert isinstance(screen, ActivitiesScreen)

        # Initially both activities are shown
        assert "receive" in screen.activity_text
        assert "send" in screen.activity_text

        # Filter by receive
        screen.set_type_filter("receive")
        assert "receive" in screen.activity_text
        assert "send" not in screen.activity_text

        # Clear filter
        screen.set_type_filter(None)
        assert "receive" in screen.activity_text
        assert "send" in screen.activity_text

        # Network filter
        screen.set_network_filter("ethereum")
        assert "receive" in screen.activity_text
        screen.set_network_filter("polygon")
        assert screen.activity_text == "No activities yet — press s to sync your wallets."
        screen.set_network_filter(None)
        assert "receive" in screen.activity_text


@pytest.mark.asyncio
async def test_activities_empty_db_shows_empty_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """3. Empty DB → empty-state text, no traceback."""
    db_file = tmp_path / "test_empty_feed.db"
    monkeypatch.setenv("WIT_DB_PATH", str(db_file))

    app = WalletTrackerApp()
    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.press("3")
        await pilot.pause()

        screen = app.screen
        assert isinstance(screen, ActivitiesScreen)
        assert screen.activity_text == "No activities yet — press s to sync your wallets."


@pytest.mark.asyncio
async def test_dashboard_counts_match_seeded_entities(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """4. Dashboard counts match seeded wallets/activities/projects."""
    db_file = tmp_path / "test_dashboard_counts.db"
    monkeypatch.setenv("WIT_DB_PATH", str(db_file))

    app = WalletTrackerApp()
    assert app.state.session_factory is not None

    with app.state.session_factory() as session:
        net = Network(name="ethereum", chain_type="evm", chain_id=1, enabled=True)
        w1 = Wallet(address="0x1111111111111111111111111111111111111111", name="Wallet1")
        w2 = Wallet(address="0x2222222222222222222222222222222222222222", name="Wallet2")
        proj = Project(name="Uniswap", description="DEX", category="defi")
        session.add_all([net, w1, w2, proj])
        session.flush()

        # Seed 2 balance snapshots
        s1 = BalanceSnapshot(
            wallet_id=w1.id,
            network_id=net.id,
            balance=Decimal(1000),
            snapshot_at=datetime.now(UTC),
        )
        s2 = BalanceSnapshot(
            wallet_id=w2.id,
            network_id=net.id,
            balance=Decimal(2500),
            snapshot_at=datetime.now(UTC),
        )
        session.add_all([s1, s2])

        # Seed 3 activities
        for i in range(3):
            session.add(
                Activity(
                    wallet_id=w1.id,
                    network_id=net.id,
                    activity_type="tx",
                    tx_hash=f"0x333333333333333333333333333333333333330{i}",
                    amount=Decimal(i + 1),
                    occurred_at=datetime.now(UTC),
                    status="confirmed",
                    source="chain",
                )
            )
        session.commit()

    async with app.run_test(size=(120, 35)):
        screen = app.screen
        assert isinstance(screen, DashboardScreen)
        screen.refresh_data()

        text = screen.dashboard_text
        assert "Wallets: 2" in text
        assert "Activities: 3" in text
        assert "Projects: 1" in text
        assert "3500" in text or "Total Tracked Value" in text
        assert "Last 5 Activities" in text or "Recent Activities" in text

        counts = screen.get_counters()
        assert counts["wallets"] == 2
        assert counts["activities"] == 3
        assert counts["projects"] == 1


@pytest.mark.asyncio
async def test_s_hotkey_sync_with_fake_provider(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """5. s with a fake provider: SyncJob created, status bar returns to idle, last_update set."""
    db_file = tmp_path / "test_sync_hotkey.db"
    monkeypatch.setenv("WIT_DB_PATH", str(db_file))

    app = WalletTrackerApp()
    assert app.state.session_factory is not None

    with app.state.session_factory() as session:
        net = Network(name="ethereum", chain_type="evm", chain_id=1, enabled=True)
        w = Wallet(address="0x1111111111111111111111111111111111111111", name="Wallet1")
        session.add_all([net, w])
        session.commit()

    fake_provider = FakeProvider()
    app.state.providers = ProviderRegistry([fake_provider])

    async with app.run_test(size=(120, 35)) as pilot:
        status_bar = app.query_one(StatusBar)
        assert status_bar.sync_state == "idle"
        assert status_bar.last_update is None

        await pilot.press("s")
        await app.workers.wait_for_complete()

        # Status bar returns to idle and last_update is recorded
        assert status_bar.sync_state == "idle"
        assert status_bar.last_update is not None
        assert app.state.last_update is not None

        # Verify SyncJob in DB
        with app.state.session_factory() as session:
            job = session.execute(
                select(SyncJob).order_by(SyncJob.id.desc()).limit(1)
            ).scalar_one_or_none()
            assert job is not None
            assert job.status == "completed"


@pytest.mark.asyncio
async def test_s_hotkey_sync_with_failing_provider(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """6. s with a failing provider: SyncJob.status == 'failed', UI alive."""
    db_file = tmp_path / "test_sync_failing.db"
    monkeypatch.setenv("WIT_DB_PATH", str(db_file))

    app = WalletTrackerApp()
    assert app.state.session_factory is not None

    with app.state.session_factory() as session:
        net = Network(name="ethereum", chain_type="evm", chain_id=1, enabled=True)
        w = Wallet(address="0x1111111111111111111111111111111111111111", name="Wallet1")
        session.add_all([net, w])
        session.commit()

    failing_provider = FakeProvider(
        balance_status=ProviderStatus.ERROR,
        error_msg="Connection timeout to RPC node",
    )
    app.state.providers = ProviderRegistry([failing_provider])

    async with app.run_test(size=(120, 35)) as pilot:
        status_bar = app.query_one(StatusBar)
        assert status_bar.sync_state == "idle"

        await pilot.press("s")
        await app.workers.wait_for_complete()

        # UI is still alive and running
        assert app.is_running
        assert status_bar.sync_state == "idle"
        assert status_bar.last_update is not None

        # Verify SyncJob in DB has failed status
        with app.state.session_factory() as session:
            job = session.execute(
                select(SyncJob).order_by(SyncJob.id.desc()).limit(1)
            ).scalar_one_or_none()
            assert job is not None
            assert job.status == "failed"
            assert "timeout" in (job.error_message or "").lower()


@pytest.mark.asyncio
async def test_s_hotkey_sync_no_wallets_keeps_ui_alive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No wallets → no sync, keep the UI alive (no traceback, status returns to idle)."""
    db_file = tmp_path / "test_sync_no_wallets.db"
    monkeypatch.setenv("WIT_DB_PATH", str(db_file))

    app = WalletTrackerApp()
    fake_provider = FakeProvider()
    app.state.providers = ProviderRegistry([fake_provider])

    async with app.run_test(size=(120, 35)) as pilot:
        status_bar = app.query_one(StatusBar)
        assert status_bar.sync_state == "idle"

        await pilot.press("s")
        await app.workers.wait_for_complete()

        assert app.is_running
        assert status_bar.sync_state == "idle"
        assert status_bar.last_update is not None

        # Verify no SyncJob was created since there were no wallets
        with app.state.session_factory() as session:
            job = session.execute(select(SyncJob)).scalar_one_or_none()
            assert job is None

