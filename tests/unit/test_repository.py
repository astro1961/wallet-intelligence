"""Unit tests for database session and repository layer."""
from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.config import AppConfig, DatabaseSection
from app.database.models import Base, Wallet
from app.database.repository import GroupRepository, WalletRepository
from app.database.session import get_session, init_db


@pytest.fixture
def repo_session():
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


def test_wallet_repository_crud(repo_session: Session):
    repo = WalletRepository(repo_session)

    # Add
    w = repo.add(address="0xAbC0000000000000000000000000000000000001", name="Treasury")
    assert w.id is not None
    assert w.address == "0xabc0000000000000000000000000000000000001"
    assert w.address_raw == "0xAbC0000000000000000000000000000000000001"

    # Get by ID
    fetched = repo.get(w.id)
    assert fetched is not None
    assert fetched.name == "Treasury"

    # Get by Address
    fetched_addr = repo.get_by_address("0xabc0000000000000000000000000000000000001")
    assert fetched_addr is not None
    assert fetched_addr.id == w.id

    # Update
    updated = repo.update(w.id, name="Main Treasury")
    assert updated.name == "Main Treasury"

    # Archive
    archived = repo.archive(w.id, archived=True)
    assert archived.archived is True

    # List with filters
    active_list = repo.list(archived=False)
    assert len(active_list) == 0
    all_list = repo.list(archived=True)
    assert len(all_list) == 1


def test_group_repository_tree_and_cycle_prevention(repo_session: Session):
    repo = GroupRepository(repo_session)

    # Create root and children
    root = repo.create(name="Root")
    child = repo.create(name="Child", parent_id=root.id)
    grandchild = repo.create(name="Grandchild", parent_id=child.id)

    # Rename
    renamed = repo.rename(root.id, "Main Root")
    assert renamed.name == "Main Root"

    # Cycle prevention: cannot move root into child or grandchild
    with pytest.raises(ValueError, match="[Cc]ycle"):
        repo.move(root.id, child.id)

    with pytest.raises(ValueError, match="[Cc]ycle"):
        repo.move(root.id, grandchild.id)

    with pytest.raises(ValueError, match="[Cc]ycle"):
        repo.move(root.id, root.id)

    # Valid move: move grandchild directly under root
    moved = repo.move(grandchild.id, root.id)
    assert moved.parent_id == root.id


def test_delete_reassigning_wallets(repo_session: Session):
    group_repo = GroupRepository(repo_session)
    wallet_repo = WalletRepository(repo_session)

    root = group_repo.create(name="Farms")
    sub = group_repo.create(name="Farm 1", parent_id=root.id)

    w1 = wallet_repo.add(address="0x1111111111111111111111111111111111111111", group_id=sub.id)
    w2 = wallet_repo.add(address="0x2222222222222222222222222222222222222222", group_id=sub.id)

    # Delete sub group with reassignment to root
    group_repo.delete_reassigning_wallets(sub.id, target_group_id=root.id)

    # Sub group should be gone
    assert group_repo.get(sub.id) is None

    # Wallets must now belong to root group, not deleted
    reloaded_w1 = wallet_repo.get(w1.id)
    reloaded_w2 = wallet_repo.get(w2.id)
    assert reloaded_w1 is not None and reloaded_w1.group_id == root.id
    assert reloaded_w2 is not None and reloaded_w2.group_id == root.id


def test_session_init_and_context_manager(tmp_path: Path):
    db_file = tmp_path / "sess_test.db"
    cfg = AppConfig(database=DatabaseSection(path=str(db_file)))
    init_db(cfg)

    # Normal commit on success
    with get_session() as s:
        s.add(Wallet(address="0x4444444444444444444444444444444444444444", name="SessWallet"))

    with get_session() as s:
        w = s.query(Wallet).filter_by(address="0x4444444444444444444444444444444444444444").first()
        assert w is not None
        assert w.name == "SessWallet"

    # Rollback on error
    with pytest.raises(RuntimeError), get_session() as s:
        s.add(Wallet(address="0x5555555555555555555555555555555555555555", name="WillFail"))
        raise RuntimeError("Simulation error")

    with get_session() as s:
        w = s.query(Wallet).filter_by(address="0x5555555555555555555555555555555555555555").first()
        assert w is None
