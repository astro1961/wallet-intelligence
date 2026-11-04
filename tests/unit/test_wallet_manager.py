"""Unit tests for WalletManager (CRUD, tags, socials, audit history, search, filters)."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.group_manager import GroupManager
from app.core.wallet_manager import WalletFilters, WalletManager
from app.database.models import Base


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    sm = sessionmaker(bind=engine, expire_on_commit=False)
    with sm() as s:
        yield s


def test_create_and_get_wallet(session: Session):
    wm = WalletManager(session)
    w = wm.create_wallet(
        address="0xfb6916095ca1df60bb79ce92ce3ea74c37c5d359",
        name="Alpha",
        tags=["hot", "defi"],
        notes="primary trading wallet",
        socials={"twitter": "https://x.com/alpha"},
    )
    assert w.id is not None
    assert w.name == "Alpha"
    assert w.notes == "primary trading wallet"
    assert len(w.tags) == 2
    assert {t.name for t in w.tags} == {"hot", "defi"}
    assert len(w.socials) == 1
    assert w.socials[0].platform == "twitter"
    assert w.socials[0].url == "https://x.com/alpha"

    fetched = wm.get_wallet(w.id)
    assert fetched is not None
    assert fetched.id == w.id


def test_update_wallet_and_audit_history(session: Session):
    wm = WalletManager(session)
    w = wm.create_wallet(
        address="0xfb6916095ca1df60bb79ce92ce3ea74c37c5d359",
        name="Main",
        notes="initial notes",
    )

    wm.update_wallet(w.id, name="Main Renamed", notes="updated notes")
    wm.archive_wallet(w.id, archived=True)

    hist = wm.history(w.id)
    assert len(hist) == 3

    assert hist[0].field == "name"
    assert hist[0].old_value == "Main"
    assert hist[0].new_value == "Main Renamed"

    assert hist[1].field == "notes"
    assert hist[1].old_value == "initial notes"
    assert hist[1].new_value == "updated notes"

    assert hist[2].field == "archived"
    assert hist[2].old_value in ("False", "false")
    assert hist[2].new_value in ("True", "true")

    # Non-editable field raises ValueError
    with pytest.raises(ValueError, match="non-editable"):
        wm.update_wallet(w.id, invalid_field="boom")


def test_search(session: Session):
    wm = WalletManager(session)
    gm = GroupManager(session)
    farm = gm.create_group("Farm")

    wm.create_wallet(
        address="0xfb6916095ca1df60bb79ce92ce3ea74c37c5d359",
        name="Alpha",
        group_id=farm.id,
        tags=["hot"],
    )
    wm.create_wallet(
        address="0xfb6916095ca1df60bb79ce92ce3ea74c37c5d35a",
        name="Beta",
        tags=["cold"],
    )
    wm.create_wallet(
        address="0xfb6916095ca1df60bb79ce92ce3ea74c37c5d35b",
        name="Gamma",
    )

    # Search by name
    res_name = wm.search("alp")
    assert len(res_name) == 1
    assert res_name[0].name == "Alpha"

    # Search by address
    res_addr = wm.search("d35a")
    assert len(res_addr) == 1
    assert res_addr[0].name == "Beta"

    # Search by tag
    res_tag = wm.search("cold")
    assert len(res_tag) == 1
    assert res_tag[0].name == "Beta"


def test_filters(session: Session):
    wm = WalletManager(session)
    gm = GroupManager(session)
    farm = gm.create_group("Farm")
    sub = gm.create_group("Sub", parent_id=farm.id)

    wm.create_wallet(
        address="0xfb6916095ca1df60bb79ce92ce3ea74c37c5d359",
        name="Alpha",
        group_id=farm.id,
        tags=["hot"],
    )
    wm.create_wallet(
        address="0xfb6916095ca1df60bb79ce92ce3ea74c37c5d35a",
        name="Beta",
        group_id=sub.id,
        tags=["cold"],
    )
    w3 = wm.create_wallet(
        address="0xfb6916095ca1df60bb79ce92ce3ea74c37c5d35b",
        name="Gamma",
    )
    wm.archive_wallet(w3.id)

    # Filter with subgroups
    res_grp = wm.list_wallets(WalletFilters(group_id=farm.id, include_subgroups=True, archived=None))
    assert {w.name for w in res_grp} == {"Alpha", "Beta"}

    # Filter without subgroups
    res_no_sub = wm.list_wallets(WalletFilters(group_id=farm.id, include_subgroups=False, archived=None))
    assert {w.name for w in res_no_sub} == {"Alpha"}

    # Filter by tag
    res_tag = wm.list_wallets(WalletFilters(tag="hot", archived=None))
    assert {w.name for w in res_tag} == {"Alpha"}

    # Filter archived
    res_archived = wm.list_wallets(WalletFilters(archived=True))
    assert len(res_archived) == 1
    assert res_archived[0].name == "Gamma"
