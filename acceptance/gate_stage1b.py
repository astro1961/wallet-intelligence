"""Independent acceptance gate — Stage 1B (Textual TUI shell).

Owned by Hermes. Pinned in docs/DEVLOG.md. The build agent must not edit this file.

Run from the project root:
    .venv/bin/python -m pytest acceptance/gate_stage1b.py -q
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

SCREEN_FILES = {
    "dashboard": "dashboard.py",
    "wallets": "wallets.py",
    "activities": "activities.py",
    "projects": "projects.py",
    "defi": "defi.py",
    "networks": "networks.py",
    "graph": "graph.py",
    "import": "import_wallets.py",
    "settings": "settings.py",
}

REQUIRED_FILES = [
    "app/application.py", "app/state.py",
    "app/ui/__init__.py", "app/ui/styles/app.tcss",
    "app/ui/widgets/wallet_tree.py", "app/ui/widgets/data_table.py",
    "app/ui/widgets/status_bar.py", "app/ui/widgets/activity_feed.py",
] + [f"app/ui/screens/{f}" for f in SCREEN_FILES.values()]


def test_required_files_exist():
    missing = [f for f in REQUIRED_FILES if not (ROOT / f).is_file()]
    assert not missing, f"missing files: {missing}"


def test_tui_dependencies_declared():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8").lower()
    assert "textual" in text and "rich" in text
    assert "pytest-asyncio" in text, "pytest-asyncio is required for TUI tests"


def test_main_launches_the_textual_app(monkeypatch, tmp_path):
    """`python main.py` must hand control to the Textual app, not print a stub message."""
    code = (
        "import main, sys\n"
        "called = {}\n"
        "def fake_run(self, *a, **kw):\n"
        "    called['run'] = True\n"
        "    return 0\n"
        "from app.application import WalletTrackerApp\n"
        "WalletTrackerApp.run = fake_run\n"
        "sys.argv = ['main.py']\n"
        "rc = main.main()\n"
        "print('RAN:%s' % called.get('run', False))\n"
        "print('RC:%s' % rc)\n"
    )
    env = os.environ.copy()
    env["WIT_DB_PATH"] = str(tmp_path / "main.db")
    env["PYTHONPATH"] = str(ROOT)
    p = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env,
                       capture_output=True, text=True, timeout=120)
    assert p.returncode == 0, f"main() crashed:\n{p.stdout}\n{p.stderr}"
    assert "RAN:True" in p.stdout, f"main() did not start the Textual app:\n{p.stdout}"


@pytest.mark.asyncio
async def test_app_starts_and_shows_all_nine_screens(tmp_path, monkeypatch):
    monkeypatch.setenv("WIT_DB_PATH", str(tmp_path / "tui.db"))
    from app.application import WalletTrackerApp

    app = WalletTrackerApp()
    async with app.run_test(size=(140, 40)) as pilot:
        assert app.screen.id == "dashboard", f"first screen is {app.screen.id!r}"
        for key, expected in SCREEN_FILES.items():
            idx = list(SCREEN_FILES).index(key) + 1
            await pilot.press(str(idx))
            await pilot.pause()
            assert app.screen.id == key, \
                f"key {idx} should open {key!r}, got {app.screen.id!r}"


@pytest.mark.asyncio
async def test_sidebar_navigation_and_status_bar(tmp_path, monkeypatch):
    monkeypatch.setenv("WIT_DB_PATH", str(tmp_path / "tui2.db"))
    from app.application import WalletTrackerApp
    from app.ui.widgets.status_bar import StatusBar

    app = WalletTrackerApp()
    async with app.run_test(size=(140, 40)) as pilot:
        assert app.query(StatusBar), "StatusBar widget not mounted"
        await pilot.pause()
    src = (ROOT / "app" / "ui" / "widgets" / "status_bar.py").read_text(encoding="utf-8")
    assert re.search(r"(last_update|last_sync|updated_at|last_updated)", src, re.I), \
        "status bar has no last-update field"
    assert re.search(r"(sync|syncing|idle|paused)", src, re.I), \
        "status bar has no synchronization state field"


@pytest.mark.asyncio
async def test_quit_key_exits(tmp_path, monkeypatch):
    monkeypatch.setenv("WIT_DB_PATH", str(tmp_path / "tui3.db"))
    from app.application import WalletTrackerApp

    app = WalletTrackerApp()
    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.press("q")
        await pilot.pause()
    assert not app.is_running, "pressing q did not exit the app"


@pytest.mark.asyncio
async def test_screens_render_empty_states_without_crashing(tmp_path, monkeypatch):
    monkeypatch.setenv("WIT_DB_PATH", str(tmp_path / "tui4.db"))
    from app.application import WalletTrackerApp

    app = WalletTrackerApp()
    async with app.run_test(size=(100, 30)) as pilot:
        for i in range(1, 10):
            await pilot.press(str(i))
            await pilot.pause()
            # narrow window on purpose: layout must not raise
            await pilot.resize_terminal(60, 20)
            await pilot.pause()
            await pilot.resize_terminal(100, 30)
            await pilot.pause()
    assert True


def test_no_outbound_network_imports_in_ui_layer():
    """The TUI shell must not talk to providers yet (Stage 1B is offline by design)."""
    offenders = []
    for path in (ROOT / "app").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if re.search(r"\b(requests|httpx|aiohttp)\b", text) and "providers" not in str(path):
            offenders.append(str(path.relative_to(ROOT)))
    assert not offenders, f"network clients imported outside providers/: {offenders}"


def test_hotkey_bindings_documented():
    app_src = (ROOT / "app" / "application.py").read_text(encoding="utf-8")
    for key in ["q", "a", "i", "r", "f", "g", "slash"]:
        assert key in app_src, f"binding {key!r} not declared in application.py"
