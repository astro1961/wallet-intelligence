"""Unit tests for GroupManager (tree operations, path, cycle detection, delete reassign)."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.group_manager import GroupManager
from app.database.models import Base, Wallet


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    sm = sessionmaker(bind=engine, expire_on_commit=False)
    with sm() as s:
        yield s


def test_create_and_get_group(session: Session):
    gm = GroupManager(session)
    root = gm.create_group("Exchanges", description="CEX wallets")
    assert root.id is not None
    assert root.name == "Exchanges"
    assert root.description == "CEX wallets"
    assert root.parent_id is None

    fetched = gm.get(root.id)
    assert fetched is not None
    assert fetched.name == "Exchanges"


def test_path(session: Session):
    gm = GroupManager(session)
    farm = gm.create_group("Farm")
    f1 = gm.create_group("Farm #1", parent_id=farm.id)
    deep = gm.create_group("Deep", parent_id=f1.id)

    assert gm.path(farm.id) == "Farm"
    assert gm.path(f1.id) == "Farm / Farm #1"
    assert gm.path(deep.id) == "Farm / Farm #1 / Deep"


def test_subtree_wallets(session: Session):
    gm = GroupManager(session)
    farm = gm.create_group("Farm")
    f1 = gm.create_group("Farm #1", parent_id=farm.id)
    f2 = gm.create_group("Farm #2", parent_id=farm.id)
    deep = gm.create_group("Deep", parent_id=f1.id)

    w1 = Wallet(address="0x1111111111111111111111111111111111111111", name="W1", group_id=farm.id)
    w2 = Wallet(address="0x2222222222222222222222222222222222222222", name="W2", group_id=f1.id)
    w3 = Wallet(address="0x3333333333333333333333333333333333333333", name="W3", group_id=deep.id)
    w4 = Wallet(address="0x4444444444444444444444444444444444444444", name="W4", group_id=f2.id)
    session.add_all([w1, w2, w3, w4])
    session.flush()

    farm_wallets = gm.subtree_wallets(farm.id)
    assert len(farm_wallets) == 4
    assert {w.name for w in farm_wallets} == {"W1", "W2", "W3", "W4"}

    f1_wallets = gm.subtree_wallets(f1.id)
    assert len(f1_wallets) == 2
    assert {w.name for w in f1_wallets} == {"W2", "W3"}

    deep_wallets = gm.subtree_wallets(deep.id)
    assert len(deep_wallets) == 1
    assert deep_wallets[0].name == "W3"


def test_move_group_and_cycle_prevention(session: Session):
    gm = GroupManager(session)
    farm = gm.create_group("Farm")
    f1 = gm.create_group("Farm #1", parent_id=farm.id)
    deep = gm.create_group("Deep", parent_id=f1.id)

    # Valid move: move deep under farm
    gm.move_group(deep.id, farm.id)
    assert gm.get(deep.id).parent_id == farm.id

    # Self-parent error
    with pytest.raises(ValueError, match="itself"):
        gm.move_group(farm.id, farm.id)

    # Cycle error: moving farm under its descendant f1
    with pytest.raises(ValueError, match="Cycle"):
        gm.move_group(farm.id, f1.id)


def test_delete_group_reassigns_to_parent(session: Session):
    gm = GroupManager(session)
    farm = gm.create_group("Farm")
    f1 = gm.create_group("Farm #1", parent_id=farm.id)
    deep = gm.create_group("Deep", parent_id=f1.id)

    w1 = Wallet(address="0x1111111111111111111111111111111111111111", name="W1", group_id=f1.id)
    session.add(w1)
    session.flush()

    # Delete f1 without reassign_to -> moves to parent (farm.id)
    gm.delete_group(f1.id)

    assert gm.get(f1.id) is None
    # deep was child of f1, now child of farm
    assert gm.get(deep.id).parent_id == farm.id
    # w1 was in f1, now in farm
    refreshed_w1 = session.get(Wallet, w1.id)
    assert refreshed_w1.group_id == farm.id


def test_delete_group_reassigns_to_explicit_group(session: Session):
    gm = GroupManager(session)
    g1 = gm.create_group("G1")
    g2 = gm.create_group("G2")
    sub = gm.create_group("Sub", parent_id=g1.id)

    w1 = Wallet(address="0x1111111111111111111111111111111111111111", name="W1", group_id=g1.id)
    session.add(w1)
    session.flush()

    gm.delete_group(g1.id, reassign_to=g2.id)

    assert gm.get(g1.id) is None
    assert gm.get(sub.id).parent_id == g2.id
    assert session.get(Wallet, w1.id).group_id == g2.id
