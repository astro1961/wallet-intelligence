"""Unit tests for RpcFailoverProvider with ordered endpoint failover."""
from __future__ import annotations

import json
from decimal import Decimal

import httpx

from app.providers.base import ProviderStatus
from app.providers.rpc_failover import RpcFailoverProvider


def make_mock_client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_fails_over_on_5xx():
    call_log: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        call_log.append(str(req.url))
        if "ep1" in str(req.url):
            return httpx.Response(500, text="Internal Server Error")
        return httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": 1, "result": "0x5035a1c5bd6bf8b90"},
        )

    client = make_mock_client(handler)
    endpoints = ["https://ep1.example.com", "https://ep2.example.com"]
    provider = RpcFailoverProvider(endpoints=endpoints, client=client)

    res = provider.get_native_balance("0x1111111111111111111111111111111111111111", "ethereum")

    assert res.status == ProviderStatus.OK
    assert isinstance(res.data, Decimal)
    assert res.data == Decimal(int("0x5035a1c5bd6bf8b90", 16))
    assert res.source == "https://ep2.example.com"
    assert call_log == ["https://ep1.example.com", "https://ep2.example.com"]
    assert provider.healthy["https://ep1.example.com"] is False
    assert provider.healthy["https://ep2.example.com"] is True


def test_fails_over_on_transport_error():
    call_log: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        call_log.append(str(req.url))
        if "ep1" in str(req.url):
            raise httpx.ConnectError("Connection refused by ep1")
        return httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": 1, "result": "0x191d2f0"},
        )

    client = make_mock_client(handler)
    endpoints = ["https://ep1.example.com", "https://ep2.example.com"]
    provider = RpcFailoverProvider(endpoints=endpoints, client=client)

    res = provider.get_latest_block("ethereum")

    assert res.status == ProviderStatus.OK
    assert isinstance(res.data, int)
    assert not isinstance(res.data, bool)
    assert res.data == int("0x191d2f0", 16)
    assert res.source == "https://ep2.example.com"
    assert provider.healthy["https://ep1.example.com"] is False
    assert provider.healthy["https://ep2.example.com"] is True


def test_fails_over_on_429():
    call_log: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        call_log.append(str(req.url))
        if "ep1" in str(req.url):
            return httpx.Response(429, text="Rate limit exceeded")
        return httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": 1, "result": "0x10"},
        )

    client = make_mock_client(handler)
    endpoints = ["https://ep1.example.com", "https://ep2.example.com"]
    provider = RpcFailoverProvider(endpoints=endpoints, client=client)

    res = provider.get_native_balance("0xaddr", "ethereum")

    assert res.status == ProviderStatus.OK
    assert res.data == Decimal(16)
    assert res.source == "https://ep2.example.com"
    assert provider.healthy["https://ep1.example.com"] is False
    assert provider.healthy["https://ep2.example.com"] is True


def test_fails_over_on_json_rpc_error():
    call_log: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        call_log.append(str(req.url))
        if "ep1" in str(req.url):
            return httpx.Response(
                200,
                json={"jsonrpc": "2.0", "id": 1, "error": {"code": -32601, "message": "Method not found"}},
            )
        return httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": 1, "result": "0x20"},
        )

    client = make_mock_client(handler)
    endpoints = ["https://ep1.example.com", "https://ep2.example.com"]
    provider = RpcFailoverProvider(endpoints=endpoints, client=client)

    res = provider.get_native_balance("0xaddr", "ethereum")

    assert res.status == ProviderStatus.OK
    assert res.data == Decimal(32)
    assert res.source == "https://ep2.example.com"
    assert provider.healthy["https://ep1.example.com"] is False
    assert provider.healthy["https://ep2.example.com"] is True


def test_all_down_returns_error_not_exception():
    def handler(req: httpx.Request) -> httpx.Response:
        if "ep1" in str(req.url):
            return httpx.Response(503, text="Service Unavailable")
        raise httpx.ReadTimeout("Read timed out on ep2")

    client = make_mock_client(handler)
    endpoints = ["https://ep1.example.com", "https://ep2.example.com"]
    provider = RpcFailoverProvider(endpoints=endpoints, client=client)

    res = provider.get_native_balance("0xaddr", "ethereum")

    assert res.status == ProviderStatus.ERROR
    assert res.data is None
    assert res.error is not None
    assert "Read timed out" in res.error
    assert provider.healthy["https://ep1.example.com"] is False
    assert provider.healthy["https://ep2.example.com"] is False


def test_all_down_429_returns_error_status():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="Too Many Requests")

    client = make_mock_client(handler)
    endpoints = ["https://ep1.example.com", "https://ep2.example.com"]
    provider = RpcFailoverProvider(endpoints=endpoints, client=client)

    res = provider.get_latest_block("ethereum")

    assert res.status == ProviderStatus.ERROR
    assert res.data is None
    assert res.error is not None
    assert "Too Many Requests" in res.error
    assert provider.healthy["https://ep1.example.com"] is False
    assert provider.healthy["https://ep2.example.com"] is False


def test_hex_parsing_for_balance_and_block():
    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        if body["method"] == "eth_getBalance":
            return httpx.Response(
                200,
                json={"jsonrpc": "2.0", "id": 1, "result": "0x5035a1c5bd6bf8b90"},
            )
        if body["method"] == "eth_blockNumber":
            return httpx.Response(
                200,
                json={"jsonrpc": "2.0", "id": 1, "result": "0x191d2f0"},
            )
        raise ValueError(f"Unknown method {body['method']}")

    client = make_mock_client(handler)
    provider = RpcFailoverProvider(endpoints=["https://ep1.example.com"], client=client)

    bal_res = provider.get_native_balance("0x1111111111111111111111111111111111111111", "ethereum")
    assert bal_res.status == ProviderStatus.OK
    assert isinstance(bal_res.data, Decimal)
    assert not isinstance(bal_res.data, float)
    assert bal_res.data == Decimal(int("0x5035a1c5bd6bf8b90", 16))

    block_res = provider.get_latest_block("ethereum")
    assert block_res.status == ProviderStatus.OK
    assert isinstance(block_res.data, int)
    assert not isinstance(block_res.data, bool)
    assert not isinstance(block_res.data, float)
    assert block_res.data == int("0x191d2f0", 16)


def test_recovery_after_primary_restored():
    primary_healthy = False

    def handler(req: httpx.Request) -> httpx.Response:
        nonlocal primary_healthy
        if "ep1" in str(req.url):
            if not primary_healthy:
                return httpx.Response(500, text="Primary down")
            return httpx.Response(
                200,
                json={"jsonrpc": "2.0", "id": 1, "result": "0x100"},
            )
        if "ep2" in str(req.url):
            return httpx.Response(
                200,
                json={"jsonrpc": "2.0", "id": 1, "result": "0x200"},
            )
        return httpx.Response(404)

    client = make_mock_client(handler)
    endpoints = ["https://ep1.example.com", "https://ep2.example.com"]
    provider = RpcFailoverProvider(endpoints=endpoints, client=client)

    # Call 1: primary down -> fails over to ep2
    res1 = provider.get_native_balance("0xaddr", "ethereum")
    assert res1.status == ProviderStatus.OK
    assert res1.data == Decimal(int("0x200", 16))
    assert res1.source == "https://ep2.example.com"
    assert provider.healthy["https://ep1.example.com"] is False
    assert provider.healthy["https://ep2.example.com"] is True

    # Primary is restored!
    primary_healthy = True

    # Call 2: primary is retried in order and becomes source again!
    res2 = provider.get_native_balance("0xaddr", "ethereum")
    assert res2.status == ProviderStatus.OK
    assert res2.data == Decimal(int("0x100", 16))
    assert res2.source == "https://ep1.example.com"
    assert provider.healthy["https://ep1.example.com"] is True
    assert provider.healthy["https://ep2.example.com"] is True


def test_healthy_is_observability_not_call_filter():
    ep1_attempts = 0

    def handler(req: httpx.Request) -> httpx.Response:
        nonlocal ep1_attempts
        if "ep1" in str(req.url):
            ep1_attempts += 1
            return httpx.Response(500, text="Down")
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": "0x1"})

    client = make_mock_client(handler)
    endpoints = ["https://ep1.example.com", "https://ep2.example.com"]
    provider = RpcFailoverProvider(endpoints=endpoints, client=client)

    # Initially both healthy
    assert provider.healthy["https://ep1.example.com"] is True
    assert provider.healthy["https://ep2.example.com"] is True

    # First call
    provider.get_latest_block("ethereum")
    assert ep1_attempts == 1
    assert provider.healthy["https://ep1.example.com"] is False

    # Second call must STILL attempt ep1 despite healthy=False
    provider.get_latest_block("ethereum")
    assert ep1_attempts == 2
    assert provider.healthy["https://ep1.example.com"] is False


def test_explicit_unsupported_methods():
    client = make_mock_client(lambda r: httpx.Response(200, json={}))
    provider = RpcFailoverProvider(endpoints=["https://ep1.example.com"], client=client)

    r_tx = provider.get_transactions("0xaddr", "ethereum")
    assert r_tx.status == ProviderStatus.UNSUPPORTED
    assert r_tx.data is None
    assert r_tx.source == "rpc_failover"

    r_bal = provider.get_token_balances("0xaddr", "ethereum")
    assert r_bal.status == ProviderStatus.UNSUPPORTED
    assert r_bal.data is None
    assert r_bal.source == "rpc_failover"

    r_det = provider.get_transaction_details("0xhash", "ethereum")
    assert r_det.status == ProviderStatus.UNSUPPORTED
    assert r_det.data is None
    assert r_det.source == "rpc_failover"

    r_meta = provider.get_token_metadata("0xcontract", "ethereum")
    assert r_meta.status == ProviderStatus.UNSUPPORTED
    assert r_meta.data is None
    assert r_meta.source == "rpc_failover"


def test_health_check_success_and_failure():
    def success_handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": "0x10"})

    client_ok = make_mock_client(success_handler)
    p_ok = RpcFailoverProvider(endpoints=["https://ep1.example.com"], client=client_ok)
    res_ok = p_ok.health_check("ethereum")
    assert res_ok.status == ProviderStatus.OK
    assert res_ok.data == 16
    assert res_ok.source == "https://ep1.example.com"

    def fail_handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="Down")

    client_fail = make_mock_client(fail_handler)
    p_fail = RpcFailoverProvider(endpoints=["https://ep1.example.com"], client=client_fail)
    res_fail = p_fail.health_check("ethereum")
    assert res_fail.status == ProviderStatus.ERROR
    assert res_fail.data is None


def test_empty_endpoints_list():
    client = make_mock_client(lambda r: httpx.Response(200))
    provider = RpcFailoverProvider(endpoints=[], client=client)

    res = provider.get_native_balance("0xaddr", "ethereum")
    assert res.status == ProviderStatus.ERROR
    assert res.data is None
    assert "No RPC endpoints" in (res.error or "")
    assert provider.healthy == {}


def test_invalid_hex_fails_over():
    call_log = []

    def handler(req: httpx.Request) -> httpx.Response:
        call_log.append(str(req.url))
        if "ep1" in str(req.url):
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": "invalid_hex"})
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": "0x30"})

    client = make_mock_client(handler)
    provider = RpcFailoverProvider(
        endpoints=["https://ep1.example.com", "https://ep2.example.com"],
        client=client,
    )
    res = provider.get_native_balance("0xaddr", "ethereum")
    assert res.status == ProviderStatus.OK
    assert res.data == Decimal(48)
    assert res.source == "https://ep2.example.com"
    assert provider.healthy["https://ep1.example.com"] is False
    assert provider.healthy["https://ep2.example.com"] is True


def test_retries_and_backoff_on_endpoint():
    attempts = 0

    def handler(req: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(500, text="Temporary glitch")
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": "0x5"})

    client = make_mock_client(handler)
    provider = RpcFailoverProvider(
        endpoints=["https://ep1.example.com"],
        client=client,
        max_retries=1,
        backoff_base=0.001,
    )

    res = provider.get_latest_block("ethereum")
    assert res.status == ProviderStatus.OK
    assert res.data == 5
    assert attempts == 2
    assert provider.healthy["https://ep1.example.com"] is True
