"""Unit tests for Blockscout Pro API provider using httpx.MockTransport."""
from __future__ import annotations

import logging
from decimal import Decimal

import httpx

from app.providers.base import ProviderStatus, TransactionListResult
from app.providers.blockscout import BlockscoutProvider


def make_mock_client(handler, base_url="https://api.blockscout.com"):
    return httpx.Client(transport=httpx.MockTransport(handler), base_url=base_url)


def test_blockscout_get_native_balance_success():
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/1/api/v2/addresses/0x1111111111111111111111111111111111111111"
        assert req.url.params.get("apikey") == "secret-key"
        return httpx.Response(200, json={"coin_balance": "5780441042197210512", "is_contract": False})

    client = make_mock_client(handler)
    provider = BlockscoutProvider(client=client, api_key="secret-key", chain_id=1)
    res = provider.get_native_balance("0x1111111111111111111111111111111111111111", "ethereum")

    assert res.status == ProviderStatus.OK
    assert isinstance(res.data, Decimal)
    assert res.data == Decimal(5780441042197210512)
    assert res.error is None
    assert res.source == "blockscout"


def test_blockscout_get_transactions_and_cursor():
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        if len(calls) == 1:
            assert "index" not in req.url.params
            return httpx.Response(200, json={
                "items": [
                    {
                        "hash": "0xabc",
                        "from": {"hash": "0xfrom"},
                        "to": {"hash": "0xto"},
                        "value": "1000000000000000000",
                        "block_number": 12345,
                        "timestamp": "2026-11-04T12:00:00Z",
                        "status": "ok",
                    }
                ],
                "next_page_params": {"index": 50, "items_count": 50},
            })
        assert req.url.params.get("index") == "50"
        return httpx.Response(200, json={"items": [], "next_page_params": None})

    client = make_mock_client(handler)
    provider = BlockscoutProvider(client=client, api_key="test-key", chain_id=1)
    r1 = provider.get_transactions("0xaddr", "ethereum")

    assert r1.status == ProviderStatus.OK
    assert isinstance(r1.data, TransactionListResult)
    assert len(r1.data.items) == 1
    tx = r1.data.items[0]
    assert tx.hash == "0xabc"
    assert tx.from_address == "0xfrom"
    assert tx.to_address == "0xto"
    assert tx.value == Decimal(1000000000000000000)
    assert tx.block_number == 12345
    assert tx.status == "ok"
    assert r1.data.next_cursor == {"index": 50, "items_count": 50}

    r2 = provider.get_transactions("0xaddr", "ethereum", cursor=r1.data.next_cursor)
    assert r2.status == ProviderStatus.OK
    assert len(r2.data.items) == 0
    assert r2.data.next_cursor is None


def test_blockscout_retry_429_then_succeed():
    attempts = 0

    def handler(req: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, json={"message": "rate limit exceeded"})
        return httpx.Response(200, json={"coin_balance": "42"})

    client = make_mock_client(handler)
    provider = BlockscoutProvider(client=client, api_key="k", max_retries=2, backoff_base=0.01)
    res = provider.get_native_balance("0xaddr", "ethereum")

    assert res.status == ProviderStatus.OK
    assert res.data == Decimal(42)
    assert attempts == 2


def test_blockscout_rate_limited_after_retries():
    attempts = 0

    def handler(req: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(429, json={"message": "too many requests"})

    client = make_mock_client(handler)
    provider = BlockscoutProvider(client=client, api_key="k", max_retries=1, backoff_base=0.01)
    res = provider.get_native_balance("0xaddr", "ethereum")

    assert res.status == ProviderStatus.RATE_LIMITED
    assert res.error is not None
    assert attempts == 2


def test_blockscout_error_500_after_retries():
    attempts = 0

    def handler(req: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(500, json={"message": "internal server error"})

    client = make_mock_client(handler)
    provider = BlockscoutProvider(client=client, api_key="k", max_retries=1, backoff_base=0.01)
    res = provider.get_native_balance("0xaddr", "ethereum")

    assert res.status == ProviderStatus.ERROR
    assert res.error is not None
    assert attempts == 2


def test_blockscout_no_api_key_leak_in_logs_or_errors(caplog):
    secret = "very-confidential-api-key"

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text=f"server error at url {req.url}")

    client = make_mock_client(handler)
    provider = BlockscoutProvider(client=client, api_key=secret, max_retries=0)

    with caplog.at_level(logging.DEBUG):
        res = provider.get_native_balance("0xaddr", "ethereum")

    assert res.status == ProviderStatus.ERROR
    assert res.error is not None
    assert secret not in res.error
    assert secret not in caplog.text


def test_blockscout_latest_block_and_health():
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/1/api/v2/stats"
        return httpx.Response(200, json={"total_blocks": "26342704"})

    client = make_mock_client(handler)
    provider = BlockscoutProvider(client=client, api_key="k", chain_id=1)

    block_res = provider.get_latest_block("ethereum")
    assert block_res.status == ProviderStatus.OK
    assert block_res.data == 26342704

    health = provider.health_check("ethereum")
    assert health.status == ProviderStatus.OK
    assert health.data == 26342704
