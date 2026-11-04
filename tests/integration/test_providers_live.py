"""Live integration tests for external providers with real network calls."""
from __future__ import annotations

import os
from decimal import Decimal

import pytest
from dotenv import load_dotenv

from app.providers.base import ProviderStatus
from app.providers.blockscout import BlockscoutProvider
from app.providers.etherscan import EtherscanProvider

load_dotenv()

VITALIK = "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045"


@pytest.mark.live
def test_blockscout_live_vitalik_balance_and_latest_block():
    api_key = os.getenv("BLOCKSCOUT_API_KEY")
    if not api_key:
        pytest.skip("BLOCKSCOUT_API_KEY not configured in environment")

    provider = BlockscoutProvider(
        api_key=api_key,
        chain_id=1,
        base_url="https://api.blockscout.com",
        max_retries=3,
        backoff_base=1.0,
        rps=5.0,
    )

    # 1. Test native balance for Vitalik's address
    bal_res = provider.get_native_balance(VITALIK, "ethereum")
    assert bal_res.status == ProviderStatus.OK, f"get_native_balance failed: {bal_res.error}"
    assert isinstance(bal_res.data, Decimal), "Native balance must be Decimal"
    assert bal_res.data > 0, f"Expected Vitalik balance > 0, got {bal_res.data}"

    # 2. Test latest block number
    block_res = provider.get_latest_block("ethereum")
    assert block_res.status == ProviderStatus.OK, f"get_latest_block failed: {block_res.error}"
    assert isinstance(block_res.data, int), "Latest block must be int"
    assert block_res.data > 26_000_000, f"Expected block > 26_000_000, got {block_res.data}"

    # 3. Test health check
    health_res = provider.health_check("ethereum")
    assert health_res.status == ProviderStatus.OK
    assert health_res.data > 26_000_000


@pytest.mark.live
def test_etherscan_live_and_cross_check_with_blockscout():
    bs_key = os.getenv("BLOCKSCOUT_API_KEY")
    es_key = os.getenv("ETHERSCAN_API_KEY")
    if not bs_key:
        pytest.skip("BLOCKSCOUT_API_KEY not configured in environment")
    if not es_key:
        pytest.skip("ETHERSCAN_API_KEY not configured in environment")

    bs_provider = BlockscoutProvider(
        api_key=bs_key,
        chain_id=1,
        base_url="https://api.blockscout.com",
    )
    es_provider = EtherscanProvider(
        api_key=es_key,
        default_chain_id=1,
        base_url="https://api.etherscan.io/v2/api",
    )

    bs_res = bs_provider.get_native_balance(VITALIK, "ethereum")
    assert bs_res.status == ProviderStatus.OK, f"Blockscout get_native_balance failed: {bs_res.error}"

    es_res = es_provider.get_native_balance(VITALIK, "ethereum")
    assert es_res.status == ProviderStatus.OK, f"Etherscan get_native_balance failed: {es_res.error}"

    assert isinstance(es_res.data, Decimal)
    assert es_res.data > 0
    assert bs_res.data == es_res.data, (
        f"Cross-check balance mismatch: Blockscout={bs_res.data} != Etherscan={es_res.data}"
    )

    es_health = es_provider.health_check("ethereum")
    assert es_health.status == ProviderStatus.OK
    assert isinstance(es_health.data, int)
    assert es_health.data > 26_000_000
