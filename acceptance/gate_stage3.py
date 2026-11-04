"""Independent acceptance gate — Stage 3 (EVM data providers, offline/mock only).

Owned by Hermes. No network: every HTTP call goes through httpx.MockTransport.

Run from the project root:
    env -u WIT_DB_PATH .venv/bin/python -m pytest acceptance/gate_stage3.py -q
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

VITALIK = "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045"
TMPL = r"""
import json, logging, os, time
from decimal import Decimal
import httpx

from app.config import load_config
from app.database.session import init_db, session_factory, session_scope
from app.database import models as m
from app.providers.base import ProviderStatus

cfg = load_config()
engine = init_db(cfg)
factory = session_factory(engine)

CALLS = []

def transport(handler):
    def _h(request: httpx.Request) -> httpx.Response:
        CALLS.append(str(request.url))
        return handler(request)
    return httpx.MockTransport(_h)

def client(handler, base_url="https://api.blockscout.com"):
    return httpx.Client(transport=transport(handler), base_url=base_url, timeout=5)
"""


def run(code: str, tmp_path: Path) -> subprocess.CompletedProcess:
    import os
    env = {k: v for k, v in os.environ.items() if not k.startswith("WIT_")}
    env["WIT_DB_PATH"] = str(tmp_path / "db.sqlite")
    env["BLOCKSCOUT_API_KEY"] = "test-key-not-real"
    env["PYTHONPATH"] = str(ROOT)
    return subprocess.run([sys.executable, "-c", TMPL + code], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=180)


def out(p: subprocess.CompletedProcess) -> str:
    assert p.returncode == 0, f"script failed:\nSTDOUT:{p.stdout}\nSTDERR:{p.stderr[-2500:]}"
    return p.stdout.strip()


def get(o: str, tag: str) -> str:
    assert tag in o, f"{tag} missing in output:\n{o}"
    return o.split(tag)[1].split("\n")[0]


def test_provider_interface_and_explicit_unsupported(tmp_path):
    code = r"""
from app.providers.base import DataProvider, ProviderResult, ProviderStatus

class Minimal(DataProvider):
    name = "minimal"

p = Minimal(client=None, api_key=None) if True else None
res = p.get_token_balances("0xabc", "ethereum")
print("UNSUPPORTED:%s" % (res.status == ProviderStatus.UNSUPPORTED))
print("HAS_ERROR:%s" % bool(res.error))
print("METHODS:" + ",".join(sorted(m for m in dir(p) if m.startswith("get_") or m in ("health_check",))))
"""
    o = out(run(code, tmp_path))
    assert get(o, "UNSUPPORTED:") == "true", f"unsupported method must return UNSUPPORTED, got:\n{o}"
    assert get(o, "HAS_ERROR:") == "true", "unsupported result must carry a reason"
    for m in ("get_native_balance", "get_token_balances", "get_transactions",
              "get_transaction_details", "get_token_metadata", "get_latest_block", "health_check"):
        assert m in get(o, "METHODS:"), f"{m} missing from the provider interface"


def test_blockscout_native_balance_and_health(tmp_path):
    code = r"""
from app.providers.blockscout import BlockscoutProvider

def handler(req):
    if "/api/v2/addresses/" in req.url.path:
        return httpx.Response(200, json={"coin_balance": "5780441042197210512", "is_contract": True})
    return httpx.Response(200, json={"total_blocks": "26342704"})

p = BlockscoutProvider(client=client(handler), api_key="test-key-not-real", chain_id=1)
res = p.get_native_balance("0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045", "ethereum")
print("STATUS:%s" % res.status.name)
print("WEI:%s" % res.data)
print("DECIMAL:%s" % isinstance(res.data, Decimal))
h = p.health_check("ethereum")
print("HEALTH:%s" % h.status.name)
print("BLOCK:%s" % h.data)
print("URL:" + CALLS[0])
print("KEY_IN_QUERY:%s" % ("apikey=test-key-not-real" in CALLS[0]))
"""
    o = out(run(code, tmp_path))
    assert get(o, "STATUS:") == "OK"
    assert get(o, "WEI:") == "5780441042197210512"
    assert get(o, "DECIMAL:") == "True", "balance must be Decimal, not float/str"
    assert get(o, "HEALTH:") == "OK"
    assert get(o, "BLOCK:") == "26342704"
    assert "/api/v2/addresses/" in get(o, "URL:"), get(o, "URL:")
    assert get(o, "KEY_IN_QUERY:") == "True"


def test_blockscout_transactions_pagination(tmp_path):
    code = r"""
from app.providers.blockscout import BlockscoutProvider

state = {"n": 0}
def handler(req):
    state["n"] += 1
    if state["n"] == 1:
        assert "index" not in req.url.params
        return httpx.Response(200, json={
            "items": [{"hash": "0xaaa", "value": "1000", "block_number": 10,
                       "timestamp": "2026-11-04T17:56:35.000000Z", "status": "ok",
                       "from": {"hash": "0xfrom"}, "to": {"hash": "0xto"}}],
            "next_page_params": {"index": 154, "block_number": 10, "items_count": 50},
        })
    assert req.url.params.get("index") == "154", "pagination params not forwarded"
    return httpx.Response(200, json={"items": [], "next_page_params": None})

p = BlockscoutProvider(client=client(handler), api_key="k", chain_id=1)
r1 = p.get_transactions("0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045", "ethereum")
print("COUNT1:%d" % len(r1.data.items))
print("TX:%s" % r1.data.items[0].hash)
print("FROM:%s" % r1.data.items[0].from_address)
print("CURSOR:%s" % bool(r1.data.next_cursor))
r2 = p.get_transactions("0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045", "ethereum", cursor=r1.data.next_cursor)
print("COUNT2:%d" % len(r2.data.items))
print("CURSOR2:%s" % r2.data.next_cursor)
print("REQ_PARAMS:" + CALLS[1])
"""
    o = out(run(code, tmp_path))
    assert get(o, "COUNT1:") == "1", o
    assert get(o, "TX:") == "0xaaa"
    assert get(o, "FROM:") == "0xfrom"
    assert get(o, "CURSOR:") == "True", "next_page_params not exposed as cursor"
    assert get(o, "COUNT2:") == "0"
    assert get(o, "CURSOR2:") == "None"
    assert "index=154" in get(o, "REQ_PARAMS:"), get(o, "REQ_PARAMS:")


def test_evm_rpc_balance_and_block(tmp_path):
    code = r"""
from app.providers.evm_rpc import EvmRpcProvider

def handler(req):
    payload = json.loads(req.content)
    method = payload["method"]
    if method == "eth_getBalance":
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": "0x5035a1c5bd6bf8b90"})
    if method == "eth_blockNumber":
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": "0x191d2f0"})
    return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "error": {"code": -32601, "message": "method not found"}})

p = EvmRpcProvider(client=client(handler, base_url="https://rpc.example"), rpc_url="https://rpc.example")
b = p.get_native_balance("0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045", "ethereum")
print("BAL:%s" % b.data)
print("BAL_TYPE:%s" % type(b.data).__name__)
l = p.get_latest_block("ethereum")
print("BLOCK:%s" % l.data)
tok = p.get_token_metadata("0xtoken", "ethereum")
print("TOKEN_STATUS:%s" % tok.status.name)
print("METHODS:" + ",".join(sorted({json.loads(c.content)["method"] for c in []})) if False else "METHODS:skip")
"""
    o = out(run(code, tmp_path))
    assert get(o, "BAL:") == str(int("0x5035a1c5bd6bf8b90", 16)), o
    assert get(o, "BAL_TYPE:") == "Decimal"
    assert get(o, "BLOCK:") == str(int("0x191d2f0", 16))
    assert get(o, "TOKEN_STATUS:") in {"UNSUPPORTED", "ERROR"}, o


def test_retry_on_429_then_success(tmp_path):
    code = r"""
from app.providers.blockscout import BlockscoutProvider
state = {"n": 0}
def handler(req):
    state["n"] += 1
    if state["n"] == 1:
        return httpx.Response(429, json={"message": "rate limited"})
    return httpx.Response(200, json={"coin_balance": "42"})

p = BlockscoutProvider(client=client(handler), api_key="k", chain_id=1, max_retries=2, backoff_base=0.01)
t0 = time.monotonic()
r = p.get_native_balance("0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045", "ethereum")
print("STATUS:%s" % r.status.name)
print("DATA:%s" % r.data)
print("ATTEMPTS:%d" % state["n"])
print("FAST:%s" % ((time.monotonic() - t0) < 2))
"""
    o = out(run(code, tmp_path))
    assert get(o, "STATUS:") == "OK", o
    assert get(o, "DATA:") == "42"
    assert get(o, "ATTEMPTS:") == "2", f"expected one retry, got {get(o, 'ATTEMPTS:')}"
    assert get(o, "FAST:") == "True"


def test_error_result_does_not_leak_key(tmp_path):
    code = r"""
from app.providers.blockscout import BlockscoutProvider

records = []
class H(logging.Handler):
    def emit(self, record):
        records.append(record.getMessage())

root = logging.getLogger()
root.addHandler(H()); root.setLevel(logging.DEBUG)

def handler(req):
    return httpx.Response(500, json={"message": "boom"})

p = BlockscoutProvider(client=client(handler), api_key="super-secret-key-value", chain_id=1, max_retries=0)
r = p.get_native_balance("0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045", "ethereum")
root.removeHandler(root.handlers[-1])
print("STATUS:%s" % r.status.name)
print("HAS_ERROR:%s" % bool(r.error))
blob = json.dumps(records) + str(r.error)
print("LEAK:%s" % ("super-secret-key-value" in blob))
print("ERR:%s" % str(r.error)[:80])
"""
    o = out(run(code, tmp_path))
    assert get(o, "STATUS:") in {"ERROR", "RATE_LIMITED"}, o
    assert get(o, "HAS_ERROR:") == "True"
    assert get(o, "LEAK:") == "False", "API key leaked into logs/errors"


def test_registry_failover(tmp_path):
    code = r"""
from app.providers.base import DataProvider, ProviderResult, ProviderStatus
from app.providers.registry import ProviderRegistry

class Broken(DataProvider):
    name = "broken"
    def get_native_balance(self, address, network):
        return ProviderResult(status=ProviderStatus.ERROR, error="down")
    def health_check(self, network):
        return ProviderResult(status=ProviderStatus.ERROR, error="down")

class Good(DataProvider):
    name = "good"
    def get_native_balance(self, address, network):
        return ProviderResult(status=ProviderStatus.OK, data=Decimal("7"), source="good")
    def health_check(self, network):
        return ProviderResult(status=ProviderStatus.OK, data=True)

reg = ProviderRegistry([Broken(), Good()])
r = reg.get_native_balance("0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045", "ethereum")
print("STATUS:%s" % r.status.name)
print("DATA:%s" % r.data)
print("SOURCE:%s" % r.source)
"""
    o = out(run(code, tmp_path))
    assert get(o, "STATUS:") == "OK", f"registry did not fail over:\n{o}"
    assert get(o, "DATA:") == "7"
    assert get(o, "SOURCE:") == "good"


def test_balance_snapshot_persisted(tmp_path):
    code = r"""
from decimal import Decimal
from app.core.balance_manager import save_native_balance

with session_scope(factory) as s:
    net = m.Network(name="Ethereum", chain_type="evm", chain_id=1, enabled=True)
    s.add(net); s.flush()
    w = m.Wallet(address="0xd8da6bf26964af9d7eed9e03e53415d37aa96045", name="vitalik")
    s.add(w); s.flush()
    snap = save_native_balance(s, w, net, Decimal("5780441042197210512"), block_number=26343086)
    print("SNAP:%s" % (snap is not None))
    print("BALANCE:%s" % snap.balance)
    print("IS_DECIMAL:%s" % isinstance(snap.balance, Decimal))
    print("BLOCK:%s" % snap.block_number)
    print("UTC:%s" % (snap.taken_at.tzinfo is not None))
"""
    o = out(run(code, tmp_path))
    assert get(o, "SNAP:") == "True", o
    assert get(o, "BALANCE:") == "5780441042197210512"
    assert get(o, "IS_DECIMAL:") == "True"
    assert get(o, "BLOCK:") == "26343086"
    assert get(o, "UTC:") == "True"


FROZEN_REVISIONS = {
    "001_initial_schema.py": "d200e1c2e1b489404465f03a2f0a902d48c550a0f9a10e4c3daf67b9884c85db",
    "002_wallet_audit_log.py": "f5786ff12400a5d7cc8fb906e92489e20e9cbf1ebd0a4c579b128221ed804cd7",
}


def test_frozen_revisions_untouched():
    """Applied history must never be rewritten: schema changes go into a NEW revision."""
    import hashlib

    versions = ROOT / "migrations" / "versions"
    for name, expected in FROZEN_REVISIONS.items():
        path = versions / name
        assert path.is_file(), f"frozen revision disappeared: {name}"
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        assert actual == expected, (
            f"{name} was edited after being applied. Frozen revisions are immutable — "
            f"add a new revision (003_…) with op.add_column/op.create_table instead."
        )


def test_schema_matches_models_after_upgrade(tmp_path):
    """A DB built by migrations must carry the columns the models declare."""
    import os
    import sqlite3

    db = tmp_path / "schema.db"
    env = {k: v for k, v in os.environ.items() if not k.startswith("WIT_")}
    env["WIT_DB_PATH"] = str(db)
    env["PYTHONPATH"] = str(ROOT)
    p = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"],
                       cwd=ROOT, env=env, capture_output=True, text=True, timeout=240)
    assert p.returncode == 0, f"upgrade failed:\n{p.stdout}\n{p.stderr}"
    con = sqlite3.connect(db)
    live = {t: {r[1] for r in con.execute(f'PRAGMA table_info("{t}")')}
            for (t,) in con.execute("select name from sqlite_master where type='table'")}
    code = (
        "from app.database.models import Base\n"
        "for t, table in Base.metadata.tables.items():\n"
        "    print('T|%s|%s' % (t, ','.join(c.name for c in table.columns)))\n"
    )
    p2 = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env,
                        capture_output=True, text=True, timeout=120)
    assert p2.returncode == 0, p2.stderr
    missing = []
    for line in p2.stdout.strip().splitlines():
        if not line.startswith("T|"):
            continue
        _, table, cols = line.split("|", 2)
        if table not in live:
            missing.append(f"{table}: whole table absent")
            continue
        absent = [c for c in cols.split(",") if c not in live[table]]
        if absent:
            missing.append(f"{table}: {absent}")
    assert not missing, f"migrations do not produce the model schema: {missing}"


def test_providers_layer_is_isolated():
    prov = ROOT / "app" / "providers"
    assert prov.is_dir()
    offenders = []
    for p in prov.rglob("*.py"):
        t = p.read_text(encoding="utf-8")
        if "textual" in t or "from app.ui" in t:
            offenders.append(p.name)
    assert not offenders, f"providers must not import the UI: {offenders}"
    base = (prov / "base.py").read_text(encoding="utf-8")
    for name in ("unsupported", "ProviderStatus", "ProviderResult"):
        assert name.lower() in base.lower(), f"base.py lacks {name}"
