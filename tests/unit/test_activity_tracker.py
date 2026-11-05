"""Unit tests for ActivityTracker core module (Stage 4A)."""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import AppConfig
from app.core.activity_tracker import ActivityTracker
from app.database.models import Activity, Base, Network, Project, ProjectContract, Wallet
from app.providers.base import TransactionItem


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
def session(session_factory):
    with session_factory() as s:
        yield s


@pytest.fixture
def sample_data(session: Session):
    net = Network(name="ethereum", chain_type="evm", chain_id=1, enabled=True)
    w = Wallet(address="0x1111111111111111111111111111111111111111", name="Alice")
    proj = Project(name="Uniswap", description="DEX protocol", category="defi")
    session.add_all([net, w, proj])
    session.flush()

    contract = ProjectContract(
        project_id=proj.id,
        network_id=net.id,
        contract_address="0x7a250d5630b4cf539739df2c5dacb4c659f2488d",
        name="Router",
    )
    session.add(contract)
    session.commit()
    return {"net": net, "wallet": w, "project": proj, "contract": contract}


def test_classify_send(session_factory):
    tracker = ActivityTracker(session_factory, AppConfig())
    wallet_addr = "0x1111111111111111111111111111111111111111"
    tx = TransactionItem(
        hash="0xsend1",
        from_address=wallet_addr,
        to_address="0x2222222222222222222222222222222222222222",
        value=Decimal(1000000000000000000),
    )
    assert tracker.classify(wallet_addr, tx) == "send"


def test_classify_receive(session_factory):
    tracker = ActivityTracker(session_factory, AppConfig())
    wallet_addr = "0x1111111111111111111111111111111111111111"
    tx = TransactionItem(
        hash="0xrecv1",
        from_address="0x2222222222222222222222222222222222222222",
        to_address=wallet_addr,
        value=Decimal(500000000000000000),
    )
    assert tracker.classify(wallet_addr, tx) == "receive"


def test_classify_self(session_factory):
    tracker = ActivityTracker(session_factory, AppConfig())
    wallet_addr = "0x1111111111111111111111111111111111111111"
    tx = TransactionItem(
        hash="0xself1",
        from_address=wallet_addr,
        to_address=wallet_addr,
        value=Decimal(0),
    )
    assert tracker.classify(wallet_addr, tx) == "self"


def test_classify_contract_call_to_known_project(session_factory, sample_data):
    tracker = ActivityTracker(session_factory, AppConfig())
    wallet_addr = sample_data["wallet"].address
    contract_addr = sample_data["contract"].contract_address

    tx = TransactionItem(
        hash="0xcall1",
        from_address=wallet_addr,
        to_address=contract_addr,
        value=Decimal(0),
    )
    # Check classification finds contract_call when to is known project contract
    assert tracker.classify(wallet_addr, tx) == "contract_call"


def test_record_happy_path(session_factory, sample_data):
    tracker = ActivityTracker(session_factory, AppConfig())
    with session_factory() as s:
        w = s.get(Wallet, sample_data["wallet"].id)
        net = s.get(Network, sample_data["net"].id)
        occurred = datetime(2026, 11, 4, 12, 0, 0, tzinfo=UTC)

        tx = TransactionItem(
            hash="0xabc123",
            from_address=w.address,
            to_address="0x9999999999999999999999999999999999999999",
            value=Decimal(1500000000000000000),
            block_number=123456,
            timestamp=occurred,
            status="ok",
        )

        act = tracker.record(s, w, net, tx)
        s.flush()

        assert act.id is not None
        assert act.wallet_id == w.id
        assert act.network_id == net.id
        assert act.tx_hash == "0xabc123"
        assert act.activity_type == "send"
        assert act.amount == Decimal(1500000000000000000)
        assert isinstance(act.amount, Decimal)
        assert act.occurred_at == occurred
        assert act.occurred_at.tzinfo is not None
        assert act.project_id is None
        assert act.source == "chain"
        s.commit()


def test_record_project_detection(session_factory, sample_data):
    tracker = ActivityTracker(session_factory, AppConfig())
    with session_factory() as s:
        w = s.get(Wallet, sample_data["wallet"].id)
        net = s.get(Network, sample_data["net"].id)
        contract = sample_data["contract"]

        # Mixed-case to verify case-insensitivity
        tx = TransactionItem(
            hash="0xrouter_call",
            from_address=w.address,
            to_address=contract.contract_address.upper(),
            value=Decimal(0),
            block_number=123457,
            timestamp=datetime.now(UTC),
            status="ok",
        )

        act = tracker.record(s, w, net, tx)
        s.commit()

        assert act.activity_type == "contract_call"
        assert act.project_id == sample_data["project"].id
        assert act.source == "detected"


def test_record_idempotency_returns_existing(session_factory, sample_data):
    tracker = ActivityTracker(session_factory, AppConfig())
    with session_factory() as s:
        w = s.get(Wallet, sample_data["wallet"].id)
        net = s.get(Network, sample_data["net"].id)

        tx = TransactionItem(
            hash="0xdup1",
            from_address=w.address,
            to_address="0x8888888888888888888888888888888888888888",
            value=Decimal(100),
            block_number=500,
        )

        act1 = tracker.record(s, w, net, tx)
        s.commit()

        act2 = tracker.record(s, w, net, tx)
        s.commit()

        assert act1.id == act2.id

        # Verify only 1 row exists in DB
        rows = list(s.execute(select(Activity).where(Activity.tx_hash == "0xdup1")).scalars().all())
        assert len(rows) == 1


def test_record_rejects_float_amount(session_factory, sample_data):
    tracker = ActivityTracker(session_factory, AppConfig())
    with session_factory() as s:
        w = s.get(Wallet, sample_data["wallet"].id)
        net = s.get(Network, sample_data["net"].id)

        tx = TransactionItem(
            hash="0xfloat1",
            from_address=w.address,
            to_address="0x2222222222222222222222222222222222222222",
            value=1.5,  # type: ignore[arg-type]
        )

        with pytest.raises(TypeError, match="float"):
            tracker.record(s, w, net, tx)


def test_record_self_transfer(session_factory, sample_data):
    tracker = ActivityTracker(session_factory, AppConfig())
    with session_factory() as s:
        w = s.get(Wallet, sample_data["wallet"].id)
        net = s.get(Network, sample_data["net"].id)

        tx = TransactionItem(
            hash="0xself_rec",
            from_address=w.address,
            to_address=w.address,
            value=Decimal(0),
        )

        act = tracker.record(s, w, net, tx)
        s.flush()

        assert act.activity_type == "self"
        assert act.project_id is None
        assert act.source == "chain"

