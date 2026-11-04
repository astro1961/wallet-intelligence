"""Unit tests for balance manager and balance snapshot persistence."""
from __future__ import annotations

from datetime import UTC
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.balance_manager import save_native_balance
from app.database.models import BalanceSnapshot, Base, Network, Wallet


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    sm = sessionmaker(bind=engine)
    s = sm()
    try:
        yield s
    finally:
        s.close()


def test_save_native_balance_preserves_decimal_and_block_number(session: Session):
    net = Network(name="Ethereum", chain_type="evm", chain_id=1, enabled=True)
    session.add(net)
    session.flush()

    w = Wallet(address="0xd8da6bf26964af9d7eed9e03e53415d37aa96045", name="vitalik")
    session.add(w)
    session.flush()

    amount = Decimal(5780441042197210512)
    snap = save_native_balance(session, w, net, amount, block_number=26343086)

    assert snap is not None
    assert isinstance(snap, BalanceSnapshot)
    assert snap.balance == amount
    assert isinstance(snap.balance, Decimal)
    assert snap.raw_balance == "5780441042197210512"
    assert snap.block_number == 26343086
    assert snap.taken_at is not None
    assert snap.taken_at.tzinfo is not None
    assert snap.taken_at.tzinfo == UTC
    assert snap.wallet_id == w.id
    assert snap.network_id == net.id


def test_save_native_balance_with_ids(session: Session):
    net = Network(name="Base", chain_type="evm", chain_id=8453, enabled=True)
    session.add(net)
    session.flush()

    w = Wallet(address="0x1111111111111111111111111111111111111111", name="alice")
    session.add(w)
    session.flush()

    snap = save_native_balance(session, w.id, net.id, Decimal(1000000000000000000), block_number=100)
    assert snap.wallet_id == w.id
    assert snap.network_id == net.id
    assert snap.balance == Decimal(1000000000000000000)


def test_save_native_balance_rejects_float(session: Session):
    net = Network(name="Optimism", chain_type="evm", chain_id=10, enabled=True)
    session.add(net)
    w = Wallet(address="0x2222222222222222222222222222222222222222")
    session.add(w)
    session.flush()

    with pytest.raises(TypeError, match="must be Decimal or int"):
        save_native_balance(session, w, net, 1.5)  # type: ignore
