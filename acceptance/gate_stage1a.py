"""Independent acceptance gate — Stage 1A (skeleton, config, DB, models, migrations).

Owned by Hermes, NOT by the build agent. The SHA-256 of this file is pinned in
docs/DEVLOG.md; if the build agent edits it, the gate is restored from the pinned
hash before it is trusted.

Run from the project root:
    .venv/bin/python -m pytest acceptance/gate_stage1a.py -q
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# --- contract pinned in tasks/stage1a.md -------------------------------------
EXPECTED_MODELS = [
    "Wallet", "WalletGroup", "WalletTag", "WalletTagLink", "WalletSocial",
    "WalletRelation", "WalletNetwork", "Network", "RpcEndpoint", "Project",
    "ProjectContract", "ProjectWallet", "ProjectTask", "Activity",
    "Transaction", "Token", "BalanceSnapshot", "DeFiPosition", "Provider",
    "SyncJob", "SyncCursor", "Note",
]

REQUIRED_FILES = [
    "pyproject.toml", "config.yaml", ".env.example", ".gitignore", "README.md",
    "main.py", "alembic.ini",
    "app/__init__.py", "app/config.py",
    "app/database/__init__.py", "app/database/models.py",
    "app/database/session.py", "app/database/repository.py",
    "app/utils/__init__.py", "app/utils/logging.py",
    "migrations/env.py",
]


def run(code: str, env: dict | None = None) -> subprocess.CompletedProcess:
    e = os.environ.copy()
    e.pop("PYTHONPATH", None)
    e["PYTHONPATH"] = str(ROOT)
    if env:
        e.update(env)
    return subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, env=e,
        capture_output=True, text=True, timeout=180,
    )


def test_required_files_exist():
    missing = [f for f in REQUIRED_FILES if not (ROOT / f).is_file()]
    assert not missing, f"missing files: {missing}"


def test_migrations_present():
    versions = list((ROOT / "migrations" / "versions").glob("*.py"))
    assert versions, "no alembic revision in migrations/versions/"


def test_pyproject_declares_spec_dependencies():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8").lower()
    required = ["textual", "rich", "sqlalchemy", "alembic", "pydantic",
                "httpx", "networkx", "pyyaml", "python-dotenv", "pytest"]
    missing = [d for d in required if d not in text]
    assert not missing, f"dependencies not declared in pyproject.toml: {missing}"
    assert "requires-python" in text, "requires-python not set"
    assert re.search(r"requires-python\s*=\s*[\"']>=?\s*3\.1[2-9]", text), \
        "requires-python must be >=3.12"


def test_gitignore_covers_secrets_and_artifacts():
    text = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for pattern in [".env", ".venv", "data", "logs", "__pycache__"]:
        assert pattern in text, f".gitignore does not exclude {pattern}"


def test_no_secrets_in_config_yaml():
    text = (ROOT / "config.yaml").read_text(encoding="utf-8")
    # API keys must be referenced by env var name, never embedded as values
    for m in re.finditer(r"^\s*(api_key|secret|token|password)\s*:\s*(.+)$",
                         text, re.M | re.I):
        value = m.group(2).strip().strip("\"'")
        assert value == "" or value.lower() in {"null", "none", "~"} \
            or re.fullmatch(r"[A-Z][A-Z0-9_]*", value), \
            f"literal secret candidate in config.yaml: {m.group(0)}"


def test_models_importable_and_complete(tmp_path):
    code = (
        "from app.database import models as m\n"
        f"expected = {EXPECTED_MODELS!r}\n"
        "missing = [n for n in expected if not hasattr(m, n)]\n"
        "print('MISSING:' + ','.join(missing))\n"
        "print('COUNT:%d' % len([n for n in expected if hasattr(m, n)]))\n"
    )
    p = run(code)
    assert p.returncode == 0, f"import failed:\n{p.stderr}"
    assert "MISSING:" in p.stdout and p.stdout.split("MISSING:")[1].split("\n")[0] == "", \
        f"model classes missing: {p.stdout}"


def test_config_loads_and_env_overrides(tmp_path):
    db = tmp_path / "cfg_override.db"
    code = (
        "from app.config import load_config\n"
        "c = load_config()\n"
        "print('DB:' + c.database.path)\n"
        "print('NAME:' + c.app.name)\n"
        "print('NETS:%d' % len(c.networks))\n"
        "print('PROV:' + ','.join(sorted(c.providers.keys())))\n"
    )
    p = run(code, env={"WIT_DB_PATH": str(db)})
    assert p.returncode == 0, f"load_config failed:\n{p.stderr}"
    assert p.stdout.count("DB:") == 1
    assert str(db) in p.stdout, "WIT_DB_PATH override not applied to database.path"
    assert "Wallet Intelligence" in p.stdout, "app.name not read from config.yaml"
    assert "NETS:" in p.stdout and not p.stdout.strip().endswith("NETS:0"), \
        "networks not loaded from config.yaml"
    for prov in ("etherscan", "blockscout", "defillama"):
        assert prov in p.stdout.lower(), f"provider {prov} missing from config"


def test_init_db_creates_all_tables(tmp_path):
    db = tmp_path / "init.db"
    code = (
        "from app.config import load_config\n"
        "from app.database import models as m\n"
        "from app.database.session import init_db\n"
        "from sqlalchemy import inspect\n"
        "cfg = load_config()\n"
        "init_db(cfg)\n"
        "eng = __import__('app.database.session', fromlist=['x'])._engine if hasattr(__import__('app.database.session', fromlist=['x']), '_engine') else None\n"
        "from sqlalchemy import create_engine\n"
        "insp = inspect(create_engine('sqlite:///' + cfg.database.path))\n"
        "tables = set(insp.get_table_names())\n"
        "expected = {m.Wallet.__tablename__}\n"
        "print('TABLES:%d' % len(tables))\n"
        "print('HAS_WALLET:%s' % (m.Wallet.__tablename__ in tables))\n"
        "print('LIST:' + ','.join(sorted(tables)))\n"
    )
    p = run(code, env={"WIT_DB_PATH": str(db)})
    assert p.returncode == 0, f"init_db failed:\n{p.stderr}"
    n = int(p.stdout.split("TABLES:")[1].split("\n")[0])
    assert n >= len(EXPECTED_MODELS), f"expected >= {len(EXPECTED_MODELS)} tables, got {n}"
    assert "HAS_WALLET:True" in p.stdout


def test_alembic_upgrade_head_from_scratch(tmp_path):
    db = tmp_path / "alembic.db"
    env = os.environ.copy()
    env["WIT_DB_PATH"] = str(db)
    env["PYTHONPATH"] = str(ROOT)
    p = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"],
                       cwd=ROOT, env=env, capture_output=True, text=True, timeout=240)
    assert p.returncode == 0, f"alembic upgrade head failed:\n{p.stdout}\n{p.stderr}"
    assert db.exists(), "alembic did not create the database file"
    check = run(
        "import sqlite3, sys\n"
        f"con = sqlite3.connect({str(db)!r})\n"
        "rows = con.execute(\"select name from sqlite_master where type='table'\").fetchall()\n"
        "names = {r[0] for r in rows}\n"
        "print('N:%d' % len(names))\n"
        "print('ALEMBIC:%s' % ('alembic_version' in names))\n",
    )
    assert check.returncode == 0, check.stderr
    n = int(check.stdout.split("N:")[1].split("\n")[0])
    assert n >= len(EXPECTED_MODELS), f"migration created only {n} tables"
    assert "ALEMBIC:True" in check.stdout, "alembic_version table missing"


def test_integrity_constraints(tmp_path):
    db = tmp_path / "integrity.db"
    code = r"""
from decimal import Decimal
from sqlalchemy.exc import IntegrityError
from app.config import load_config
from app.database.session import init_db, get_session
from app.database import models as m

cfg = load_config(); init_db(cfg)
errs = []

with get_session() as s:
    eth = m.Network(name="Ethereum", chain_type="evm", chain_id=1, enabled=True)
    arb = m.Network(name="Arbitrum", chain_type="evm", chain_id=42161, enabled=True)
    s.add_all([eth, arb]); s.flush()
    g = m.WalletGroup(name="Farm")
    s.add(g); s.flush()
    w = m.Wallet(address="0xabc0000000000000000000000000000000000001", name="W1", group_id=g.id)
    s.add(w); s.flush()
    s.add(m.WalletNetwork(wallet_id=w.id, network_id=eth.id)); s.flush()
    print("OK_MULTI_NETWORK")
    # duplicate wallet (address, chain_type) must fail
    try:
        s.add(m.Wallet(address="0xabc0000000000000000000000000000000000001", name="dup", group_id=g.id))
        s.flush(); errs.append("no unique constraint on wallet address+chain_type")
        s.rollback()
    except IntegrityError:
        s.rollback()
    # duplicate wallet_network must fail
    try:
        s.add(m.WalletNetwork(wallet_id=w.id, network_id=eth.id)); s.flush()
        errs.append("no unique constraint on wallet_network(wallet_id, network_id)")
        s.rollback()
    except IntegrityError:
        s.rollback()
    # FK must reject a wallet pointing at a non-existent group
    try:
        s.add(m.Wallet(address="0xabc0000000000000000000000000000000000002", group_id=999999)); s.flush()
        errs.append("FK not enforced (group_id=999999 accepted)")
        s.rollback()
    except IntegrityError:
        s.rollback()

print("ERRS:" + "|".join(errs))
"""
    p = run(code, env={"WIT_DB_PATH": str(db)})
    assert p.returncode == 0, f"integrity test crashed:\n{p.stderr}"
    assert "OK_MULTI_NETWORK" in p.stdout, "same address on two networks was rejected"
    errs = p.stdout.split("ERRS:")[1].split("\n")[0]
    assert errs == "", f"integrity gaps: {errs}"


def test_no_float_columns_for_financial_values(tmp_path):
    db = tmp_path / "types.db"
    code = r"""
from sqlalchemy import inspect, create_engine
from app.config import load_config
from app.database.session import init_db

cfg = load_config(); init_db(cfg)
insp = inspect(create_engine("sqlite:///" + cfg.database.path))
bad = []
for t in insp.get_table_names():
    for col in insp.get_columns(t):
        name = col["name"].lower()
        if any(k in name for k in ("balance", "amount", "value", "price")) \
           and "FLOAT" in str(col["type"]).upper():
            bad.append(f"{t}.{col['name']}:{col['type']}")
print("BAD:" + "|".join(bad))
"""
    p = run(code, env={"WIT_DB_PATH": str(db)})
    assert p.returncode == 0, p.stderr
    bad = p.stdout.split("BAD:")[1].split("\n")[0]
    assert bad == "", f"float columns used for financial values: {bad}"


def test_logging_writes_file_and_redacts_secrets(tmp_path):
    log_dir = tmp_path / "logs"
    code = (
        "import logging\n"
        "from app.utils.logging import setup_logging\n"
        f"setup_logging({str(log_dir)!r})\n"
        "logging.getLogger('wit').info('ETHERSCAN_API_KEY=deadbeefcafe1234')\n"
        "logging.getLogger('wit').info('hello from gate')\n"
        "logging.shutdown()\n"
    )
    p = run(code, env={"WIT_DB_PATH": str(tmp_path / "log.db")})
    assert p.returncode == 0, f"setup_logging failed:\n{p.stderr}"
    files = list(log_dir.glob("*.log"))
    assert files, "no log file created"
    text = "\n".join(f.read_text(encoding="utf-8") for f in files)
    assert "hello from gate" in text, "log record missing"
    assert "deadbeefcafe1234" not in text, "API key value leaked into log file"


def test_project_has_unit_tests():
    files = [p for p in (ROOT / "tests").rglob("test_*.py")]
    assert len(files) >= 3, f"expected >=3 unit test files from the agent, got {len(files)}"
    total = sum(len(f.read_text(encoding='utf-8').splitlines()) for f in files)
    assert total >= 120, f"agent tests look like stubs ({total} lines total)"


# --- gate v2 additions (2026-11-04, after 1A review) -------------------------

def test_migration_contains_real_ddl():
    versions = sorted((ROOT / "migrations" / "versions").glob("*.py"))
    assert versions, "no revisions"
    text = "\n".join(v.read_text(encoding="utf-8") for v in versions)
    creates = text.count("op.create_table(")
    assert creates >= 20, f"revision emits only {creates} op.create_table() calls"
    assert "create_all" not in text, \
        "migration delegates to Base.metadata.create_all — not a reproducible revision"
    assert "from app.database.models import" not in text, \
        "migration imports live models; historical revisions must be frozen DDL"


def test_address_normalized_on_attribute_assignment(tmp_path):
    db = tmp_path / "norm.db"
    code = r"""
from app.config import load_config
from app.database.session import init_db
from app.database import models as m

init_db(load_config())
w = m.Wallet(address="0xAbCdEf0000000000000000000000000000000001", name="n")
print("INIT:" + w.address)
w.address = "0xABCDEF0000000000000000000000000000000002"
print("SET:" + w.address)
w2 = m.Wallet(address="So1anaAddrCaseSensitive1111", chain_type="solana")
print("SOL:" + w2.address)
"""
    p = run(code, env={"WIT_DB_PATH": str(db)})
    assert p.returncode == 0, p.stderr
    lines = dict(l.split(":", 1) for l in p.stdout.strip().splitlines() if ":" in l)
    assert lines.get("INIT", "").islower(), f"constructor did not normalize: {lines.get('INIT')}"
    assert lines.get("SET", "").islower(), \
        f"assignment did not normalize EVM address: {lines.get('SET')}"
    assert lines.get("SOL") == "So1anaAddrCaseSensitive1111", \
        "solana address must keep its case"


def test_init_db_is_idempotent(tmp_path):
    db = tmp_path / "idem.db"
    code = r"""
from app.config import load_config
from app.database.session import init_db
from sqlalchemy import create_engine, inspect

cfg = load_config()
init_db(cfg)
init_db(cfg)
n = len(inspect(create_engine("sqlite:///" + cfg.database.path)).get_table_names())
print("TABLES:%d" % n)
"""
    p = run(code, env={"WIT_DB_PATH": str(db)})
    assert p.returncode == 0, f"second init_db failed:\n{p.stderr}"
    n = int(p.stdout.split("TABLES:")[1].split("\n")[0])
    assert n >= len(EXPECTED_MODELS), f"tables lost after second init: {n}"

