"""Unit tests for SyncEngine core module (Stage 4A)."""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import AppConfig
from app.core.sync_engine import SyncEngine, SyncReport
from app.database.models import (
    Activity,
    BalanceSnapshot,
    Base,
    Network,
    Project,
    ProjectContract,
    SyncCursor,
    SyncJob,
    Transaction,
    Wallet,
)
from app.providers.base import (
    DataProvider,
    ProviderResult,
    ProviderStatus,
    TransactionItem,
    TransactionListResult,
)
from app.providers.registry import ProviderRegistry


class MockProvider(DataProvider):
    name = "mock"

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
        self.calls: list[dict[str, Any]] = []

    def get_native_balance(self, address: str, network: str) -> ProviderResult:
        self.calls.append({"method": "get_native_balance", "address": address, "network": network})
        if self.balance_status != ProviderStatus.OK:
            return ProviderResult(status=self.balance_status, error=self.error_msg or "balance error", source=self.name)
        return ProviderResult(status=ProviderStatus.OK, data=self.balance_val, source=self.name)

    def get_transactions(self, address: str, network: str, cursor: Any = None) -> ProviderResult:
        self.calls.append({"method": "get_transactions", "address": address, "network": network, "cursor": cursor})
        if self.tx_status != ProviderStatus.OK:
            return ProviderResult(status=self.tx_status, error=self.error_msg or "tx error", source=self.name)
        return ProviderResult(
            status=ProviderStatus.OK,
            data=TransactionListResult(items=self.tx_items, next_cursor=None),
            source=self.name,
        )


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
    return sessionmaker(bind=engine)


@pytest.fixture
def seed_data(session_factory):
    with session_factory() as s:
        net = Network(name="ethereum", chain_type="evm", chain_id=1, enabled=True)
        w1 = Wallet(address="0x1111111111111111111111111111111111111111", name="Wallet1")
        w2 = Wallet(address="0x2222222222222222222222222222222222222222", name="Wallet2")
        proj = Project(name="Curve", description="Curve Finance", category="defi")
        s.add_all([net, w1, w2, proj])
        s.flush()

        contract = ProjectContract(
            project_id=proj.id,
            network_id=net.id,
            contract_address="0xd533a949740bb3306d119cc777fa900ba034cd52",
            name="CRV Token",
        )
        s.add(contract)
        s.commit()
        return {
            "net_id": net.id,
            "w1_id": w1.id,
            "w2_id": w2.id,
            "contract_address": contract.contract_address,
        }


def test_sync_wallet_happy_path(session_factory, seed_data):
    w1_id = seed_data["w1_id"]
    tx_time = datetime(2026, 11, 4, 15, 30, 0, tzinfo=UTC)
    tx = TransactionItem(
        hash="0xhash1",
        from_address="0x1111111111111111111111111111111111111111",
        to_address="0x3333333333333333333333333333333333333333",
        value=Decimal(2000000000000000000),
        block_number=19000000,
        timestamp=tx_time,
        status="ok",
    )
    provider = MockProvider(
        native_balance=Decimal(5000000000000000000),
        transactions=[tx],
    )
    registry = ProviderRegistry([provider])
    config = AppConfig()

    engine = SyncEngine(session_factory, registry, config)
    report = engine.sync_wallet(w1_id, network="ethereum")

    assert isinstance(report, SyncReport)
    assert report.wallet_id == w1_id
    assert report.network == "ethereum"
    assert report.status == "ok"
    assert report.activities_added == 1
    assert report.activities_updated == 0
    assert report.balance_saved is True
    assert report.error is None

    # Verify DB state
    with session_factory() as s:
        # BalanceSnapshot
        snaps = list(s.execute(select(BalanceSnapshot).where(BalanceSnapshot.wallet_id == w1_id)).scalars().all())
        assert len(snaps) == 1
        assert snaps[0].balance == Decimal(5000000000000000000)
        assert isinstance(snaps[0].balance, Decimal)
        assert snaps[0].block_number == 19000000

        # Transaction
        txs = list(s.execute(select(Transaction).where(Transaction.wallet_id == w1_id)).scalars().all())
        assert len(txs) == 1
        assert txs[0].tx_hash == "0xhash1"
        assert txs[0].value == Decimal(2000000000000000000)

        # Activity
        acts = list(s.execute(select(Activity).where(Activity.wallet_id == w1_id)).scalars().all())
        assert len(acts) == 1
        assert acts[0].tx_hash == "0xhash1"
        assert acts[0].activity_type == "send"
        assert acts[0].amount == Decimal(2000000000000000000)

        # SyncCursor
        cursor = s.execute(
            select(SyncCursor).where(
                SyncCursor.wallet_id == w1_id,
                SyncCursor.data_type == "tx",
            )
        ).scalar_one_or_none()
        assert cursor is not None
        assert cursor.last_block_number == 19000000

        # SyncJob
        job = s.execute(
            select(SyncJob).where(
                SyncJob.wallet_id == w1_id,
                SyncJob.job_type == "wallet_sync",
            )
        ).scalar_one_or_none()
        assert job is not None
        assert job.status == "completed"
        assert job.started_at is not None
        assert job.finished_at is not None
        assert job.error_message is None


def test_sync_wallet_idempotency(session_factory, seed_data):
    w1_id = seed_data["w1_id"]
    tx = TransactionItem(
        hash="0xhash_idem",
        from_address="0x1111111111111111111111111111111111111111",
        to_address="0x4444444444444444444444444444444444444444",
        value=Decimal(100),
        block_number=19000050,
    )
    provider = MockProvider(
        native_balance=Decimal(1000),
        transactions=[tx],
    )
    registry = ProviderRegistry([provider])
    engine = SyncEngine(session_factory, registry, AppConfig())

    # Run 1
    r1 = engine.sync_wallet(w1_id, network="ethereum")
    assert r1.status == "ok"
    assert r1.activities_added == 1
    assert r1.balance_saved is True

    # Run 2 (same window)
    r2 = engine.sync_wallet(w1_id, network="ethereum")
    assert r2.status == "ok"
    assert r2.activities_added == 0
    assert r2.activities_updated == 0
    assert r2.balance_saved is False

    with session_factory() as s:
        acts = list(s.execute(select(Activity).where(Activity.wallet_id == w1_id)).scalars().all())
        assert len(acts) == 1
        txs = list(s.execute(select(Transaction).where(Transaction.wallet_id == w1_id)).scalars().all())
        assert len(txs) == 1
        snaps = list(s.execute(select(BalanceSnapshot).where(BalanceSnapshot.wallet_id == w1_id)).scalars().all())
        assert len(snaps) == 1


def test_sync_wallet_cursor_resume(session_factory, seed_data):
    w1_id = seed_data["w1_id"]
    tx1 = TransactionItem(
        hash="0xblock100",
        from_address="0x1111111111111111111111111111111111111111",
        to_address="0x5555555555555555555555555555555555555555",
        value=Decimal(1),
        block_number=100,
    )
    provider = MockProvider(transactions=[tx1])
    registry = ProviderRegistry([provider])
    engine = SyncEngine(session_factory, registry, AppConfig())

    # Fresh wallet passes cursor=None
    engine.sync_wallet(w1_id, network="ethereum")
    assert len(provider.calls) >= 2
    tx_calls = [c for c in provider.calls if c["method"] == "get_transactions"]
    assert tx_calls[0]["cursor"] is None

    # Next run passes cursor with block=100, last_block=100
    engine.sync_wallet(w1_id, network="ethereum")
    assert len([c for c in provider.calls if c["method"] == "get_transactions"]) == 2
    second_tx_call = [c for c in provider.calls if c["method"] == "get_transactions"][1]
    assert second_tx_call["cursor"] == {"block": 100, "last_block": 100}


def test_sync_all_error_isolation(session_factory, seed_data):
    w1_id = seed_data["w1_id"]
    w2_id = seed_data["w2_id"]

    class FlakyProvider(DataProvider):
        name = "flaky"

        def get_native_balance(self, address: str, network: str) -> ProviderResult:
            if "1111" in address:
                return ProviderResult(status=ProviderStatus.ERROR, error="RPC timeout", source=self.name)
            return ProviderResult(status=ProviderStatus.OK, data=Decimal(100), source=self.name)

        def get_transactions(self, address: str, network: str, cursor: Any = None) -> ProviderResult:
            return ProviderResult(status=ProviderStatus.OK, data=TransactionListResult(), source=self.name)

    registry = ProviderRegistry([FlakyProvider()])
    engine = SyncEngine(session_factory, registry, AppConfig())

    reports = engine.sync_all(network="ethereum")

    assert len(reports) == 2
    r_map = {r.wallet_id: r for r in reports}

    # W1 had error
    assert r_map[w1_id].status == "error"
    assert "RPC timeout" in (r_map[w1_id].error or "")

    # W2 succeeded
    assert r_map[w2_id].status == "ok"

    # Verify SyncJob statuses in DB
    with session_factory() as s:
        job1 = s.execute(
            select(SyncJob).where(SyncJob.wallet_id == w1_id).order_by(SyncJob.id.desc())
        ).scalar_one()
        assert job1.status == "failed"
        assert "RPC timeout" in (job1.error_message or "")

        job2 = s.execute(
            select(SyncJob).where(SyncJob.wallet_id == w2_id).order_by(SyncJob.id.desc())
        ).scalar_one()
        assert job2.status == "completed"


def test_sync_wallet_rate_limited(session_factory, seed_data):
    w1_id = seed_data["w1_id"]
    provider = MockProvider(balance_status=ProviderStatus.RATE_LIMITED, error_msg="Too many requests")
    registry = ProviderRegistry([provider])
    engine = SyncEngine(session_factory, registry, AppConfig())

    report = engine.sync_wallet(w1_id, network="ethereum")

    assert report.status == "error"
    assert report.error is not None
    assert "rate limit" in report.error.lower() or "retry" in report.error.lower()

    with session_factory() as s:
        job = s.execute(select(SyncJob).where(SyncJob.wallet_id == w1_id)).scalar_one()
        assert job.status == "failed"
        assert job.error_message is not None


def test_sync_wallet_snapshot_precision_decimal_no_float(session_factory, seed_data):
    w1_id = seed_data["w1_id"]
    # Exact wei value as Decimal
    amount = Decimal(1234567890123456789)
    provider = MockProvider(native_balance=amount)
    registry = ProviderRegistry([provider])
    engine = SyncEngine(session_factory, registry, AppConfig())

    report = engine.sync_wallet(w1_id, network="ethereum")
    assert report.status == "ok"
    assert report.balance_saved is True

    with session_factory() as s:
        snap = s.execute(select(BalanceSnapshot).where(BalanceSnapshot.wallet_id == w1_id)).scalar_one()
        assert isinstance(snap.balance, Decimal)
        assert not isinstance(snap.balance, float)
        assert snap.raw_balance == "1234567890123456789"

    # Reject float native balance
    provider_float = MockProvider(native_balance=123.45)  # type: ignore[arg-type]
    engine_float = SyncEngine(session_factory, ProviderRegistry([provider_float]), AppConfig())
    report_float = engine_float.sync_wallet(w1_id, network="ethereum")
    assert report_float.status == "error"
    assert "float" in (report_float.error or "").lower()


def test_sync_wallet_archived_skipped(session_factory, seed_data):
    w1_id = seed_data["w1_id"]
    with session_factory() as s:
        w = s.get(Wallet, w1_id)
        w.archived = True
        s.commit()

    provider = MockProvider()
    engine = SyncEngine(session_factory, ProviderRegistry([provider]), AppConfig())
    report = engine.sync_wallet(w1_id, network="ethereum")

    assert report.status == "skipped"
    assert len(provider.calls) == 0


def test_sync_wallet_nonexistent_wallet(session_factory):
    provider = MockProvider()
    engine = SyncEngine(session_factory, ProviderRegistry([provider]), AppConfig())
    report = engine.sync_wallet(999999, network="ethereum")

    assert report.status == "error"
    assert "not found" in (report.error or "").lower()

