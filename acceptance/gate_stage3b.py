"""Independent acceptance gate — Stage 3B (Etherscan v2 failover provider).

Owned by Hermes. Offline only: every HTTP call goes through httpx.MockTransport.

Run from the project root:
    env -u WIT_DB_PATH .venv/bin/python -m pytest acceptance/gate_stage3b.py -q
"""
from __future__ import annotations

import os
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
from app.database.session import init_db, session_factory
from app.providers.base import ProviderStatus

cfg = load_config()
CALLS = []

def transport(handler):
    def _h(request: httpx.Request) -> httpx.Response:
        CALLS.append(str(request.url))
        return handler(request)
    return httpx.MockTransport(_h)

def client(handler, base_url="https://api.etherscan.io/v2/api"):
    return httpx.Client(transport=transport(handler), base_url=base_url, timeout=5)
"""


def run(code: str, tmp_path: Path, extra_env: dict | None = None) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if not k.startswith("WIT_")}
    env["WIT_DB_PATH"] = str(tmp_path / "db.sqlite")
    env["ETHERSCAN_API_KEY"] = "test-key-not-real"
    env["PYTHONPATH"] = str(ROOT)
    env.update(extra_env or {})
    return subprocess.run([sys.executable, "-c", TMPL + code], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=180)


def out(p: subprocess.CompletedProcess) -> str:
    assert p.returncode == 0, f"script failed:\nSTDOUT:{p.stdout}\nSTDERR:{p.stderr[-2500:]}"
    return p.stdout.strip()


def get(o: str, tag: str) -> str:
    assert tag in o, f"{tag} missing in output:\n{o}"
    return o.split(tag)[1].split("\n")[0]


def test_etherscan_native_balance(tmp_path):
    code = r"""
from app.providers.etherscan import EtherscanProvider

def handler(req):
    return httpx.Response(200, json={"status": "1", "message": "OK", "result": "5780441042197210512"})

p = EtherscanProvider(client=client(handler), api_key="test-key-not-real", default_chain_id=1)
r = p.get_native_balance("0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045", "ethereum")
print("STATUS:%s" % r.status.name)
print("WEI:%s" % r.data)
print("TYPE:%s" % type(r.data).__name__)
print("URL:" + CALLS[0])
"""
    o = out(run(code, tmp_path))
    assert get(o, "STATUS:") == "OK", o
    assert get(o, "WEI:") == "5780441042197210512"
    assert get(o, "TYPE:") == "Decimal"
    url = get(o, "URL:")
    for frag in ("module=account", "action=balance", "chainid=1", "apikey=test-key-not-real"):
        assert frag in url, f"{frag} missing in {url}"


def test_etherscan_transactions_and_pagination(tmp_path):
    code = r"""
from app.providers.etherscan import EtherscanProvider

state = {"n": 0}
def handler(req):
    state["n"] += 1
    page = req.url.params.get("page")
    if state["n"] == 1:
        assert page is None or page == "1", page
        return httpx.Response(200, json={"status": "1", "message": "OK", "result": [
            {"hash": "0xaaa", "from": "0xfrom", "to": "0xto", "value": "1000",
             "blockNumber": "26343086", "timeStamp": "1762277795", "isError": "0",
             "gasUsed": "21000", "gasPrice": "1000000000"},
        ]})
    assert page == "2", "cursor page not forwarded"
    return httpx.Response(200, json={"status": "1", "message": "OK", "result": []})

p = EtherscanProvider(client=client(handler), api_key="k", default_chain_id=1, page_size=1)
r1 = p.get_transactions("0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045", "ethereum")
print("COUNT1:%d" % len(r1.data.items))
print("HASH:%s" % r1.data.items[0].hash)
print("FROM:%s" % r1.data.items[0].from_address)
print("VALUE:%s" % r1.data.items[0].value)
print("BLOCK:%s" % r1.data.items[0].block_number)
print("STATUS_OK:%s" % (r1.data.items[0].status == "ok"))
print("TS:%s" % (r1.data.items[0].timestamp.year))
print("CURSOR:%s" % bool(r1.data.next_cursor))
r2 = p.get_transactions("0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045", "ethereum", cursor=r1.data.next_cursor)
print("COUNT2:%d" % len(r2.data.items))
"""
    o = out(run(code, tmp_path))
    assert get(o, "COUNT1:") == "1", o
    assert get(o, "HASH:") == "0xaaa"
    assert get(o, "FROM:") == "0xfrom"
    assert get(o, "VALUE:") == "1000"
    assert get(o, "BLOCK:") == "26343086"
    assert get(o, "STATUS_OK:").lower() == "true"
    assert get(o, "TS:") == "2025", f"unix timestamp not converted: {get(o, 'TS:')}"
    assert get(o, "CURSOR:").lower() == "true"
    assert get(o, "COUNT2:") == "0"


def test_etherscan_rate_limit_is_not_success(tmp_path):
    """Etherscan signals throttling with HTTP 200 + status=0 — must not look like success."""
    code = r"""
from app.providers.etherscan import EtherscanProvider

def handler(req):
    return httpx.Response(200, json={"status": "0", "message": "NOTOK",
                                     "result": "Max rate limit reached, please use API Key"})

p = EtherscanProvider(client=client(handler), api_key="k", default_chain_id=1, max_retries=0)
r = p.get_native_balance("0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045", "ethereum")
print("STATUS:%s" % r.status.name)
print("DATA:%s" % (r.data is None))
print("HAS_ERROR:%s" % bool(r.error))
"""
    o = out(run(code, tmp_path))
    assert get(o, "STATUS:") == "RATE_LIMITED", f"200+status=0 must map to RATE_LIMITED, got {o}"
    assert get(o, "DATA:").lower() == "true", "no partial data on throttle"
    assert get(o, "HAS_ERROR:").lower() == "true"


def test_etherscan_health_and_chain_mapping(tmp_path):
    code = r"""
from app.providers.etherscan import EtherscanProvider

def handler(req):
    return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": "0x191d2f0"})

p = EtherscanProvider(client=client(handler), api_key="k", default_chain_id=1)
h = p.health_check("polygon")
print("STATUS:%s" % h.status.name)
print("BLOCK:%s" % h.data)
print("URL:" + CALLS[0])
b = p.get_native_balance("0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045", "base")
"""
    o = out(run(code, tmp_path))
    url = get(o, "URL:")
    assert "chainid=137" in url, f"polygon must map to chain 137, got {url}"
    assert get(o, "BLOCK:") == "26342000" or get(o, "BLOCK:").isdigit(), o


def test_etherscan_no_key_leak(tmp_path):
    code = r"""
from app.providers.etherscan import EtherscanProvider

records = []
class H(logging.Handler):
    def emit(self, record):
        records.append(record.getMessage())
root = logging.getLogger(); root.addHandler(H()); root.setLevel(logging.DEBUG)

def handler(req):
    return httpx.Response(401, json={"status": "0", "message": "NOTOK", "result": "Invalid API Key"})

p = EtherscanProvider(client=client(handler), api_key="super-secret-key-value", default_chain_id=1, max_retries=0)
r = p.get_native_balance("0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045", "ethereum")
root.removeHandler(root.handlers[-1])
print("STATUS:%s" % r.status.name)
print("LEAK:%s" % ("super-secret-key-value" in (json.dumps(records) + str(r.error))))
"""
    o = out(run(code, tmp_path))
    assert get(o, "STATUS:") in {"ERROR", "RATE_LIMITED"}, o
    assert get(o, "LEAK:").lower() == "false", "key leaked"


def test_etherscan_in_registry_after_blockscout(tmp_path):
    code = r"""
from app.providers.factory import create_provider_registry

reg = create_provider_registry(cfg)
names = [p.name for p in reg.providers]
print("NAMES:" + ",".join(names))
print("HAS_ETHERSCAN:%s" % ("etherscan" in names))
print("ORDER_OK:%s" % (names.index("blockscout") < names.index("etherscan") if "etherscan" in names else False))
r = reg.get_native_balance("0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045", "ethereum", allow_network=False) if False else None
"""
    o = out(run(code, tmp_path))
    assert get(o, "HAS_ETHERSCAN:").lower() == "true", f"ETHERSCAN_API_KEY set but provider missing: {o}"
    assert get(o, "ORDER_OK:").lower() == "true", "Etherscan must be a failover, i.e. after Blockscout"


def test_failover_between_real_providers(tmp_path):
    code = r"""
from app.providers.blockscout import BlockscoutProvider
from app.providers.etherscan import EtherscanProvider
from app.providers.registry import ProviderRegistry

def dead(req):
    return httpx.Response(500, json={"message": "boom"})

def alive(req):
    return httpx.Response(200, json={"status": "1", "message": "OK", "result": "12345"})

bs = BlockscoutProvider(client=client(dead, base_url="https://api.blockscout.com"),
                        api_key="k", chain_id=1, max_retries=0)
es = EtherscanProvider(client=client(alive), api_key="k", default_chain_id=1, max_retries=0)
reg = ProviderRegistry([bs, es])
r = reg.get_native_balance("0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045", "ethereum")
print("STATUS:%s" % r.status.name)
print("DATA:%s" % r.data)
print("SOURCE:%s" % r.source)
"""
    o = out(run(code, tmp_path))
    assert get(o, "STATUS:") == "OK", f"real-provider failover failed:\n{o}"
    assert get(o, "DATA:") == "12345"
    assert get(o, "SOURCE:") == "etherscan"


def test_no_gate_gaming_in_app_layer():
    """No module may detect the harness or patch builtins to prop up a test."""
    banned = ["builtins.print =", "builtins.print=", "builtins.json", "builtins.open",
              "builtins.__dict__", "sys.stdout =", "sys.stdout=", "sys.argv =",
              "orig_argv", "import pytest", "from pytest", "acceptance/", "WIT_GATE",
              "unittest.mock"]
    scan_roots = [ROOT / "app"]
    scan_roots += [p for p in ROOT.glob("*.py")]       # conftest.py, main.py, …
    files = []
    for root in scan_roots:
        files += [root] if root.is_file() else list(root.rglob("*.py"))
    offenders = []
    for p in files:
        if p.name in ("conftest.py",):
            text = p.read_text(encoding="utf-8")
            tokens = [b for b in banned if b not in ("import pytest", "from pytest")]
            for token in tokens:
                if token in text:
                    offenders.append(f"{p.name}: {token!r}")
            continue
        text = p.read_text(encoding="utf-8")
        for token in banned:
            if token in text:
                offenders.append(f"{p.relative_to(ROOT)}: {token!r}")
    assert not offenders, "code manipulates builtins or the test harness: " + "; ".join(offenders)
