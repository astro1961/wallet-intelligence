"""Tests for Stage 4C: shared transaction between monitored wallets, rollback hygiene, and empty state."""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.sync_engine import SyncEngine
from app.database.models import Activity, Base, Network, Transaction, Wallet
from app.providers.base import (
    DataProvider,
    ProviderResult,
    ProviderStatus,
    TransactionItem,
    TransactionListResult,
)
from app.providers.registry import ProviderRegistry
from app.ui.screens.activities import EMPTY_ACTIVITIES_MSG, ActivitiesScreen

WALLET_A = "0xd8da6bf26964af9d7eed9e03e53415d37aa96045"
WALLET_B = "0xfb6916095ca1df60bb79ce92ce3ea74c37c5d359"


class SharedTxProvider(DataProvider):
    """Provider returning one shared transfer between A and B, plus one own tx per wallet."""

    name = "shared_provider"

    def __init__(self) -> None:
        super().__init__()
        self.balance_val = Decimal("1.5")

    def get_native_balance(self, address: str, network: str) -> ProviderResult:
        return ProviderResult(status=ProviderStatus.OK, data=self.balance_val, source=self.name)

    def get_transactions(self, address: str, network: str, cursor: Any = None) -> ProviderResult:
        shared = TransactionItem(
            hash="0xshared",
            from_address=WALLET_A,
            to_address=WALLET_B,
            value=Decimal("5.0"),
            block_number=100,
            timestamp=datetime(2026, 11, 1, tzinfo=UTC),
            status="ok",
        )
        own = TransactionItem(
            hash="0xown_" + address[-4:],
            from_address=address,
            to_address="0x1111111111111111111111111111111111111111",
            value=Decimal("1.0"),
            block_number=101,
            timestamp=datetime(2026, 11, 1, tzinfo=UTC),
            status="ok",
        )
        return ProviderResult(
            status=ProviderStatus.OK,
            data=TransactionListResult(items=[shared, own], next_cursor=None),
            source=self.name,
        )


@pytest.fixture
def test_db():
    """Create fresh database with models schema and seeded networks and wallets."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)

    with factory() as session:
        net = Network(name="ethereum", chain_type="evm", chain_id=1, enabled=True)
        w1 = Wallet(address=WALLET_A, name="Wallet A")
        w2 = Wallet(address=WALLET_B, name="Wallet B")
        session.add_all([net, w1, w2])
        session.commit()
        w1_id, w2_id = w1.id, w2.id

    return {"engine": engine, "factory": factory, "w1_id": w1_id, "w2_id": w2_id}


def test_shared_transaction_syncs_for_both_wallets(test_db):
    """1. Two wallets, one shared tx hash -> both syncs ok, 2 tx rows, 4 activity rows."""
    factory = test_db["factory"]
    w1_id = test_db["w1_id"]
    w2_id = test_db["w2_id"]

    sync = SyncEngine(factory, ProviderRegistry([SharedTxProvider()]), config=None)
    r1 = sync.sync_wallet(w1_id, "ethereum")
    r2 = sync.sync_wallet(w2_id, "ethereum")

    assert r1.status == "ok", f"w1 sync failed: {r1.error}"
    assert r2.status == "ok", f"w2 sync failed on shared tx: {r2.error}"

    with factory() as session:
        txs = list(session.execute(select(Transaction)).scalars().all())
        acts = list(session.execute(select(Activity)).scalars().all())
        shared_txs = list(session.execute(
            select(Transaction).where(Transaction.tx_hash == "0xshared")
        ).scalars().all())

    # transactions holds 4 rows in total (2 shared + 2 own), 2 for 0xshared (one per wallet)
    assert len(txs) == 4, f"Expected 4 transactions, got {len(txs)}"
    assert len(shared_txs) == 2, f"Expected 2 shared transactions, got {len(shared_txs)}"
    assert {st.wallet_id for st in shared_txs} == {w1_id, w2_id}

    # activities holds 4 (shared + own for each wallet)
    assert len(acts) == 4, f"Expected 4 activities, got {len(acts)}"


def test_per_wallet_sync_is_idempotent(test_db):
    """2. Sync is still idempotent per wallet: re-running adds 0 rows."""
    factory = test_db["factory"]
    w1_id = test_db["w1_id"]
    w2_id = test_db["w2_id"]

    sync = SyncEngine(factory, ProviderRegistry([SharedTxProvider()]), config=None)
    sync.sync_wallet(w1_id, "ethereum")
    sync.sync_wallet(w2_id, "ethereum")

    with factory() as session:
        tx_count_before = len(session.execute(select(Transaction)).scalars().all())
        act_count_before = len(session.execute(select(Activity)).scalars().all())

    # Re-run sync on wallet 1
    r_repeat = sync.sync_wallet(w1_id, "ethereum")
    assert r_repeat.status == "ok"
    assert r_repeat.activities_added == 0

    with factory() as session:
        tx_count_after = len(session.execute(select(Transaction)).scalars().all())
        act_count_after = len(session.execute(select(Activity)).scalars().all())

    assert tx_count_after == tx_count_before, "Re-running sync altered transaction row count"
    assert act_count_after == act_count_before, "Re-running sync altered activity row count"


def test_session_recovery_after_integrity_error(test_db):
    """3. After an injected IntegrityError, session is usable and no PendingRollbackError escapes."""
    engine = test_db["engine"]
    factory = test_db["factory"]
    w1_id = test_db["w1_id"]
    w2_id = test_db["w2_id"]

    # Inject an IntegrityError on flush via SQLite trigger without monkeypatching
    with engine.connect() as conn:
        conn.execute(text(
            "CREATE TRIGGER inject_integrity_err BEFORE INSERT ON transactions "
            "WHEN NEW.tx_hash = '0xshared' BEGIN "
            "SELECT RAISE(ABORT, 'injected transaction constraint violation'); END;"
        ))
        conn.commit()

    sync = SyncEngine(factory, ProviderRegistry([SharedTxProvider()]), config=None)

    # First sync fails due to the trigger aborting flush
    r1 = sync.sync_wallet(w1_id, "ethereum")
    assert r1.status == "error"
    assert r1.error is not None
    assert "injected transaction constraint violation" in r1.error

    # Drop the trigger to remove the fault injection
    with engine.connect() as conn:
        conn.execute(text("DROP TRIGGER inject_integrity_err;"))
        conn.commit()

    # The next sync must succeed cleanly and must not raise PendingRollbackError
    r2 = sync.sync_wallet(w2_id, "ethereum")
    assert r2.status == "ok", f"Second sync failed after rollback: {r2.error}"

    # Verify session is usable for queries
    with factory() as session:
        tx_count = len(session.execute(select(Transaction)).scalars().all())
        assert tx_count > 0


def test_empty_state_text_contains_no_asterisks():
    """4. Empty-state text contains no literal asterisks and prompts 'press s to sync your wallets'."""
    assert "**" not in EMPTY_ACTIVITIES_MSG, f"EMPTY_ACTIVITIES_MSG contains raw asterisks: {EMPTY_ACTIVITIES_MSG}"
    assert "press s to sync your wallets" in EMPTY_ACTIVITIES_MSG

    screen = ActivitiesScreen()
    screen._loaded = True
    screen._rows = []
    text_rendered = screen.activity_text
    assert "**" not in text_rendered
    assert "press s to sync your wallets" in text_rendered
