"""Independent acceptance gate — Stage 3C (multi-network correctness, silent-failure cleanup).

Owned by Hermes. Offline only.

Run from the project root:
    env -u WIT_DB_PATH .venv/bin/python -m pytest acceptance/gate_stage3c.py -q
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

VITALIK = "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045"

TMPL = r"""
import json, logging
from decimal import Decimal
import httpx

from app.config import load_config
from app.providers.base import ProviderStatus

cfg = load_config()
CALLS = []

def transport(handler):
    def _h(request: httpx.Request) -> httpx.Response:
        CALLS.append(str(request.url))
        return handler(request)
    return httpx.MockTransport(_h)

def client(handler, base_url="https://example.invalid"):
    return httpx.Client(transport=transport(handler), base_url=base_url, timeout=5)
"""


def run(code: str, tmp_path: Path) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if not k.startswith("WIT_")}
    env["WIT_DB_PATH"] = str(tmp_path / "db.sqlite")
    env["PYTHONPATH"] = str(ROOT)
    return subprocess.run([sys.executable, "-c", TMPL + code], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=180)


def out(p: subprocess.CompletedProcess) -> str:
    assert p.returncode == 0, f"script failed:\nSTDOUT:{p.stdout}\nSTDERR:{p.stderr[-2500:]}"
    return p.stdout.strip()


def get(o: str, tag: str) -> str:
    assert tag in o, f"{tag} missing in output:\n{o}"
    return o.split(tag)[1].split("\n")[0]


def test_evm_rpc_routes_each_network_to_its_own_endpoint(tmp_path):
    """A single RPC URL for every network silently returns another chain's balance."""
    code = r"""
from app.providers.evm_rpc import EvmRpcProvider

def handler(req):
    payload = json.loads(req.content)
    if payload["method"] == "eth_getBalance":
        host = req.url.host
        val = {"eth.llamarpc.com": "111", "arb1.arbitrum.io": "222"}.get(host, "999")
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": hex(int(val))})
    return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": "0x1"})

p = EvmRpcProvider(client=client(handler),
                   rpc_url="https://eth.llamarpc.com",
                   rpc_urls={"ethereum": "https://eth.llamarpc.com", "arbitrum": "https://arb1.arbitrum.io"})
eth = p.get_native_balance("0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045", "ethereum")
arb = p.get_native_balance("0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045", "arbitrum")
unknown = p.get_native_balance("0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045", "solana")
print("ETH:%s" % eth.data)
print("ARB:%s" % arb.data)
print("UNKNOWN_STATUS:%s" % unknown.status.name)
print("UNKNOWN_DATA:%s" % (unknown.data is None))
"""
    o = out(run(code, tmp_path))
    assert get(o, "ETH:") == "111", o
    assert get(o, "ARB:") == "222", (
        f"arbitrum did not go to its own endpoint (got {get(o, 'ARB:')}) — "
        "a single shared RPC returns another chain's balance"
    )
    assert get(o, "UNKNOWN_STATUS:") in {"ERROR", "UNSUPPORTED"}, get(o, "UNKNOWN_STATUS:")
    assert get(o, "UNKNOWN_DATA:").lower() == "true"


def test_blockscout_uses_per_network_chain_id(tmp_path):
    code = r"""
from app.providers.blockscout import BlockscoutProvider

def handler(req):
    return httpx.Response(200, json={"coin_balance": "5"})

p = BlockscoutProvider(client=client(handler, base_url="https://api.blockscout.com"),
                       api_key="k", chain_id=1)
p.get_native_balance("0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045", "arbitrum")
p.get_native_balance("0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045", "base")
print("URL1:" + CALLS[0])
print("URL2:" + CALLS[1])
"""
    o = out(run(code, tmp_path))
    assert "/42161/" in get(o, "URL1:"), get(o, "URL1:")
    assert "/8453/" in get(o, "URL2:"), get(o, "URL2:")


def test_factory_wires_rpc_per_network(tmp_path):
    """build registry from the real config.yaml and check no network shares Ethereum's RPC."""
    code = r"""
from app.config import load_config
from app.providers.factory import create_provider_registry

cfg = load_config()
reg = create_provider_registry(cfg)
rpc = [p for p in reg.providers if p.name == "evm_rpc"]
assert rpc, "no evm_rpc provider built"
p = rpc[0]
urls = getattr(p, "rpc_urls", None) or {}
print("NETS:" + ",".join(sorted(urls)))
print("COUNT:%d" % len(urls))
print("ETH:%s" % urls.get("ethereum"))
print("ARB:%s" % urls.get("arbitrum"))
print("DISTINCT:%s" % (len(set(urls.values())) == len(urls)))
"""
    o = out(run(code, tmp_path))
    assert int(get(o, "COUNT:")) >= 2, f"rpc_urls not wired: {o}"
    assert get(o, "ETH:") != get(o, "ARB:"), "two networks share one RPC endpoint"
    assert get(o, "DISTINCT:").lower() == "true", "duplicate RPC urls across networks"


def test_no_silent_except_pass():
    """Swallowing exceptions without a log line hides provider and import failures."""
    offenders = []
    pattern = re.compile(r"except[^:]*:\s*\n\s+pass\b")
    for p in (ROOT / "app").rglob("*.py"):
        text = p.read_text(encoding="utf-8")
        for m in pattern.finditer(text):
            line = text[: m.start()].count("\n") + 1
            offenders.append(f"{p.relative_to(ROOT)}:{line}")
    assert not offenders, "silent 'except: pass' blocks: " + ", ".join(offenders)


def test_silent_failures_are_visible(tmp_path):
    code = r"""
from app.config import load_config
import os
os.environ["WIT_REFRESH_INTERVAL"] = "not-a-number"
cfg = load_config()
print("INTERVAL:%s" % cfg.app.refresh_interval_seconds)
"""
    p = run(code, tmp_path)
    assert p.returncode == 0, p.stderr[-1000:]
    assert "INTERVAL:" in p.stdout, p.stdout
    assert "not-a-number" in (p.stdout + p.stderr) or "WIT_REFRESH_INTERVAL" in (p.stdout + p.stderr), (
        "invalid WIT_REFRESH_INTERVAL was ignored silently — it must produce a warning"
    )


def test_single_snapshot_timestamp_and_schema_matches(tmp_path):
    code = r"""
from app.database.models import BalanceSnapshot
cols = [c.name for c in BalanceSnapshot.__table__.columns]
print("COLS:" + ",".join(cols))
print("HAS_TAKEN:" + str("taken_at" in cols))
print("HAS_SNAPSHOT:" + str("snapshot_at" in cols))
"""
    o = out(run(code, tmp_path))
    assert get(o, "HAS_SNAPSHOT:").lower() == "true", o
    assert get(o, "HAS_TAKEN:").lower() == "false", (
        "two snapshot timestamps (taken_at + snapshot_at) — keep the spec's snapshot_at only"
    )
