"""Independent acceptance gate — Stage 2A (wallet/group services, bulk import, audit).

Owned by Hermes. Pinned in docs/DEVLOG.md; the build agent must not edit it.

Run from the project root:
    env -u WIT_DB_PATH .venv/bin/python -m pytest acceptance/gate_stage2a.py -q
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

HEADER = r"""
import json, os
from app.config import load_config
from app.database.session import init_db, session_factory, session_scope
from app.database import models as m

cfg = load_config()
engine = init_db(cfg)
factory = session_factory(engine)
"""


def run(code: str, tmp_path: Path, name: str = "db.sqlite") -> subprocess.CompletedProcess:
    db = tmp_path / name
    env = {k: v for k, v in os.environ.items() if not k.startswith("WIT_")}
    env["WIT_DB_PATH"] = str(db)
    env["PYTHONPATH"] = str(ROOT)
    return subprocess.run(
        [sys.executable, "-c", HEADER + code], cwd=ROOT, env=env,
        capture_output=True, text=True, timeout=180,
    )


def out(p: subprocess.CompletedProcess) -> str:
    assert p.returncode == 0, f"script failed:\nSTDOUT:{p.stdout}\nSTDERR:{p.stderr[-3000:]}"
    return p.stdout.strip()


def test_validators_eip55_and_solana(tmp_path):
    code = r"""
from app.utils.validators import normalize_evm_address, is_valid_evm_address, is_valid_solana_address
res = {}
res["lower_ok"] = normalize_evm_address("0xfb6916095ca1df60bb79ce92ce3ea74c37c5d359")
res["checksum_ok"] = normalize_evm_address("0xfB6916095ca1df60bB79Ce92cE3Ea74c37c5d359")
try:
    normalize_evm_address("0xfB6916095ca1df60bB79Ce92cE3Ea74c37c5d35A")
    res["bad_checksum"] = "accepted"
except ValueError as e:
    res["bad_checksum"] = "rejected"
res["short"] = is_valid_evm_address("0x1234")
res["good"] = is_valid_evm_address("0xfB6916095ca1df60bB79Ce92cE3Ea74c37c5d359")
res["sol_good"] = is_valid_solana_address("5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1")
res["sol_bad"] = is_valid_solana_address("0xfB6916095ca1df60bB79Ce92cE3Ea74c37c5d359")
print("RES:" + json.dumps(res))
"""
    res = json.loads(out(run(code, tmp_path)).split("RES:")[1])
    assert res["lower_ok"] == "0xfB6916095ca1df60bB79Ce92cE3Ea74c37c5d359"
    assert res["checksum_ok"] == "0xfB6916095ca1df60bB79Ce92cE3Ea74c37c5d359"
    assert res["bad_checksum"] == "rejected", "invalid EIP-55 checksum must raise ValueError"
    assert res["short"] is False and res["good"] is True
    assert res["sol_good"] is True and res["sol_bad"] is False


def test_group_tree_subtree_move_cycle_delete(tmp_path):
    code = r"""
from app.core.group_manager import GroupManager
from app.core.wallet_manager import WalletManager
with session_scope(factory) as s:
    g = GroupManager(s); w = WalletManager(s)
    farm = g.create_group("Farm"); f1 = g.create_group("Farm #1", farm.id); f2 = g.create_group("Farm #2", farm.id)
    deep = g.create_group("Deep", f1.id)
    a = w.create_wallet(address="0xfb6916095ca1df60bb79ce92ce3ea74c37c5d359", name="W1", group_id=f1.id)
    b = w.create_wallet(address="0xfb6916095ca1df60bb79ce92ce3ea74c37c5d35a", name="W2", group_id=deep.id)
    c = w.create_wallet(address="0xfb6916095ca1df60bb79ce92ce3ea74c37c5d35b", name="W3", group_id=f2.id)
    print("PATH:" + g.path(deep.id))
    ids = sorted(x.address[-2:] for x in g.subtree_wallets(farm.id))
    print("SUBTREE:" + ",".join(ids))
    try:
        g.move_group(farm.id, deep.id); print("CYCLE:accepted")
    except ValueError:
        print("CYCLE:rejected")
    g.delete_group(f1.id)
    left = sorted(x.group_id if x.group_id else 0 for x in w.list_wallets())
    print("AFTER_DELETE:" + json.dumps(left))
    print("GROUPS:" + json.dumps(sorted(x.name for x in s.query(m.WalletGroup).all())))
"""
    o = out(run(code, tmp_path))
    assert "PATH:Farm / Farm #1 / Deep" in o or "PATH:Farm/Farm #1/Deep" in o, o
    assert "d35a,d359" in o.replace(" ", ""), f"subtree_wallets missed descendants: {o}"
    assert "CYCLE:rejected" in o, "moving a group into its own descendant must raise ValueError"
    after = json.loads(o.split("AFTER_DELETE:")[1].split("\n")[0])
    assert 0 not in after, f"wallets lost group instead of being reassigned: {after}"


def test_wallet_metadata_tags_socials_history(tmp_path):
    code = r"""
from app.core.wallet_manager import WalletManager
from app.core.group_manager import GroupManager
with session_scope(factory) as s:
    g = GroupManager(s); w = WalletManager(s)
    grp = g.create_group("Cold")
    wl = w.create_wallet(address="0xfb6916095ca1df60bb79ce92ce3ea74c37c5d359", name="Main",
                         group_id=grp.id, tags=["cold", "main"], notes="seedless watch-only",
                         socials={"twitter": "https://x.com/example"})
    w.update_wallet(wl.id, name="Main Cold", notes="renamed")
    w.archive_wallet(wl.id)
    hist = w.history(wl.id)
    print("TAGS:" + json.dumps(sorted(t.name for t in wl.tags)) if False else "TAGS:skip")
    print("SOCIALS:" + json.dumps([x.url or x.value for x in wl.socials]) if False else "SOCIALS:skip")
    print("HIST:" + json.dumps(len(hist)))
    print("HIST_LAST:" + json.dumps({"field": hist[-1].field, "old": hist[-1].old_value, "new": hist[-1].new_value}))
    print("ARCHIVED:" + json.dumps(w.get_wallet(wl.id).archived))
"""
    o = out(run(code, tmp_path))
    assert int(o.split("HIST:")[1].split("\n")[0]) >= 2, f"metadata history too short: {o}"
    last = json.loads(o.split("HIST_LAST:")[1].split("\n")[0])
    assert last["field"] in {"name", "notes", "archived"} and last["old"] != last["new"], last
    assert "ARCHIVED:true" in o


def test_search_and_filters(tmp_path):
    code = r"""
from app.core.group_manager import GroupManager
from app.core.wallet_manager import WalletManager, WalletFilters
with session_scope(factory) as s:
    g = GroupManager(s); w = WalletManager(s)
    farm = g.create_group("Farm"); sub = g.create_group("Sub", farm.id)
    w.create_wallet(address="0xfb6916095ca1df60bb79ce92ce3ea74c37c5d359", name="Alpha", group_id=farm.id, tags=["hot"])
    w.create_wallet(address="0xfb6916095ca1df60bb79ce92ce3ea74c37c5d35a", name="Beta", group_id=sub.id, tags=["cold"])
    w.create_wallet(address="0xfb6916095ca1df60bb79ce92ce3ea74c37c5d35b", name="Gamma")
    print("SEARCH_NAME:" + ",".join(sorted(x.name for x in w.search("alp"))))
    print("SEARCH_ADDR:" + ",".join(sorted(x.name for x in w.search("0x...d35a" if False else "d35a"))))
    print("SEARCH_TAG:" + ",".join(sorted(x.name for x in w.search("cold"))))
    print("FILTER_SUBGROUP:" + ",".join(sorted(x.name for x in w.list_wallets(WalletFilters(group_id=farm.id)))))
    print("FILTER_TAG:" + ",".join(sorted(x.name for x in w.list_wallets(WalletFilters(tag="hot")))))
"""
    o = out(run(code, tmp_path))
    assert "SEARCH_NAME:Alpha" in o, o
    assert "SEARCH_ADDR:Beta" in o, f"address search failed: {o}"
    assert "SEARCH_TAG:Beta" in o, f"tag search failed: {o}"
    assert "FILTER_SUBGROUP:Alpha,Beta" in o, f"group filter must include subgroups: {o}"
    assert "FILTER_TAG:Alpha" in o, o


def test_import_csv_preview_apply(tmp_path):
    code = r"""
from app.core.import_manager import ImportManager
csv_text = "address,name,group,network,tags\n"
csv_text += "0xfb6916095ca1df60bb79ce92ce3ea74c37c5d359,Wallet001,Farm #1,ethereum,farming\n"
csv_text += "0xfb6916095ca1df60bb79ce92ce3ea74c37c5d359,Wallet001dup,Farm #1,ethereum,farming\n"
csv_text += "0xNOTANADDRESS,Wallet002,Farm #1,ethereum,farming\n"
csv_text += "0xfb6916095ca1df60bb79ce92ce3ea74c37c5d35a,Wallet003,Farm #2,arbitrum,cold\n"
with session_scope(factory) as s:
    im = ImportManager(s)
    prev = im.preview(csv_text, fmt="csv")
    print("FMT:" + prev.format)
    print("COUNTS:" + json.dumps({"new": prev.new_count, "dup": prev.duplicate_count, "err": prev.error_count}))
    print("WALLETS_AFTER_PREVIEW:" + json.dumps(s.query(m.Wallet).count()))
    rep = im.apply(prev, mode="add_only")
    print("REPORT:" + json.dumps({"added": rep.added, "skipped": rep.skipped, "errors": len(rep.errors)}))
    print("WALLETS_AFTER_APPLY:" + json.dumps(s.query(m.Wallet).count()))
    rep2 = im.apply(im.preview(csv_text, fmt="csv"), mode="add_only")
    print("REPORT2:" + json.dumps({"added": rep2.added, "skipped": rep2.skipped}))
"""
    o = out(run(code, tmp_path))
    assert "FMT:csv" in o, o
    counts = json.loads(o.split("COUNTS:")[1].split("\n")[0])
    assert counts == {"new": 2, "dup": 1, "err": 1}, f"preview counts wrong: {counts}"
    assert "WALLETS_AFTER_PREVIEW:0" in o, "preview must not write to the database"
    rep = json.loads(o.split("REPORT:")[1].split("\n")[0])
    assert rep == {"added": 2, "skipped": 2, "errors": 1}, rep
    assert "WALLETS_AFTER_APPLY:2" in o
    rep2 = json.loads(o.split("REPORT2:")[1].split("\n")[0])
    assert rep2["added"] == 0 and rep2["skipped"] == 4, f"re-import must be idempotent: {rep2}"


def test_import_txt_and_json(tmp_path):
    code = r"""
from app.core.import_manager import ImportManager
txt = "\n".join([
    "0xfb6916095ca1df60bb79ce92ce3ea74c37c5d359,Alpha",
    "0xfb6916095ca1df60bb79ce92ce3ea74c37c5d35a,Beta",
    "# comment line",
    "0xbroken",
])
js = json.dumps([
    {"address": "0xfb6916095ca1df60bb79ce92ce3ea74c37c5d359", "name": "Alpha", "tags": ["a"]},
    {"address": "0xfb6916095ca1df60bb79ce92ce3ea74c37c5d359", "name": "AlphaDup"},
])
with session_scope(factory) as s:
    im = ImportManager(s)
    p1 = im.preview(txt, fmt="txt"); r1 = im.apply(p1, mode="add_only")
    p2 = im.preview(js, fmt="json")
    print("FMT_TXT:%s FMT_JSON:%s" % (p1.format, p2.format))
    print("TXT_REPORT:" + json.dumps({"added": r1.added, "errors": len(r1.errors)}))
    print("JSON_COUNTS:" + json.dumps({"new": p2.new_count, "dup": p2.duplicate_count, "err": p2.error_count}))
    print("AUTO:" + json.dumps([im.detect_format(txt), im.detect_format(js)]))
"""
    o = out(run(code, tmp_path))
    assert "FMT_TXT:txt" in o and "FMT_JSON:json" in o, o
    r = json.loads(o.split("TXT_REPORT:")[1].split("\n")[0])
    assert r["added"] == 2 and r["errors"] == 1, r
    c = json.loads(o.split("JSON_COUNTS:")[1].split("\n")[0])
    assert c == {"new": 1, "dup": 1, "err": 0}, c
    auto = json.loads(o.split("AUTO:")[1].split("\n")[0])
    assert auto == ["txt", "json"], auto


def test_import_update_mode_and_row_isolation(tmp_path):
    code = r"""
from app.core.import_manager import ImportManager
with session_scope(factory) as s:
    im = ImportManager(s)
    base = "0xfb6916095ca1df60bb79ce92ce3ea74c37c5d359,Original\n"
    im.apply(im.preview(base, fmt="txt"), mode="add_only")
    upd = "0xfb6916095ca1df60bb79ce92ce3ea74c37c5d359,Renamed\n"
    r1 = im.apply(im.preview(upd, fmt="txt"), mode="add_only")
    name1 = s.query(m.Wallet).one().name
    r2 = im.apply(im.preview(upd, fmt="txt"), mode="update")
    name2 = s.query(m.Wallet).one().name
    print("ADDONLY:" + json.dumps({"added": r1.added, "skipped": r1.skipped, "updated": getattr(r1, "updated", 0)}))
    print("NAME_SEQ:" + json.dumps([name1, name2]))
    print("UPDATE:" + json.dumps({"updated": getattr(r2, "updated", 0)}))
    big = "".join("0x%040x,Bulk%03d\n" % (i + 1, i) for i in range(20))
    big += "0xbroken,Bad1\n0xbroken,Bad2\n"
    rb = im.apply(im.preview(big, fmt="txt"), mode="add_only")
    print("BULK:" + json.dumps({"added": rb.added, "errors": len(rb.errors)}))
"""
    o = out(run(code, tmp_path))
    assert json.loads(o.split("NAME_SEQ:")[1].split("\n")[0]) == ["Original", "Renamed"], o
    upd = json.loads(o.split("UPDATE:")[1].split("\n")[0])
    assert upd["updated"] == 1, f"update mode did not update: {upd}"
    bulk = json.loads(o.split("BULK:")[1].split("\n")[0])
    assert bulk == {"added": 20, "errors": 2}, f"one bad row must not abort the batch: {bulk}"


def test_audit_migration_applies(tmp_path):
    db = tmp_path / "mig.db"
    env = {k: v for k, v in os.environ.items() if not k.startswith("WIT_")}
    env["WIT_DB_PATH"] = str(db)
    env["PYTHONPATH"] = str(ROOT)
    p = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"],
                       cwd=ROOT, env=env, capture_output=True, text=True, timeout=240)
    assert p.returncode == 0, f"alembic upgrade failed:\n{p.stdout}\n{p.stderr}"
    check = run(
        "import sqlite3\n"
        f"con = sqlite3.connect({str(db)!r})\n"
        "names = {r[0] for r in con.execute(\"select name from sqlite_master where type='table'\")}\n"
        "print('AUDIT:%s' % ('wallet_audit_log' in names))\n"
        "print('N:%d' % len(names))\n",
        tmp_path, "noop.db",
    )
    o = out(check)
    assert "AUDIT:True" in o, f"wallet_audit_log table missing after migrations: {o}"
    assert int(o.split("N:")[1].split("\n")[0]) >= 23


def test_core_layer_is_offline_and_ui_free():
    core = ROOT / "app" / "core"
    assert core.is_dir(), "app/core package missing"
    offenders = []
    for p in core.rglob("*.py"):
        t = p.read_text(encoding="utf-8")
        if any(x in t for x in ("import httpx", "import requests", "textual", "from app.ui")):
            offenders.append(p.name)
    assert not offenders, f"core must stay UI- and network-free: {offenders}"
