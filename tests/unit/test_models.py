"""Unit tests for SQLAlchemy models, constraints, and data types."""
from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.database.models import (
    Activity,
    BalanceSnapshot,
    Base,
    DeFiPosition,
    Network,
    Note,
    Project,
    ProjectContract,
    ProjectTask,
    ProjectWallet,
    Provider,
    RpcEndpoint,
    SyncCursor,
    SyncJob,
    Token,
    Transaction,
    Wallet,
    WalletGroup,
    WalletNetwork,
    WalletRelation,
    WalletSocial,
    WalletTag,
    WalletTagLink,
)


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def test_all_22_models_present():
    models = [
        Wallet, WalletGroup, WalletTag, WalletTagLink, WalletSocial,
        WalletRelation, WalletNetwork, Network, RpcEndpoint, Project,
        ProjectContract, ProjectWallet, ProjectTask, Activity,
        Transaction, Token, BalanceSnapshot, DeFiPosition, Provider,
        SyncJob, SyncCursor, Note,
    ]
    assert len(models) == 22


def test_no_float_columns():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    insp = inspect(engine)
    for table_name in insp.get_table_names():
        for col in insp.get_columns(table_name):
            col_name = col["name"].lower()
            col_type = str(col["type"]).upper()
            if any(k in col_name for k in ("balance", "amount", "value", "price")):
                assert "FLOAT" not in col_type, f"Column {table_name}.{col_name} has float type {col_type}"


def test_wallet_address_normalization_and_unique_constraint(db_session: Session):
    w1 = Wallet(address="0xAbC1230000000000000000000000000000000001", chain_type="evm")
    db_session.add(w1)
    db_session.flush()

    assert w1.address == "0xabc1230000000000000000000000000000000001"
    assert w1.address_raw == "0xAbC1230000000000000000000000000000000001"

    # Duplicate address on same chain_type must fail
    w2 = Wallet(address="0xabc1230000000000000000000000000000000001", chain_type="evm")
    db_session.add(w2)
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()

    # Same address on solana chain_type is permitted
    w_sol = Wallet(address="0xabc1230000000000000000000000000000000001", chain_type="solana")
    db_session.add(w_sol)
    db_session.flush()
    assert w_sol.id is not None


def test_wallet_network_unique_constraint(db_session: Session):
    net = Network(name="Ethereum", chain_type="evm", chain_id=1)
    w = Wallet(address="0x1111111111111111111111111111111111111111")
    db_session.add_all([net, w])
    db_session.flush()

    wn1 = WalletNetwork(wallet_id=w.id, network_id=net.id)
    db_session.add(wn1)
    db_session.flush()

    wn2 = WalletNetwork(wallet_id=w.id, network_id=net.id)
    db_session.add(wn2)
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_foreign_key_rejection(db_session: Session):
    w = Wallet(address="0x2222222222222222222222222222222222222222", group_id=999999)
    db_session.add(w)
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_activity_dedupe_constraint(db_session: Session):
    net = Network(name="Base", chain_type="evm", chain_id=8453)
    w = Wallet(address="0x3333333333333333333333333333333333333333")
    db_session.add_all([net, w])
    db_session.flush()

    act1 = Activity(
        wallet_id=w.id,
        network_id=net.id,
        tx_hash="0xdeadbeef",
        log_index=0,
        activity_type="transfer",
        amount=Decimal("1.5"),
    )
    db_session.add(act1)
    db_session.flush()

    act2 = Activity(
        wallet_id=w.id,
        network_id=net.id,
        tx_hash="0xdeadbeef",
        log_index=0,
        activity_type="transfer",
    )
    db_session.add(act2)
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_wallet_address_attribute_assignment_normalization():
    w = Wallet(address="0xAbCdEf0000000000000000000000000000000001", chain_type="evm")
    assert w.address == "0xabcdef0000000000000000000000000000000001"
    assert w.address_raw == "0xAbCdEf0000000000000000000000000000000001"

    w.address = "0xABCDEF0000000000000000000000000000000002"
    assert w.address == "0xabcdef0000000000000000000000000000000002"
    assert w.address_raw == "0xABCDEF0000000000000000000000000000000002"

    w_sol = Wallet(address="So1anaAddrCaseSensitive1111", chain_type="solana")
    assert w_sol.address == "So1anaAddrCaseSensitive1111"
    w_sol.address = "So1anaNewAddressCaseSensitive2222"
    assert w_sol.address == "So1anaNewAddressCaseSensitive2222"
    assert w_sol.address_raw == "So1anaNewAddressCaseSensitive2222"


def test_project_contract_and_token_address_normalization():
    pc = ProjectContract(contract_address="0xAbCdEf0000000000000000000000000000000001", project_id=1, network_id=1)
    assert pc.contract_address == "0xabcdef0000000000000000000000000000000001"
    pc.contract_address = "0xABCDEF0000000000000000000000000000000002"
    assert pc.contract_address == "0xabcdef0000000000000000000000000000000002"

    tok = Token(contract_address="0xAbCdEf0000000000000000000000000000000001", network_id=1, symbol="TEST")
    assert tok.contract_address == "0xabcdef0000000000000000000000000000000001"
    tok.contract_address = "0xABCDEF0000000000000000000000000000000002"
    assert tok.contract_address == "0xabcdef0000000000000000000000000000000002"

