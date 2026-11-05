"""Unit tests for Stage 6: Sync pause/resume and manual activities."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from textual.widgets import Input

from app.application import WalletTrackerApp
from app.config import AppConfig
from app.core.activity_tracker import ActivityTracker
from app.core.sync_engine import SyncEngine
from app.database.models import Activity, Base, Network, SyncJob, Wallet
from app.providers.base import (
    DataProvider,
    ProviderResult,
    ProviderStatus,
    TransactionItem,
    TransactionListResult,
)
from app.providers.registry import ProviderRegistry
from app.ui.screens.activities import ActivitiesScreen
from app.ui.widgets.status_bar import StatusBar


class ControlledMockProvider(DataProvider):
    """Provider that can trigger callbacks (such as pause request) on specific calls."""

    name = "controlled_mock"

    def __init__(
        self,
        native_balance: Decimal | None = None,
        transactions: list[TransactionItem] | None = None,
    ) -> None:
        super().__init__()
        self.native_balance = native_balance if native_balance is not None else Decimal(1000000000000000000)
        self.transactions = transactions if transactions is not None else []
        self.balance_calls: list[str] = []
        self.tx_calls: list[str] = []
        self.on_balance_hook: Any | None = None

    def get_native_balance(self, address: str, network: str) -> ProviderResult:
        self.balance_calls.append(address)
        if self.on_balance_hook is not None:
            self.on_balance_hook(address)
        return ProviderResult(
            status=ProviderStatus.OK,
            data=self.native_balance,
            source=self.name,
        )

    def get_transactions(self, address: str, network: str, cursor: Any = None) -> ProviderResult:
        self.tx_calls.append(address)
        return ProviderResult(
            status=ProviderStatus.OK,
            data=TransactionListResult(items=self.transactions, next_cursor=None),
            source=self.name,
        )


@pytest.fixture
def memory_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def session_factory(memory_db):
    return sessionmaker(bind=memory_db)


@pytest.fixture
def seed_three_wallets(session_factory):
    with session_factory() as session:
        net = Network(name="ethereum", chain_type="evm", chain_id=1, enabled=True, native_token="ETH")
        w1 = Wallet(address="0x1111111111111111111111111111111111111111", name="Wallet1")
        w2 = Wallet(address="0x2222222222222222222222222222222222222222", name="Wallet2")
        w3 = Wallet(address="0x3333333333333333333333333333333333333333", name="Wallet3")
        session.add_all([net, w1, w2, w3])
        session.commit()
        return {
            "net_id": net.id,
            "w1_id": w1.id,
            "w2_id": w2.id,
            "w3_id": w3.id,
        }


def test_pause_requested_mid_provider_stops_between_wallets(session_factory, seed_three_wallets):
    """1. Pause requested from inside a provider call stops after the current wallet;

    counts are ok=1, skipped=2; is_paused is True; resume then processes all three.
    """
    w1_id = seed_three_wallets["w1_id"]
    w2_id = seed_three_wallets["w2_id"]
    w3_id = seed_three_wallets["w3_id"]

    provider = ControlledMockProvider()
    registry = ProviderRegistry([provider])
    engine = SyncEngine(session_factory, registry, AppConfig())

    # When provider is called for W1, request pause
    def pause_on_w1(address: str) -> None:
        if "1111" in address:
            engine.request_pause()

    provider.on_balance_hook = pause_on_w1

    reports = engine.sync_all(network="ethereum")

    assert len(reports) == 3
    ok_reports = [r for r in reports if r.status == "ok"]
    skipped_reports = [r for r in reports if r.status == "skipped"]

    assert len(ok_reports) == 1
    assert ok_reports[0].wallet_id == w1_id
    assert len(skipped_reports) == 2
    assert {r.wallet_id for r in skipped_reports} == {w2_id, w3_id}
    assert all("pause" in (r.error or "").lower() for r in skipped_reports)

    assert engine.is_paused is True

    # Check SyncJob statuses in database
    with session_factory() as s:
        job1 = s.execute(select(SyncJob).where(SyncJob.wallet_id == w1_id)).scalar_one()
        assert job1.status == "completed"

        job2 = s.execute(select(SyncJob).where(SyncJob.wallet_id == w2_id)).scalar_one()
        assert job2.status == "paused"

        job3 = s.execute(select(SyncJob).where(SyncJob.wallet_id == w3_id)).scalar_one()
        assert job3.status == "paused"

    # Resume and run sync_all again -> processes all three
    provider.on_balance_hook = None
    engine.request_resume()
    assert engine.is_paused is False

    reports_resumed = engine.sync_all(network="ethereum")
    assert len(reports_resumed) == 3
    assert all(r.status == "ok" for r in reports_resumed)


def test_paused_run_writes_paused_sync_job_and_syncs_nothing(session_factory, seed_three_wallets):
    """2. Paused run writes SyncJob.status='paused' (or 'skipped') and syncs nothing."""
    provider = ControlledMockProvider()
    registry = ProviderRegistry([provider])
    engine = SyncEngine(session_factory, registry, AppConfig())

    # Pre-pause the engine
    engine.request_pause()
    assert engine.is_paused is True

    reports = engine.sync_all(network="ethereum")

    assert len(reports) == 3
    assert all(r.status == "skipped" for r in reports)
    assert all("pause" in (r.error or "").lower() for r in reports)

    # Provider should never have been invoked
    assert len(provider.balance_calls) == 0
    assert len(provider.tx_calls) == 0

    # SyncJob rows should all be recorded with status "paused"
    with session_factory() as s:
        jobs = list(s.execute(select(SyncJob).order_by(SyncJob.id)).scalars().all())
        assert len(jobs) == 3
        assert all(j.status == "paused" for j in jobs)


def test_add_manual_flags_decimal_amount_and_synthetic_hash(session_factory, seed_three_wallets):
    """3. add_manual sets the manual flags, keeps Decimal amount, and creates a manual-… hash."""
    tracker = ActivityTracker(session_factory, AppConfig())
    w1_id = seed_three_wallets["w1_id"]
    net_id = seed_three_wallets["net_id"]

    amount_val = Decimal("123.5")
    note_val = "OTC settlement with Alice"
    occ_time = datetime(2026, 11, 4, 12, 0, 0, tzinfo=UTC)

    with session_factory() as session:
        # Rejects float
        with pytest.raises(TypeError, match="must be Decimal or int"):
            tracker.add_manual(
                session=session,
                wallet=w1_id,
                network=net_id,
                activity_type="trade",
                amount=123.45,  # type: ignore[arg-type]
            )

        act = tracker.add_manual(
            session=session,
            wallet=w1_id,
            network=net_id,
            activity_type="trade",
            amount=amount_val,
            occurred_at=occ_time,
            note=note_val,
        )
        session.commit()

        assert act.id is not None
        assert act.is_manual is True
        assert act.source == "manual"
        assert act.status == "manual"
        assert act.activity_type == "trade"
        assert isinstance(act.amount, Decimal)
        assert act.amount == amount_val
        assert act.tx_hash.startswith("manual-")
        assert not act.tx_hash.startswith("0x")
        act_occ = act.occurred_at if act.occurred_at.tzinfo else act.occurred_at.replace(tzinfo=UTC)
        assert act_occ == occ_time
        assert act.extra_data is not None
        extra = json.loads(act.extra_data)
        assert extra.get("note") == note_val

        # Verify wallet timestamps updated
        w = session.get(Wallet, w1_id)
        w_last = w.last_activity_at if w.last_activity_at.tzinfo else w.last_activity_at.replace(tzinfo=UTC)
        assert w_last == occ_time


def test_manual_and_auto_activities_coexist(session_factory, seed_three_wallets):
    """4. Manual and auto activities coexist: one of each in the DB after a sync plus an add_manual."""
    w1_id = seed_three_wallets["w1_id"]
    net_id = seed_three_wallets["net_id"]

    # 1. Produce auto activity via sync_wallet
    tx_time = datetime(2026, 11, 4, 15, 0, 0, tzinfo=UTC)
    tx = TransactionItem(
        hash="0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        from_address="0x1111111111111111111111111111111111111111",
        to_address="0x4444444444444444444444444444444444444444",
        value=Decimal("1.5"),
        block_number=12345,
        timestamp=tx_time,
        status="ok",
    )
    provider = ControlledMockProvider(transactions=[tx])
    registry = ProviderRegistry([provider])
    engine = SyncEngine(session_factory, registry, AppConfig())
    report = engine.sync_wallet(w1_id, network="ethereum")
    assert report.status == "ok"

    # 2. Add manual activity via tracker
    tracker = ActivityTracker(session_factory, AppConfig())
    with session_factory() as session:
        manual_act = tracker.add_manual(
            session=session,
            wallet=w1_id,
            network=net_id,
            activity_type="gift",
            amount=Decimal("0.5"),
            note="Manual airdrop gift",
        )
        session.commit()
        assert manual_act.id is not None

    # 3. Verify coexistence in DB
    with session_factory() as session:
        activities = list(
            session.execute(
                select(Activity).where(Activity.wallet_id == w1_id).order_by(Activity.id)
            ).scalars().all()
        )
        assert len(activities) == 2

        auto_act = next(a for a in activities if not a.is_manual)
        man_act = next(a for a in activities if a.is_manual)

        assert auto_act.source == "chain"
        assert auto_act.tx_hash == "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        assert auto_act.status == "confirmed"

        assert man_act.source == "manual"
        assert man_act.status == "manual"
        assert man_act.tx_hash.startswith("manual-")


@pytest.mark.asyncio
async def test_activities_feed_manual_filters(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """5. Feed filters: manual / auto / None, with visual marker ✎ on manual activities."""
    db_file = tmp_path / "test_stage6_feed.db"
    monkeypatch.setenv("WIT_DB_PATH", str(db_file))

    app = WalletTrackerApp()
    assert app.state.session_factory is not None

    with app.state.session_factory() as session:
        net = Network(name="ethereum", chain_type="evm", chain_id=1, enabled=True)
        w = Wallet(address="0x1111111111111111111111111111111111111111", name="AlphaWallet")
        session.add_all([net, w])
        session.flush()

        # Seed auto activity
        act_auto = Activity(
            wallet_id=w.id,
            network_id=net.id,
            activity_type="send",
            tx_hash="0xauto111111111111111111111111111111111111",
            amount=Decimal(10),
            occurred_at=datetime(2026, 11, 4, 10, 0, tzinfo=UTC),
            status="confirmed",
            source="chain",
            is_manual=False,
        )
        # Seed manual activity
        act_manual = Activity(
            wallet_id=w.id,
            network_id=net.id,
            activity_type="receive",
            tx_hash="manual-abcdef0123456789abcdef0123456789",
            amount=Decimal(20),
            occurred_at=datetime(2026, 11, 4, 11, 0, tzinfo=UTC),
            status="manual",
            source="manual",
            is_manual=True,
            extra_data='{"note": "manual offchain"}',
        )
        session.add_all([act_auto, act_manual])
        session.commit()

    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.press("3")
        await pilot.pause()

        screen = app.screen
        assert isinstance(screen, ActivitiesScreen)

        # 1. Default (None): both should appear, manual has ✎ marker
        text_all = screen.activity_text
        assert "send" in text_all
        assert "receive" in text_all
        assert "✎" in text_all
        assert "0xauto...1111" in text_all
        assert "manual...6789" in text_all

        # 2. Filter: manual only
        screen.set_manual_filter("manual")
        text_manual = screen.activity_text
        assert "receive" in text_manual
        assert "✎" in text_manual
        assert "manual...6789" in text_manual
        assert "0xauto...1111" not in text_manual

        # 3. Filter: auto only
        screen.set_manual_filter("auto")
        text_auto = screen.activity_text
        assert "send" in text_auto
        assert "0xauto...1111" in text_auto
        assert "✎" not in text_auto
        assert "manual...6789" not in text_auto

        # 4. Filter: None restores both
        screen.set_manual_filter(None)
        text_restored = screen.activity_text
        assert "send" in text_restored
        assert "receive" in text_restored
        assert "✎" in text_restored


@pytest.mark.asyncio
async def test_p_hotkey_toggles_pause_and_drives_status_bar(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """App hotkey 'p' toggles pause on SyncEngine and drives StatusBar.sync_state."""
    db_file = tmp_path / "test_stage6_hotkey.db"
    monkeypatch.setenv("WIT_DB_PATH", str(db_file))

    app = WalletTrackerApp()
    async with app.run_test(size=(120, 35)) as pilot:
        status_bar = app.query_one(StatusBar)
        assert status_bar.sync_state == "idle"
        assert app.sync_engine.is_paused is False

        # Press p -> toggle to paused
        await pilot.press("p")
        await pilot.pause()

        assert status_bar.sync_state == "paused"
        assert "Paused" in status_bar.render()
        assert app.sync_engine.is_paused is True
        assert app.state.sync_state == "paused"

        # Press p again -> toggle back to idle / resumed
        await pilot.press("p")
        await pilot.pause()

        assert status_bar.sync_state == "idle"
        assert "Idle" in status_bar.render()
        assert app.sync_engine.is_paused is False
        assert app.state.sync_state == "idle"


@pytest.mark.asyncio
async def test_p_hotkey_suppressed_when_input_focused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When an Input is focused, typing 'p' must not toggle pause."""
    db_file = tmp_path / "test_stage6_suppress.db"
    monkeypatch.setenv("WIT_DB_PATH", str(db_file))

    app = WalletTrackerApp()
    async with app.run_test(size=(120, 35)) as pilot:
        # Navigate to a screen or mount an Input
        test_input = Input(id="test-input")
        await app.screen.mount(test_input)
        test_input.focus()
        await pilot.pause()

        assert app.focused is test_input
        assert app.sync_engine.is_paused is False

        # Type 'p' into the input
        await pilot.press("p")
        await pilot.pause()

        assert test_input.value == "p"
        assert app.sync_engine.is_paused is False
        status_bar = app.query_one(StatusBar)
        assert status_bar.sync_state == "idle"
