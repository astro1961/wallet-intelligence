"""Unit tests for Network Manager and network seeding from config."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.config import AppConfig, NetworkConfig
from app.core.network_manager import ensure_networks_from_config
from app.database.models import Base, Network


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    sm = sessionmaker(bind=engine, expire_on_commit=False)
    with sm() as s:
        yield s


def test_ensure_networks_from_config(session: Session):
    cfg = AppConfig(
        networks=[
            NetworkConfig(
                name="Ethereum",
                chain_type="evm",
                chain_id=1,
                rpc_url="https://eth.llamarpc.com",
                explorer_url="https://etherscan.io",
                native_token="ETH",
                symbol="ETH",
                decimals=18,
                enabled=True,
                is_testnet=False,
            ),
            NetworkConfig(
                name="Arbitrum",
                chain_type="evm",
                chain_id=42161,
                rpc_url="https://arb1.arbitrum.io/rpc",
                explorer_url="https://arbiscan.io",
                native_token="ETH",
                symbol="ETH",
                decimals=18,
                enabled=True,
                is_testnet=False,
            ),
        ]
    )

    created = ensure_networks_from_config(session, cfg)
    assert created == 2

    nets = list(session.execute(select(Network)).scalars().all())
    assert len(nets) == 2
    net_map = {n.name: n for n in nets}
    assert "Ethereum" in net_map
    assert net_map["Ethereum"].chain_id == 1
    assert net_map["Arbitrum"].chain_id == 42161

    # Second run must be idempotent
    created_second = ensure_networks_from_config(session, cfg)
    assert created_second == 0
    assert len(list(session.execute(select(Network)).scalars().all())) == 2
