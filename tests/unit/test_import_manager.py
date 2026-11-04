"""Unit tests for ImportManager (CSV, TXT, JSON, deduplication, row isolation, update mode)."""
from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.import_manager import ImportManager
from app.database.models import Base, Network, Wallet


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    sm = sessionmaker(bind=engine, expire_on_commit=False)
    with sm() as s:
        # Seed test networks
        s.add_all([
            Network(name="Ethereum", chain_type="evm", chain_id=1),
            Network(name="Arbitrum", chain_type="evm", chain_id=42161),
        ])
        s.flush()
        yield s


def test_detect_format(session: Session):
    im = ImportManager(session)
    csv_text = "address,name,group,network,tags\n0xfb6916095ca1df60bb79ce92ce3ea74c37c5d359,W1,G,ethereum,hot"
    txt_text = "0xfb6916095ca1df60bb79ce92ce3ea74c37c5d359,W1\n# comment\n0xfb6916095ca1df60bb79ce92ce3ea74c37c5d35a"
    json_text = json.dumps([{"address": "0xfb6916095ca1df60bb79ce92ce3ea74c37c5d359", "name": "W1"}])

    assert im.detect_format(csv_text) == "csv"
    assert im.detect_format(txt_text) == "txt"
    assert im.detect_format(json_text) == "json"


def test_csv_preview_and_apply(session: Session):
    im = ImportManager(session)
    csv_text = (
        "address,name,group,network,tags\n"
        "0xfb6916095ca1df60bb79ce92ce3ea74c37c5d359,W1,Farm #1,ethereum,farming;hot\n"
        "0xfb6916095ca1df60bb79ce92ce3ea74c37c5d359,W1_dup,Farm #1,ethereum,farming\n"
        "0xbadaddr,W2,Farm #1,ethereum,farming\n"
        "0xfb6916095ca1df60bb79ce92ce3ea74c37c5d35a,W3,Farm #2,arbitrum,cold\n"
    )

    prev = im.preview(csv_text, fmt="csv")
    assert prev.format == "csv"
    assert prev.new_count == 2
    assert prev.duplicate_count == 1
    assert prev.error_count == 1

    # Preview must NOT write to DB
    assert session.query(Wallet).count() == 0

    report = im.apply(prev, mode="add_only")
    assert report.added == 2
    assert report.skipped == 2
    assert len(report.errors) == 1
    assert session.query(Wallet).count() == 2

    # Second run is idempotent
    prev2 = im.preview(csv_text, fmt="csv")
    report2 = im.apply(prev2, mode="add_only")
    assert report2.added == 0
    assert report2.skipped == 4
    assert session.query(Wallet).count() == 2


def test_txt_and_json_import(session: Session):
    im = ImportManager(session)
    txt_text = (
        "0xfb6916095ca1df60bb79ce92ce3ea74c37c5d359,Alpha\n"
        "# ignored comment\n"
        "0xfb6916095ca1df60bb79ce92ce3ea74c37c5d35a,Beta\n"
        "0xbad_address\n"
    )

    prev_txt = im.preview(txt_text)
    assert prev_txt.format == "txt"
    assert prev_txt.new_count == 2
    assert prev_txt.error_count == 1

    rep_txt = im.apply(prev_txt, mode="add_only")
    assert rep_txt.added == 2
    assert len(rep_txt.errors) == 1

    # JSON with duplicate in batch
    js_text = json.dumps([
        {"address": "0xfb6916095ca1df60bb79ce92ce3ea74c37c5d359", "name": "Alpha"},
        {"address": "0xfb6916095ca1df60bb79ce92ce3ea74c37c5d359", "name": "AlphaDup"},
    ])
    prev_js = im.preview(js_text)
    assert prev_js.format == "json"
    assert prev_js.new_count == 1
    assert prev_js.duplicate_count == 1
    assert prev_js.error_count == 0


def test_update_mode_and_row_isolation(session: Session):
    im = ImportManager(session)
    base = "0xfb6916095ca1df60bb79ce92ce3ea74c37c5d359,Original\n"
    im.apply(im.preview(base, fmt="txt"), mode="add_only")

    w = session.query(Wallet).one()
    assert w.name == "Original"

    # Add-only ignores existing
    upd = "0xfb6916095ca1df60bb79ce92ce3ea74c37c5d359,Renamed\n"
    rep_add = im.apply(im.preview(upd, fmt="txt"), mode="add_only")
    assert rep_add.added == 0
    assert rep_add.skipped == 1
    assert session.query(Wallet).one().name == "Original"

    # Update mode modifies existing
    rep_upd = im.apply(im.preview(upd, fmt="txt"), mode="update")
    assert rep_upd.updated == 1
    assert session.query(Wallet).one().name == "Renamed"

    # Row isolation: bad rows do not abort the batch
    batch = "".join(f"0x{i+1:040x},Bulk{i:03d}\n" for i in range(10))
    batch += "0xbroken1,Bad1\n0xbroken2,Bad2\n"
    rep_batch = im.apply(im.preview(batch, fmt="txt"), mode="add_only")
    assert rep_batch.added == 10
    assert len(rep_batch.errors) == 2


def test_unknown_network_rejection(session: Session):
    im = ImportManager(session)
    csv_text = (
        "address,name,group,network,tags\n"
        "0xfb6916095ca1df60bb79ce92ce3ea74c37c5d359,W1,Farm #1,nonexistent_net,farming\n"
    )
    prev = im.preview(csv_text, fmt="csv")
    assert prev.error_count == 1
    assert "Unknown network" in (prev.rows[0].error or "")
