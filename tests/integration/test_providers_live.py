"""Live integration tests for external providers with real network calls."""
from __future__ import annotations

import os
from decimal import Decimal

import pytest
from dotenv import load_dotenv

from app.providers.base import ProviderStatus
from app.providers.blockscout import BlockscoutProvider

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
