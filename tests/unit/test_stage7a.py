"""Unit tests for Stage 7A: DeFiAnalyzer and DeFiScreen."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from textual.widgets import DataTable, Label

from app.application import WalletTrackerApp
from app.config import AppConfig
from app.core.defi_analyzer import DeFiAnalyzer
from app.database.models import (
    BalanceSnapshot,
    Base,
    Network,
    Token,
    Wallet,
)
from app.providers.base import ProviderResult, ProviderStatus


class FakePriceProvider:
    """Mock price provider returning fixed Decimal prices or errors."""

    def __init__(
        self,
        prices: dict[tuple[str, str], Decimal | ProviderResult] | None = None,
        should_fail: bool = False,
    ) -> None:
        self.prices = prices or {}
        self.should_fail = should_fail
        self.calls: list[tuple[str, str]] = []

    def get_token_price(self, chain: str, token: str) -> Any:
        self.calls.append((chain, token))
        if self.should_fail:
            raise RuntimeError("Provider connection failed")
        key = (chain.strip().lower(), token.strip().lower())
        return self.prices.get(key)


@pytest.fixture
def memory_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def session_factory(memory_db):
    return sessionmaker(bind=memory_db, expire_on_commit=False)


@pytest.fixture
def seed_data(session_factory):
    with session_factory() as session:
        net_eth = Network(name="Ethereum", chain_type="evm", chain_id=1, enabled=True, native_token="ETH")
        net_base = Network(name="Base", chain_type="evm", chain_id=8453, enabled=True, native_token="ETH")
        w1 = Wallet(address="0x1111111111111111111111111111111111111111", name="Alice")
        w2 = Wallet(address="0x2222222222222222222222222222222222222222", name="Bob")

        tok_usdc = Token(
            network=net_eth,
            contract_address="0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
            symbol="USDC",
            name="USD Coin",
            decimals=6,
        )
        tok_weth = Token(
            network=net_eth,
            contract_address="0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",
            symbol="WETH",
            name="Wrapped Ether",
            decimals=18,
        )
        tok_nft = Token(
            network=net_eth,
            contract_address="0xb47e3cd837ddf8e4c57f05d70ab865de6e193bbb",
            symbol="PUNKS",
            name="CryptoPunks",
            decimals=0,
        )

        session.add_all([net_eth, net_base, w1, w2, tok_usdc, tok_weth, tok_nft])
        session.commit()

        return {
            "net_eth_id": net_eth.id,
            "net_base_id": net_base.id,
            "w1_id": w1.id,
            "w2_id": w2.id,
            "tok_usdc_id": tok_usdc.id,
            "tok_weth_id": tok_weth.id,
            "tok_nft_id": tok_nft.id,
            "usdc_addr": tok_usdc.contract_address,
            "weth_addr": tok_weth.contract_address,
            "nft_addr": tok_nft.contract_address,
        }


def test_snapshot_token_balance_with_price(session_factory, seed_data):
    """Snapshot computes balance via decimals scaling and resolves price via provider."""
    price_val = Decimal("1950.50")
    provider = FakePriceProvider({
        ("ethereum", seed_data["weth_addr"].lower()): price_val,
    })
    analyzer = DeFiAnalyzer(session_factory, provider, AppConfig())

    with session_factory() as session:
        wallet = session.get(Wallet, seed_data["w1_id"])
        network = session.get(Network, seed_data["net_eth_id"])
        token = session.get(Token, seed_data["tok_weth_id"])

        # 2.5 WETH in raw wei
        raw_balance = Decimal(2500000000000000000)
        snap = analyzer.snapshot_token_balance(wallet, network, token, raw_balance)

        assert snap is not None
        assert snap.id is not None
        assert isinstance(snap.balance, Decimal)
        assert snap.balance == Decimal("2.5")
        assert snap.raw_balance == "2500000000000000000"
        assert isinstance(snap.usd_price, Decimal)
        assert snap.usd_price == price_val
        assert isinstance(snap.usd_value, Decimal)
        expected_value = Decimal("2.5") * price_val
        assert snap.usd_value == expected_value

        # Verify persisted in DB
        db_snap = session.get(BalanceSnapshot, snap.id)
        assert db_snap is not None
        assert db_snap.balance == Decimal("2.5")
        assert db_snap.usd_price == price_val
        assert db_snap.usd_value == expected_value


def test_snapshot_token_balance_missing_price(session_factory, seed_data):
    """Missing price leaves usd_price=None, usd_value=None but still writes snapshot."""
    provider = FakePriceProvider({})  # No price for token
    analyzer = DeFiAnalyzer(session_factory, provider, AppConfig())

    with session_factory() as session:
        wallet = session.get(Wallet, seed_data["w1_id"])
        network = session.get(Network, seed_data["net_eth_id"])
        token = session.get(Token, seed_data["tok_usdc_id"])

        raw_balance = 50000000  # 50 USDC
        snap = analyzer.snapshot_token_balance(wallet, network, token, raw_balance)

        assert snap is not None
        assert snap.balance == Decimal(50)
        assert snap.raw_balance == "50000000"
        assert snap.usd_price is None
        assert snap.usd_value is None

        db_snap = session.get(BalanceSnapshot, snap.id)
        assert db_snap is not None
        assert db_snap.balance == Decimal(50)
        assert db_snap.usd_price is None
        assert db_snap.usd_value is None


def test_snapshot_token_balance_provider_exception(session_factory, seed_data):
    """Provider exception leaves usd_price=None, usd_value=None without crashing."""
    provider = FakePriceProvider(should_fail=True)
    analyzer = DeFiAnalyzer(session_factory, provider, AppConfig())

    with session_factory() as session:
        wallet = session.get(Wallet, seed_data["w1_id"])
        network = session.get(Network, seed_data["net_eth_id"])
        token = session.get(Token, seed_data["tok_usdc_id"])

        snap = analyzer.snapshot_token_balance(wallet, network, token, 1000000)
        assert snap is not None
        assert snap.balance == Decimal(1)
        assert snap.usd_price is None
        assert snap.usd_value is None


def test_snapshot_token_balance_provider_result_format(session_factory, seed_data):
    """Handles price provider returning ProviderResult object."""
    price_val = Decimal("0.9998")
    provider = FakePriceProvider({
        ("ethereum", seed_data["usdc_addr"].lower()): ProviderResult(
            status=ProviderStatus.OK, data=price_val, source="mock"
        ),
    })
    analyzer = DeFiAnalyzer(session_factory, provider, AppConfig())

    with session_factory() as session:
        wallet = session.get(Wallet, seed_data["w1_id"])
        network = session.get(Network, seed_data["net_eth_id"])
        token = session.get(Token, seed_data["tok_usdc_id"])

        snap = analyzer.snapshot_token_balance(wallet, network, token, 1000000)
        assert snap.balance == Decimal(1)
        assert snap.usd_price == price_val
        assert snap.usd_value == price_val


def test_snapshot_token_balance_decimals_scaling(session_factory, seed_data):
    """Test 0 decimals, 6 decimals, and 18 decimals scaling via Decimal."""
    provider = FakePriceProvider({
        ("ethereum", seed_data["nft_addr"].lower()): Decimal(50000),
    })
    analyzer = DeFiAnalyzer(session_factory, provider, AppConfig())

    with session_factory() as session:
        wallet = session.get(Wallet, seed_data["w1_id"])
        network = session.get(Network, seed_data["net_eth_id"])

        tok_nft = session.get(Token, seed_data["tok_nft_id"])
        snap_nft = analyzer.snapshot_token_balance(wallet, network, tok_nft, 3)
        assert snap_nft.balance == Decimal(3)
        assert snap_nft.usd_value == Decimal(150000)

        tok_usdc = session.get(Token, seed_data["tok_usdc_id"])
        snap_usdc = analyzer.snapshot_token_balance(wallet, network, tok_usdc, 1234567)
        assert snap_usdc.balance == Decimal("1.234567")


def test_snapshot_token_balance_rejects_float(session_factory, seed_data):
    """Reject float raw_balance to avoid floating-point inaccuracies."""
    analyzer = DeFiAnalyzer(session_factory, None, AppConfig())

    with session_factory() as session:
        wallet = session.get(Wallet, seed_data["w1_id"])
        network = session.get(Network, seed_data["net_eth_id"])
        token = session.get(Token, seed_data["tok_usdc_id"])

        bad_float_val = 12.34
        with pytest.raises(TypeError, match="must be Decimal or int"):
            analyzer.snapshot_token_balance(wallet, network, token, bad_float_val)  # type: ignore


def test_snapshot_token_balance_appends_history(session_factory, seed_data):
    """Each snapshot call adds a new row rather than updating existing."""
    analyzer = DeFiAnalyzer(session_factory, None, AppConfig())

    with session_factory() as session:
        wallet = session.get(Wallet, seed_data["w1_id"])
        network = session.get(Network, seed_data["net_eth_id"])
        token = session.get(Token, seed_data["tok_usdc_id"])

        snap1 = analyzer.snapshot_token_balance(wallet, network, token, 1000000)
        snap2 = analyzer.snapshot_token_balance(wallet, network, token, 2000000)

        assert snap1.id != snap2.id
        assert snap1.balance == Decimal(1)
        assert snap2.balance == Decimal(2)


def test_upsert_position_create_and_dedup(session_factory, seed_data):
    """upsert_position is idempotent per (wallet, network, protocol, position_type)."""
    analyzer = DeFiAnalyzer(session_factory, None, AppConfig())

    with session_factory() as session:
        wallet = session.get(Wallet, seed_data["w1_id"])
        network = session.get(Network, seed_data["net_eth_id"])

        # 1. First call creates
        pos1 = analyzer.upsert_position(
            wallet=wallet,
            network=network,
            protocol="aave-v3",
            position_type="lending",
            amount=Decimal("10.5"),
            usd_value=Decimal(21000),
            certainty="confirmed",
            details="Supplied WETH",
        )
        assert pos1 is not None
        assert pos1.id is not None
        assert pos1.amount == Decimal("10.5")
        assert pos1.usd_value == Decimal(21000)
        assert pos1.certainty == "confirmed"
        first_id = pos1.id

        # 2. Second call updates existing row and returns same ID
        pos2 = analyzer.upsert_position(
            wallet=wallet,
            network=network,
            protocol="aave-v3",
            position_type="lending",
            amount=Decimal("15.0"),
            usd_value=Decimal(30000),
            certainty="confirmed",
            details="Supplied more WETH",
        )
        assert pos2.id == first_id
        assert pos2.amount == Decimal("15.0")
        assert pos2.usd_value == Decimal(30000)
        assert pos2.details == "Supplied more WETH"

        # Verify only 1 row in DB
        positions = analyzer.list_positions(seed_data["w1_id"])
        assert len(positions) == 1
        assert positions[0].id == first_id


def test_upsert_position_invalid_certainty(session_factory, seed_data):
    """certainty must be in {'confirmed', 'inferred', 'unknown'}; anything else raises ValueError."""
    analyzer = DeFiAnalyzer(session_factory, None, AppConfig())

    with session_factory() as session:
        wallet = session.get(Wallet, seed_data["w1_id"])
        network = session.get(Network, seed_data["net_eth_id"])

        with pytest.raises(ValueError, match="certainty"):
            analyzer.upsert_position(
                wallet, network, "uniswap", "liquidity",
                certainty="speculative"
            )

        with pytest.raises(ValueError, match="certainty"):
            analyzer.upsert_position(
                wallet, network, "uniswap", "liquidity",
                certainty="maybe"
            )

        with pytest.raises(ValueError, match="certainty"):
            analyzer.upsert_position(
                wallet, network, "uniswap", "liquidity",
                certainty="CONFIRMED"
            )


def test_upsert_position_rejects_float(session_factory, seed_data):
    """Reject float for amount and usd_value in upsert_position."""
    analyzer = DeFiAnalyzer(session_factory, None, AppConfig())

    with session_factory() as session:
        wallet = session.get(Wallet, seed_data["w1_id"])
        network = session.get(Network, seed_data["net_eth_id"])

        bad_float_amt = 10.5
        with pytest.raises(TypeError, match="must be Decimal"):
            analyzer.upsert_position(
                wallet, network, "aave", "lending",
                amount=bad_float_amt  # type: ignore
            )

        bad_float_val = 100.25
        with pytest.raises(TypeError, match="must be Decimal"):
            analyzer.upsert_position(
                wallet, network, "aave", "lending",
                amount=Decimal(10),
                usd_value=bad_float_val  # type: ignore
            )


def test_aggregate_confirmed_inferred_unknown_split(session_factory, seed_data):
    """aggregate tracks confirmed separately from inferred/unknown and breaks down by protocol/network."""
    analyzer = DeFiAnalyzer(session_factory, None, AppConfig())

    # Seed positions
    w1_id = seed_data["w1_id"]
    w2_id = seed_data["w2_id"]
    eth_id = seed_data["net_eth_id"]
    base_id = seed_data["net_base_id"]

    analyzer.upsert_position(w1_id, eth_id, "Aave", "lending", usd_value=Decimal(500), certainty="confirmed")
    analyzer.upsert_position(w1_id, eth_id, "Uniswap", "liquidity", usd_value=Decimal(300), certainty="inferred")
    analyzer.upsert_position(w1_id, base_id, "Compound", "staking", usd_value=Decimal(200), certainty="unknown")

    # Position for wallet 2
    analyzer.upsert_position(w2_id, eth_id, "Curve", "yield", usd_value=Decimal(1000), certainty="confirmed")

    # Aggregate for wallet 1 only
    agg1 = analyzer.aggregate(wallet_id=w1_id)
    assert agg1["total_value"] == Decimal(1000)
    assert agg1["by_certainty"] == {
        "confirmed": Decimal(500),
        "inferred": Decimal(300),
        "unknown": Decimal(200),
    }
    assert agg1["by_protocol"] == {
        "Aave": Decimal(500),
        "Uniswap": Decimal(300),
        "Compound": Decimal(200),
    }
    assert agg1["by_network"] == {
        "Ethereum": Decimal(800),
        "Base": Decimal(200),
    }

    # Aggregate across all wallets
    agg_all = analyzer.aggregate()
    assert agg_all["total_value"] == Decimal(2000)
    assert agg_all["by_certainty"]["confirmed"] == Decimal(1500)
    assert agg_all["by_certainty"]["inferred"] == Decimal(300)
    assert agg_all["by_certainty"]["unknown"] == Decimal(200)
    assert "Curve" in agg_all["by_protocol"]
    assert agg_all["by_protocol"]["Curve"] == Decimal(1000)


def test_aggregate_empty_returns_zeroes(session_factory):
    """aggregate on empty database returns Decimal(0) and initialized structures."""
    analyzer = DeFiAnalyzer(session_factory, None, AppConfig())
    agg = analyzer.aggregate()

    assert agg["total_value"] == Decimal(0)
    assert agg["by_certainty"] == {
        "confirmed": Decimal(0),
        "inferred": Decimal(0),
        "unknown": Decimal(0),
    }
    assert agg["by_protocol"] == {}
    assert agg["by_network"] == {}


def test_value_history_ordering(session_factory, seed_data):
    """value_history returns snapshots ordered oldest to newest with exact dict format."""
    now = datetime.now(UTC)
    t1 = now - timedelta(hours=3)
    t2 = now - timedelta(hours=2)
    t3 = now - timedelta(hours=1)

    w1_id = seed_data["w1_id"]
    net_id = seed_data["net_eth_id"]
    tok_id = seed_data["tok_usdc_id"]

    # Insert out of order
    with session_factory() as session:
        s2 = BalanceSnapshot(
            wallet_id=w1_id, network_id=net_id, token_id=tok_id,
            balance=Decimal(20), usd_value=Decimal(20), snapshot_at=t2,
        )
        s1 = BalanceSnapshot(
            wallet_id=w1_id, network_id=net_id, token_id=tok_id,
            balance=Decimal(10), usd_value=Decimal(10), snapshot_at=t1,
        )
        s3 = BalanceSnapshot(
            wallet_id=w1_id, network_id=net_id, token_id=tok_id,
            balance=Decimal(30), usd_value=None, snapshot_at=t3,
        )
        session.add_all([s2, s1, s3])
        session.commit()

    analyzer = DeFiAnalyzer(session_factory, None, AppConfig())
    history = analyzer.value_history(wallet_id=w1_id)

    assert len(history) == 3
    # Assert chronological ordering oldest -> newest
    assert history[0]["snapshot_at"] == t1
    assert history[0]["balance"] == Decimal(10)
    assert history[0]["usd_value"] == Decimal(10)

    assert history[1]["snapshot_at"] == t2
    assert history[1]["balance"] == Decimal(20)
    assert history[1]["usd_value"] == Decimal(20)

    assert history[2]["snapshot_at"] == t3
    assert history[2]["balance"] == Decimal(30)
    assert history[2]["usd_value"] is None

    # Check limit parameter
    history_limited = analyzer.value_history(wallet_id=w1_id, limit=2)
    assert len(history_limited) == 2
    assert history_limited[0]["snapshot_at"] == t1
    assert history_limited[1]["snapshot_at"] == t2


@pytest.mark.asyncio
async def test_defi_screen_renders_aggregate_and_positions_table_with_certainty(
    session_factory, seed_data
):
    """DeFiScreen renders aggregate figures and a positions table with a Certainty column."""
    analyzer = DeFiAnalyzer(session_factory, None, AppConfig())
    w1_id = seed_data["w1_id"]
    eth_id = seed_data["net_eth_id"]
    base_id = seed_data["net_base_id"]

    analyzer.upsert_position(
        w1_id, eth_id, "Aave V3", "lending",
        amount=Decimal("5.5"), usd_value=Decimal(11000),
        certainty="confirmed", details="Collateral",
    )
    analyzer.upsert_position(
        w1_id, base_id, "Aerodrome", "liquidity",
        amount=Decimal(100), usd_value=Decimal(2500),
        certainty="inferred", details="LP Pool",
    )

    app = WalletTrackerApp()
    assert app.state is not None
    app.state.session_factory = session_factory

    async with app.run_test(size=(120, 35)) as pilot:
        # Navigate to DeFi screen (key "5")
        await pilot.press("5")
        await pilot.pause()

        assert app.screen.id == "defi"

        # Check aggregate display widgets
        total_lbl = app.screen.query_one("#defi-total-value", Label)
        assert "$13,500" in str(total_lbl.render())

        confirmed_lbl = app.screen.query_one("#defi-confirmed-value", Label)
        assert "$11,000" in str(confirmed_lbl.render())

        inferred_lbl = app.screen.query_one("#defi-inferred-value", Label)
        assert "$2,500" in str(inferred_lbl.render())

        # Check positions table
        table = app.screen.query_one(DataTable)
        assert table is not None

        # Assert Certainty column is present
        column_labels = [str(col.label) for col in table.columns.values()]
        assert any("Certainty" in label for label in column_labels)
        assert any("Protocol" in label for label in column_labels)
        assert any("Type" in label for label in column_labels)
        assert any("USD Value" in label for label in column_labels)

        # Assert rows exist with expected data
        assert table.row_count == 2
