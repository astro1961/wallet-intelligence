"""Independent acceptance gate — Stage 4C (shared transactions, rollback hygiene, empty state).

Bug found by a live run, not by a gate: two of your own wallets in one transfer.

Owned by Hermes. Offline.

Run from the project root:
    env -u WIT_DB_PATH .venv/bin/python -m pytest acceptance/gate_stage4c.py -q
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
from datetime import datetime, timezone
from decimal import Decimal

from app.config import load_config
from app.database.session import init_db, session_factory, session_scope
from app.database import models as m
from app.core.network_manager import ensure_networks_from_config
from app.core.sync_engine import SyncEngine
from app.providers.base import (DataProvider, ProviderResult, ProviderStatus,
                                TransactionItem, TransactionListResult)
from app.providers.registry import ProviderRegistry

cfg = load_config()
engine = init_db(cfg)
factory = session_factory(engine)
A = "0xd8da6bf26964af9d7eed9e03e53415d37aa96045"
B = "0xfb6916095ca1df60bb79ce92ce3ea74c37c5d359"

class TwoWallets(DataProvider):
    name = "fake"
    def get_native_balance(self, address, network):
        return ProviderResult(status=ProviderStatus.OK, data=Decimal("1"), source=self.name)
    def get_transactions(self, address, network, cursor=None):
        # one shared transaction between our own two wallets + one inbound for each
        shared = TransactionItem(hash="0xshared", from_address=A, to_address=B, value=Decimal("5"),
                                 block_number=100, timestamp=datetime(2026, 11, 1, tzinfo=timezone.utc),
                                 status="ok")
        own = TransactionItem(hash="0xown" + address[-4:], from_address=address,
                              to_address="0x1111111111111111111111111111111111111111",
                              value=Decimal("1"), block_number=101,
                              timestamp=datetime(2026, 11, 1, tzinfo=timezone.utc), status="ok")
        return ProviderResult(status=ProviderStatus.OK,
                              data=TransactionListResult(items=[shared, own], next_cursor=None),
                              source=self.name)
    def get_latest_block(self, network):
        return ProviderResult(status=ProviderStatus.OK, data=101, source=self.name)
    def health_check(self, network):
        return ProviderResult(status=ProviderStatus.OK, data=True, source=self.name)


def seed():
    with session_scope(factory) as s:
        ensure_networks_from_config(s, cfg)
        w1 = m.Wallet(address=A, name="A"); s.add(w1); s.flush()
        w2 = m.Wallet(address=B, name="B"); s.add(w2); s.flush()
        return w1.id, w2.id
"""


def run(code: str, tmp_path: Path) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if not k.startswith("WIT_")}
    env["WIT_DB_PATH"] = str(tmp_path / "db4c.sqlite")
    env["PYTHONPATH"] = str(ROOT)
    return subprocess.run([sys.executable, "-c", TMPL + code], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=240)


def out(p: subprocess.CompletedProcess) -> str:
    assert p.returncode == 0, f"script failed:\nSTDOUT:{p.stdout}\nSTDERR:{p.stderr[-3000:]}"
    return p.stdout.strip()


def get(o: str, tag: str) -> str:
    assert tag in o, f"{tag} missing in output:\n{o}"
    return o.split(tag)[1].split("\n")[0]


def test_transfer_between_own_wallets_syncs_on_both_sides(tmp_path):
    """A tx that touches two monitored wallets must be storable for each of them."""
    code = r"""
w1, w2 = seed()
sync = SyncEngine(factory, ProviderRegistry([TwoWallets()]), cfg)
r1 = sync.sync_wallet(w1, "ethereum")
r2 = sync.sync_wallet(w2, "ethereum")
print("R1:%s" % r1.status)
print("R2:%s" % r2.status)
print("R2_ERR:%s" % (r2.error or "")[:120])
with session_scope(factory) as s:
    print("TX:%d" % s.query(m.Transaction).count())
    print("ACT:%d" % s.query(m.Activity).count())
    print("SHARED:%d" % s.query(m.Transaction).filter(m.Transaction.tx_hash == "0xshared").count())
"""
    o = out(run(code, tmp_path))
    assert get(o, "R1:") == "ok", o
    assert get(o, "R2:") == "ok", (
        "second wallet failed on a shared transaction "
        f"(error: {get(o, 'R2_ERR:')}) — uniqueness must include wallet_id"
    )
    assert get(o, "SHARED:") == "2", "shared tx must exist per wallet, got " + get(o, "SHARED:")


def test_integrity_error_does_not_poison_the_session(tmp_path):
    """A failed flush must be rolled back and reported, not raise PendingRollback later."""
    code = r"""
w1, w2 = seed()
sync = SyncEngine(factory, ProviderRegistry([TwoWallets()]), cfg)
sync.sync_wallet(w1, "ethereum")
before = None
with session_scope(factory) as s:
    before = s.query(m.Transaction).count()
r2 = sync.sync_wallet(w2, "ethereum")
print("STATUS:%s" % r2.status)
print("ERROR_HAS_HINT:%s" % bool(r2.error))
after = None
with session_scope(factory) as s:
    after = s.query(m.Transaction).count()
print("BEFORE:%d" % before)
print("AFTER:%d" % after)
print("RECOVERED:%s" % (after >= before))
"""
    p = run(code, tmp_path)
    assert p.returncode == 0, f"session was left dirty:\n{p.stderr[-2000:]}"
    o = out(p)
    assert get(o, "RECOVERED:").lower() == "true", o


def test_transaction_uniqueness_includes_wallet(tmp_path):
    """The dedup index must allow the same (network, hash) for different wallets."""
    code = r"""
w1, w2 = seed()
sync = SyncEngine(factory, ProviderRegistry([TwoWallets()]), cfg)
sync.sync_wallet(w1, "ethereum")
sync.sync_wallet(w2, "ethereum")
with session_scope(factory) as s:
    rows = s.query(m.Transaction).filter(m.Transaction.tx_hash == "0xshared").all()
    print("WALLETS:" + ",".join(str(r.wallet_id) for r in rows))
    print("NETWORKS:" + ",".join(str(r.network_id) for r in rows))
"""
    o = out(run(code, tmp_path))
    wallets = get(o, "WALLETS:").split(",")
    assert len(set(wallets)) == 2, f"both rows share one wallet_id: {wallets}"


def test_repeat_sync_still_deduplicates_per_wallet(tmp_path):
    code = r"""
w1, w2 = seed()
sync = SyncEngine(factory, ProviderRegistry([TwoWallets()]), cfg)
sync.sync_wallet(w1, "ethereum"); sync.sync_wallet(w2, "ethereum")
before = None
with session_scope(factory) as s:
    before = (s.query(m.Transaction).count(), s.query(m.Activity).count())
r = sync.sync_wallet(w1, "ethereum")
after = None
with session_scope(factory) as s:
    after = (s.query(m.Transaction).count(), s.query(m.Activity).count())
print("ADDED:%d" % r.activities_added)
print("BEFORE:%s" % (before,))
print("AFTER:%s" % (after,))
"""
    o = out(run(code, tmp_path))
    assert get(o, "ADDED:") == "0", "re-sync duplicated rows: " + o
    assert get(o, "BEFORE:") == get(o, "AFTER:"), "re-sync changed row counts"


def test_activities_empty_state_has_no_raw_markup():
    """The empty state must render 'press s', not literal asterisks."""
    text = (ROOT / "app" / "ui" / "screens" / "activities.py").read_text(encoding="utf-8")
    import re

    msgs = re.findall(r'EMPTY_ACTIVITIES_MSG\s*=\s*"([^"]+)"', text)
    assert msgs, "EMPTY_ACTIVITIES_MSG not found"
    msg = msgs[0]
    assert "**" not in msg or "Static(" in text and "markup=True" in text, (
        f"empty state contains raw markup that renders as asterisks: {msg!r}"
    )
