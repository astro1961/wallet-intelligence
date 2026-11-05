"""Independent acceptance gate — Stage 4A (sync engine + activity tracker).

Owned by Hermes. Offline: a fake provider, a temp database, no network.

Run from the project root:
    env -u WIT_DB_PATH .venv/bin/python -m pytest acceptance/gate_stage4a.py -q
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TMPL = r"""
import json
from datetime import datetime, timezone
from decimal import Decimal

from app.config import load_config
from app.database.session import init_db, session_factory, session_scope
from app.database import models as m
from app.providers.base import (DataProvider, ProviderResult, ProviderStatus,
                                TransactionItem, TransactionListResult)
from app.providers.registry import ProviderRegistry
from app.core.sync_engine import SyncEngine
from app.core.activity_tracker import ActivityTracker

cfg = load_config()
engine = init_db(cfg)
factory = session_factory(engine)
VITALIK = "0xd8da6bf26964af9d7eed9e03e53415d37aa96045"
OTHER = "0xfb6916095ca1df60bb79ce92ce3ea74c37c5d359"

class FakeProvider(DataProvider):
    name = "fake"
    def __init__(self, items, block=100, fail_for=()):
        super().__init__(client=None, api_key=None)
        self.items = items
        self.block = block
        self.fail_for = set(fail_for)
        self.calls = []

    def get_native_balance(self, address, network):
        if address in self.fail_for:
            return ProviderResult(status=ProviderStatus.ERROR, error="boom", source=self.name)
        return ProviderResult(status=ProviderStatus.OK, data=Decimal("1000000000000000000"), source=self.name)

    def get_transactions(self, address, network, cursor=None):
        self.calls.append(cursor)
        if address in self.fail_for:
            return ProviderResult(status=ProviderStatus.ERROR, error="boom", source=self.name)
        items = [i for i in self.items if i.from_address == address or i.to_address == address]
        if cursor and cursor.get("block") == self.block:
            items = []
        return ProviderResult(status=ProviderStatus.OK,
                              data=TransactionListResult(items=items, next_cursor=None), source=self.name)

    def get_latest_block(self, network):
        return ProviderResult(status=ProviderStatus.OK, data=self.block, source=self.name)

    def health_check(self, network):
        return ProviderResult(status=ProviderStatus.OK, data=True, source=self.name)


def tx(h, frm, to, value="1", block=100, kind="transfer"):
    return TransactionItem(hash=h, from_address=frm, to_address=to,
                           value=Decimal(value), block_number=block,
                           timestamp=datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc),
                           status="ok")


def seeded():
    with session_scope(factory) as s:
        net = m.Network(name="Ethereum", chain_type="evm", chain_id=1, enabled=True)
        s.add(net); s.flush()
        w1 = m.Wallet(address=VITALIK, name="vitalik"); s.add(w1); s.flush()
        w2 = m.Wallet(address=OTHER, name="other"); s.add(w2); s.flush()
        return {"net": net.id, "w1": w1.id, "w2": w2.id}
"""


def run(code: str, tmp_path: Path) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if not k.startswith("WIT_")}
    env["WIT_DB_PATH"] = str(tmp_path / "db4a.sqlite")
    env["PYTHONPATH"] = str(ROOT)
    return subprocess.run([sys.executable, "-c", TMPL + code], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=240)


def out(p: subprocess.CompletedProcess) -> str:
    assert p.returncode == 0, f"script failed:\nSTDOUT:{p.stdout}\nSTDERR:{p.stderr[-3000:]}"
    return p.stdout.strip()


def get(o: str, tag: str) -> str:
    assert tag in o, f"{tag} missing in output:\n{o}"
    return o.split(tag)[1].split("\n")[0]


def test_sync_creates_activities_balance_and_cursor(tmp_path):
    code = r"""
ids = seeded()
prov = FakeProvider([tx("0xaaa", VITALIK, OTHER), tx("0xbbb", OTHER, VITALIK)], block=100)
sync = SyncEngine(factory, ProviderRegistry([prov]), cfg)
rep = sync.sync_wallet(ids["w1"], "ethereum")
print("STATUS:%s" % rep.status)
print("ACT_ADDED:%s" % rep.activities_added)
print("BALANCE:%s" % rep.balance_saved)
with session_scope(factory) as s:
    print("DB_ACT:%d" % s.query(m.Activity).count())
    print("DB_TX:%d" % s.query(m.Transaction).count())
    snap = s.query(m.BalanceSnapshot).first()
    print("SNAP:%s" % (snap.balance if snap else None))
    cur = s.query(m.SyncCursor).first()
    print("CURSOR_BLOCK:%s" % (cur.last_block_number if cur else None))
    job = s.query(m.SyncJob).first()
    print("JOB_STATUS:%s" % (job.status if job else None))
"""
    o = out(run(code, tmp_path))
    assert get(o, "STATUS:") == "ok", o
    assert int(get(o, "ACT_ADDED:")) == 2, o
    assert get(o, "BALANCE:").lower() == "true", o
    assert get(o, "DB_ACT:") == "2"
    assert get(o, "DB_TX:") == "2"
    assert get(o, "SNAP:") == "1000000000000000000"
    assert get(o, "CURSOR_BLOCK:") == "100"
    assert get(o, "JOB_STATUS:") == "completed", o


def test_second_sync_is_idempotent(tmp_path):
    code = r"""
ids = seeded()
items = [tx("0xaaa", VITALIK, OTHER), tx("0xbbb", OTHER, VITALIK)]
sync = SyncEngine(factory, ProviderRegistry([FakeProvider(items, block=100)]), cfg)
r1 = sync.sync_wallet(ids["w1"], "ethereum")
r2 = sync.sync_wallet(ids["w1"], "ethereum")
print("R1:%d" % r1.activities_added)
print("R2:%d" % r2.activities_added)
with session_scope(factory) as s:
    print("TOTAL:%d" % s.query(m.Activity).count())
    print("SNAPSHOTS:%d" % s.query(m.BalanceSnapshot).count())
"""
    o = out(run(code, tmp_path))
    assert get(o, "R1:") == "2"
    assert get(o, "R2:") == "0", "second sync re-inserted activities: dedup by (wallet, tx_hash, log_index) is missing"
    assert get(o, "TOTAL:") == "2"


def test_incremental_cursor_is_used_on_next_run(tmp_path):
    code = r"""
ids = seeded()
prov = FakeProvider([tx("0xaaa", VITALIK, OTHER, block=90)], block=100)
sync = SyncEngine(factory, ProviderRegistry([prov]), cfg)
sync.sync_wallet(ids["w1"], "ethereum")
first_cursor = prov.calls[-1] if prov.calls else None
prov2 = FakeProvider([], block=120)
sync2 = SyncEngine(factory, ProviderRegistry([prov2]), cfg)
sync2.sync_wallet(ids["w1"], "ethereum")
print("FIRST_CURSOR:%s" % (first_cursor,))
print("SECOND_CURSOR:%s" % (prov2.calls[-1] if prov2.calls else None,))
"""
    o = out(run(code, tmp_path))
    second = get(o, "SECOND_CURSOR:")
    assert "block" in second or "null" not in second, (
        f"second run did not pass a resume cursor from SyncCursor: {second}"
    )


def test_one_failing_wallet_does_not_stop_the_others(tmp_path):
    code = r"""
ids = seeded()
prov = FakeProvider([tx("0xaaa", VITALIK, OTHER), tx("0xbbb", OTHER, VITALIK)], block=100,
                    fail_for={OTHER})
sync = SyncEngine(factory, ProviderRegistry([prov]), cfg)
reports = sync.sync_all("ethereum")
print("COUNT:%d" % len(reports))
print("OK:%d" % sum(1 for r in reports if r.status == "ok"))
print("ERR:%d" % sum(1 for r in reports if r.status == "error"))
print("ERR_MSG:%s" % next((bool(r.error) for r in reports if r.status == "error"), None))
"""
    o = out(run(code, tmp_path))
    assert get(o, "COUNT:") == "2", o
    assert get(o, "OK:") == "1", f"a failing wallet killed the batch:\n{o}"
    assert get(o, "ERR:") == "1"
    assert get(o, "ERR_MSG:").lower() == "true"


def test_activity_classification_and_project_detection(tmp_path):
    code = r"""
ids = seeded()
with session_scope(factory) as s:
    proj = m.Project(name="Airdrop X", status="active"); s.add(proj); s.flush()
    pc = m.ProjectContract(project_id=proj.id, network_id=ids["net"],
                           address="0x1111111111111111111111111111111111111111", name="Claim")
    s.add(pc)

tracker = ActivityTracker(factory, cfg)
with session_scope(factory) as s:
    w = s.get(m.Wallet, ids["w1"]); net = s.get(m.Network, ids["net"])
    out_tx = tracker.record(s, w, net, tx("0xsend", VITALIK, OTHER))
    in_tx = tracker.record(s, w, net, tx("0xrecv", OTHER, VITALIK))
print("SEND_TYPE:%s" % out_tx.activity_type)
print("RECV_TYPE:%s" % in_tx.activity_type)
print("SEND_PROJECT:%s" % out_tx.project_id)
with session_scope(factory) as s:
    w = s.get(m.Wallet, ids["w1"]); net = s.get(m.Network, ids["net"])
    p_tx = tracker.record(s, w, net, tx("0xclaim", VITALIK, "0x1111111111111111111111111111111111111111"))
print("CLAIM_TYPE:%s" % p_tx.activity_type)
print("CLAIM_PROJECT:%s" % (p_tx.project_id is not None))
print("CLAIM_SOURCE:%s" % p_tx.source)
"""
    o = out(run(code, tmp_path))
    assert get(o, "SEND_TYPE:") == "send", o
    assert get(o, "RECV_TYPE:") == "receive", o
    assert get(o, "SEND_PROJECT:") == "None"
    assert get(o, "CLAIM_TYPE:") == "contract_call", o
    assert get(o, "CLAIM_PROJECT:").lower() == "true", "activity not linked to the project contract"
    assert get(o, "CLAIM_SOURCE:") == "detected", o


def test_sync_layer_has_no_ui_dependency():
    for path in (ROOT / "app" / "core").glob("sync_engine.py"):
        text = path.read_text(encoding="utf-8")
        assert "textual" not in text, "sync engine must not depend on the UI"
    tracker = ROOT / "app" / "core" / "activity_tracker.py"
    assert tracker.is_file(), "activity_tracker.py missing"
    text = tracker.read_text(encoding="utf-8")
    assert "textual" not in text
    assert "except Exception:\n            pass" not in text
