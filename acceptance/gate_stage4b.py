"""Independent acceptance gate — Stage 4B (Activities/Dashboard views + sync hotkey).

Owned by Hermes. Offline: fake provider injected through AppState, temp database.

Run from the project root:
    env -u WIT_DB_PATH .venv/bin/python -m pytest acceptance/gate_stage4b.py -q
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _mk_tx(h, frm, to, value="1", block=100):
    from decimal import Decimal

    from app.providers.base import TransactionItem

    return TransactionItem(hash=h, from_address=frm, to_address=to, value=Decimal(value),
                            block_number=block, timestamp=None, status="ok")


class FakeProvider:
    """Minimal provider: fixed balance, two transactions, no network."""

    name = "fake"

    def __init__(self, fail: bool = False):
        self.fail = fail
        self.calls = 0

    def _res(self, data):
        from app.providers.base import ProviderResult, ProviderStatus

        if self.fail:
            return ProviderResult(status=ProviderStatus.ERROR, error="boom", source=self.name)
        return ProviderResult(status=ProviderStatus.OK, data=data, source=self.name)

    def get_native_balance(self, address, network):
        from decimal import Decimal

        self.calls += 1
        return self._res(Decimal("1000000000000000000"))

    def get_transactions(self, address, network, cursor=None):
        from app.providers.base import TransactionListResult

        self.calls += 1
        return self._res(TransactionListResult(
            items=[_mk_tx("0xgate4b01", address, "0xbeef000000000000000000000000000000000001"),
                   _mk_tx("0xgate4b02", "0xbeef000000000000000000000000000000000002", address)],
            next_cursor=None))

    def get_latest_block(self, network):
        return self._res(100)

    def health_check(self, network):
        return self._res(True)


@pytest.fixture(autouse=True)
def _db(tmp_path, monkeypatch):
    monkeypatch.setenv("WIT_DB_PATH", str(tmp_path / "tui4b.db"))


def seed(networks=True, wallets=1):
    from app.config import load_config
    from app.core.wallet_manager import WalletManager
    from app.database.models import Network
    from app.database.session import init_db, session_factory, session_scope

    engine = init_db(load_config())
    with session_scope(session_factory(engine)) as s:
        if networks and s.query(Network).count() == 0:
            s.add(Network(name="Ethereum", chain_type="evm", chain_id=1, enabled=True))
            s.flush()
        wm = WalletManager(s)
        ids = []
        for i in range(wallets):
            w = wm.create_wallet(address=f"0xfb6916095ca1df60bb79ce92ce3ea74c37c5d35{i}", name=f"W{i}")
            ids.append(w.id)
        return ids


def make_app(fake=None):
    from app.application import WalletTrackerApp
    from app.config import load_config
    from app.database.session import init_db, session_factory
    from app.state import AppState

    cfg = load_config()
    engine = init_db(cfg)
    state = AppState(config=cfg, engine=engine, session_factory=session_factory(engine))
    if fake is not None:
        from app.providers.registry import ProviderRegistry

        state.providers = ProviderRegistry([fake])
    return WalletTrackerApp(state=state)


@pytest.mark.asyncio
async def test_appstate_carries_providers():
    from app.state import AppState

    st = AppState()
    assert hasattr(st, "providers"), "AppState must allow injecting a provider registry"
    assert getattr(st, "providers") is None


@pytest.mark.asyncio
async def test_sync_hotkey_runs_sync_and_updates_status():
    from app.config import load_config
    from app.database.models import SyncJob
    from app.database.session import init_db, session_factory, session_scope

    ids = seed(wallets=1)
    fake = FakeProvider()
    app = make_app(fake)
    async with app.run_test(size=(140, 45)) as pilot:
        await pilot.press("s")
        await pilot.pause(1.5)
        status = app.query_one("#status-bar")
        assert status.sync_state != "syncing", "status bar stuck in 'syncing'"
        assert status.last_update is not None, "status bar did not record the sync time"

    engine = init_db(load_config())
    with session_scope(session_factory(engine)) as s:
        jobs = s.query(SyncJob).all()
    assert jobs, "pressing 's' created no SyncJob row"
    assert jobs[0].status in {"completed", "failed"}
    assert fake.calls >= 2, f"provider was not used by the sync worker (calls={fake.calls})"


@pytest.mark.asyncio
async def test_activities_screen_lists_and_filters_real_rows():
    from app.config import load_config
    from app.core.sync_engine import SyncEngine
    from app.database.session import init_db, session_factory
    from app.providers.registry import ProviderRegistry

    seed(wallets=1)
    engine = init_db(load_config())
    SyncEngine(session_factory(engine), ProviderRegistry([FakeProvider()]), load_config()) \
        .sync_wallet(1, "ethereum")

    app = make_app(None)
    async with app.run_test(size=(140, 45)) as pilot:
        await pilot.press("3")
        await pilot.pause()
        screen = app.screen
        screen.refresh_data()
        await pilot.pause()
        text = screen.activity_text
        assert "0xgate4b01" in text or "0xgate4b0" in text, f"activities not loaded: {text[:300]}"
        assert "receive" in text.lower() or "send" in text.lower(), text[:300]

        screen.set_type_filter("receive")
        await pilot.pause()
        filtered = screen.activity_text
        assert "receive" in filtered.lower(), filtered[:300]


@pytest.mark.asyncio
async def test_dashboard_shows_counts_and_recent_activity():
    from app.config import load_config
    from app.core.sync_engine import SyncEngine
    from app.database.session import init_db, session_factory
    from app.providers.registry import ProviderRegistry

    seed(wallets=2)
    engine = init_db(load_config())
    SyncEngine(session_factory(engine), ProviderRegistry([FakeProvider()]), load_config()) \
        .sync_all("ethereum")

    app = make_app(None)
    async with app.run_test(size=(140, 45)) as pilot:
        await pilot.press("1")
        await pilot.pause()
        screen = app.screen
        screen.refresh_data()
        await pilot.pause()
        text = screen.dashboard_text
        assert "2" in text, f"wallet count missing on dashboard: {text[:300]}"
        assert "0xgate4b" in text or "recent" in text.lower(), text[:300]


@pytest.mark.asyncio
async def test_sync_hotkey_survives_provider_failure():
    from app.database.models import SyncJob
    from app.database.session import init_db, session_factory, session_scope
    from app.config import load_config

    seed(wallets=1)
    app = make_app(FakeProvider(fail=True))
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("s")
        await pilot.pause(1.5)
        status = app.query_one("#status-bar")
        assert status.sync_state in {"idle", "paused"}, "status bar not reset after a failed sync"

    engine = init_db(load_config())
    with session_scope(session_factory(engine)) as s:
        jobs = s.query(SyncJob).all()
    assert jobs and jobs[0].status == "failed", "failed sync was not recorded as failed"
