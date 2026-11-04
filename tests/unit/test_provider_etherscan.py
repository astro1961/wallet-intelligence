"""Unit tests for Etherscan v2 API provider using httpx.MockTransport."""
from __future__ import annotations

import logging
from decimal import Decimal

import httpx

from app.providers.base import ProviderStatus, TransactionListResult
from app.providers.etherscan import EtherscanProvider


def make_mock_client(handler, base_url="https://api.etherscan.io/v2/api"):
    return httpx.Client(transport=httpx.MockTransport(handler), base_url=base_url)


def test_etherscan_get_native_balance_success():
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.params.get("module") == "account"
        assert req.url.params.get("action") == "balance"
        assert req.url.params.get("chainid") == "1"
        assert req.url.params.get("address") == "0x1111111111111111111111111111111111111111"
        assert req.url.params.get("tag") == "latest"
        assert req.url.params.get("apikey") == "secret-key"
        return httpx.Response(200, json={"status": "1", "message": "OK", "result": "5780441042197210512"})

    client = make_mock_client(handler)
    provider = EtherscanProvider(client=client, api_key="secret-key", default_chain_id=1)
    res = provider.get_native_balance("0x1111111111111111111111111111111111111111", "ethereum")

    assert res.status == ProviderStatus.OK
    assert isinstance(res.data, Decimal)
    assert res.data == Decimal(5780441042197210512)
    assert res.error is None
    assert res.source == "etherscan"


def test_etherscan_get_transactions_and_mapping():
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.params.get("module") == "account"
        assert req.url.params.get("action") == "txlist"
        return httpx.Response(200, json={
            "status": "1",
            "message": "OK",
            "result": [
                {
                    "hash": "0x111",
                    "from": "0xfrom1",
                    "to": "0xto1",
                    "value": "1000000000000000000",
                    "blockNumber": "26343086",
                    "timeStamp": "1762277795",
                    "isError": "0",
                    "gasUsed": "21000",
                    "gasPrice": "1000000000",
                },
                {
                    "hash": "0x222",
                    "from": "0xfrom2",
                    "to": None,
                    "value": "500",
                    "blockNumber": "26343087",
                    "timeStamp": "1762277800",
                    "isError": "1",
                    "gasUsed": "21000",
                    "gasPrice": "1000000000",
                },
            ],
        })

    client = make_mock_client(handler)
    provider = EtherscanProvider(client=client, api_key="k", default_chain_id=1)
    res = provider.get_transactions("0xaddr", "ethereum")

    assert res.status == ProviderStatus.OK
    assert isinstance(res.data, TransactionListResult)
    assert len(res.data.items) == 2

    tx1 = res.data.items[0]
    assert tx1.hash == "0x111"
    assert tx1.from_address == "0xfrom1"
    assert tx1.to_address == "0xto1"
    assert tx1.value == Decimal(1000000000000000000)
    assert tx1.block_number == 26343086
    assert tx1.timestamp is not None and tx1.timestamp.year == 2025
    assert tx1.status == "ok"

    tx2 = res.data.items[1]
    assert tx2.hash == "0x222"
    assert tx2.from_address == "0xfrom2"
    assert tx2.to_address is None
    assert tx2.value == Decimal(500)
    assert tx2.block_number == 26343087
    assert tx2.timestamp is not None and tx2.timestamp.year == 2025
    assert tx2.status == "error"


def test_etherscan_transactions_pagination():
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        if len(calls) == 1:
            assert "page" not in req.url.params
            assert "offset" not in req.url.params
            return httpx.Response(200, json={
                "status": "1",
                "message": "OK",
                "result": [
                    {"hash": "0x1", "from": "0x1", "to": "0x2", "value": "10", "blockNumber": "1", "timeStamp": "1762277795", "isError": "0"},
                    {"hash": "0x2", "from": "0x1", "to": "0x3", "value": "20", "blockNumber": "2", "timeStamp": "1762277795", "isError": "0"},
                ],
            })
        assert req.url.params.get("page") == "2"
        assert req.url.params.get("offset") == "2"
        return httpx.Response(200, json={
            "status": "1",
            "message": "OK",
            "result": [
                {"hash": "0x3", "from": "0x1", "to": "0x4", "value": "30", "blockNumber": "3", "timeStamp": "1762277795", "isError": "0"},
            ],
        })

    client = make_mock_client(handler)
    provider = EtherscanProvider(client=client, api_key="k", default_chain_id=1, page_size=2)
    r1 = provider.get_transactions("0xaddr", "ethereum")

    assert r1.status == ProviderStatus.OK
    assert len(r1.data.items) == 2
    assert r1.data.next_cursor == {"page": 2, "offset": 2}

    r2 = provider.get_transactions("0xaddr", "ethereum", cursor=r1.data.next_cursor)
    assert r2.status == ProviderStatus.OK
    assert len(r2.data.items) == 1
    assert r2.data.next_cursor is None


def test_etherscan_rate_limited_status_0():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "status": "0",
            "message": "NOTOK",
            "result": "Max rate limit reached, please use API Key",
        })

    client = make_mock_client(handler)
    provider = EtherscanProvider(client=client, api_key="k", max_retries=0)
    res = provider.get_native_balance("0xaddr", "ethereum")

    assert res.status == ProviderStatus.RATE_LIMITED
    assert res.data is None
    assert res.error is not None
    assert "rate limit" in res.error.lower()


def test_etherscan_error_invalid_key():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "status": "0",
            "message": "NOTOK",
            "result": "Invalid API Key",
        })

    client = make_mock_client(handler)
    provider = EtherscanProvider(client=client, api_key="bad-key", max_retries=0)
    res = provider.get_native_balance("0xaddr", "ethereum")

    assert res.status == ProviderStatus.ERROR
    assert res.data is None
    assert "Invalid API Key" in (res.error or "")


def test_etherscan_no_api_key_leak_in_logs_and_errors(caplog):
    secret = "secret-etherscan-key-value"

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"status": "0", "message": "NOTOK", "result": f"Invalid key: {secret}"})

    client = make_mock_client(handler)
    provider = EtherscanProvider(client=client, api_key=secret, max_retries=0)

    with caplog.at_level(logging.DEBUG):
        res = provider.get_native_balance("0xaddr", "ethereum")

    assert res.status == ProviderStatus.ERROR
    assert secret not in (res.error or "")
    assert secret not in caplog.text


def test_etherscan_chain_mapping():
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        return httpx.Response(200, json={"status": "1", "message": "OK", "result": "100"})

    client = make_mock_client(handler)
    provider = EtherscanProvider(client=client, api_key="k", default_chain_id=1)

    provider.get_native_balance("0xaddr", "polygon")
    assert calls[-1].url.params.get("chainid") == "137"

    provider.get_native_balance("0xaddr", "base")
    assert calls[-1].url.params.get("chainid") == "8453"

    provider.get_native_balance("0xaddr", "ethereum")
    assert calls[-1].url.params.get("chainid") == "1"

    provider.get_native_balance("0xaddr", "arbitrum")
    assert calls[-1].url.params.get("chainid") == "42161"


def test_etherscan_unsupported_methods():
    provider = EtherscanProvider(client=None, api_key="k")

    tok_bal = provider.get_token_balances("0xaddr", "ethereum")
    assert tok_bal.status == ProviderStatus.UNSUPPORTED
    assert tok_bal.error is not None

    tok_meta = provider.get_token_metadata("0xtoken", "ethereum")
    assert tok_meta.status == ProviderStatus.UNSUPPORTED
    assert tok_meta.error is not None

    tx_det = provider.get_transaction_details("0xtx", "ethereum")
    assert tx_det.status == ProviderStatus.UNSUPPORTED
    assert tx_det.error is not None


def test_etherscan_latest_block_and_health():
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.params.get("module") == "proxy"
        assert req.url.params.get("action") == "eth_blockNumber"
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": "0x191d2f0"})

    client = make_mock_client(handler)
    provider = EtherscanProvider(client=client, api_key="k", default_chain_id=1)

    block_res = provider.get_latest_block("ethereum")
    assert block_res.status == ProviderStatus.OK
    assert block_res.data == 26333936

    health = provider.health_check("ethereum")
    assert health.status == ProviderStatus.OK
    assert health.data == 26333936


def test_etherscan_retry_429_then_succeed():
    attempts = 0

    def handler(req: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, json={"message": "rate limit exceeded"})
        return httpx.Response(200, json={"status": "1", "message": "OK", "result": "42"})

    client = make_mock_client(handler)
    provider = EtherscanProvider(client=client, api_key="k", max_retries=2, backoff_base=0.01)
    res = provider.get_native_balance("0xaddr", "ethereum")

    assert res.status == ProviderStatus.OK
    assert res.data == Decimal(42)
    assert attempts == 2


def test_etherscan_server_error_500_after_retries():
    attempts = 0

    def handler(req: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(500, json={"message": "internal server error"})

    client = make_mock_client(handler)
    provider = EtherscanProvider(client=client, api_key="k", max_retries=1, backoff_base=0.01)
    res = provider.get_native_balance("0xaddr", "ethereum")

    assert res.status == ProviderStatus.ERROR
    assert res.error is not None
    assert attempts == 2
