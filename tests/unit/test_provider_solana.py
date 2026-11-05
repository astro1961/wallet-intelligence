"""Unit tests for Solana JSON-RPC data provider (Stage 9C)."""
from __future__ import annotations

import ast
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.providers.base import ProviderStatus
from app.providers.solana import SolanaProvider

VALID_SOLANA_ADDR = "9xQeWvG816bUx9EPjHmaT23yvVM2ZWbrrpZb9PusVFin"
ANOTHER_SOLANA_ADDR = "So11111111111111111111111111111111111111112"


def _make_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.mainnet-beta.solana.com")


def test_solana_provider_init_and_attributes():
    client = _make_client(lambda req: httpx.Response(200, json={}))
    provider = SolanaProvider(rpc_url="https://api.mainnet-beta.solana.com", client=client)

    assert provider.name == "solana"
    assert provider.rpc_url == "https://api.mainnet-beta.solana.com"
    assert provider.client is client


def test_solana_provider_default_client():
    provider = SolanaProvider(rpc_url="https://api.mainnet-beta.solana.com")
    assert provider.client is not None
    provider.close()


def test_get_native_balance_success_with_value_dict():
    def handler(request: httpx.Request) -> httpx.Response:
        data = json.loads(request.content)
        assert data["jsonrpc"] == "2.0"
        assert data["method"] == "getBalance"
        assert data["params"] == [VALID_SOLANA_ADDR]
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "result": {
                    "context": {"slot": 123456},
                    "value": 3141592653,
                },
            },
        )

    client = _make_client(handler)
    provider = SolanaProvider(rpc_url="https://api.mainnet-beta.solana.com", client=client)
    res = provider.get_native_balance(VALID_SOLANA_ADDR, "solana")

    assert res.status == ProviderStatus.OK
    assert isinstance(res.data, Decimal)
    assert not isinstance(res.data, float)
    assert res.data == Decimal(3141592653)
    assert res.source == "solana"
    assert res.error is None


def test_get_native_balance_success_direct_int_result():
    def handler(request: httpx.Request) -> httpx.Response:
        data = json.loads(request.content)
        assert data["method"] == "getBalance"
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "result": 1000000000,
            },
        )

    client = _make_client(handler)
    provider = SolanaProvider(rpc_url="https://api.mainnet-beta.solana.com", client=client)
    res = provider.get_native_balance(ANOTHER_SOLANA_ADDR, "solana")

    assert res.status == ProviderStatus.OK
    assert isinstance(res.data, Decimal)
    assert not isinstance(res.data, float)
    assert res.data == Decimal(1000000000)


def test_get_native_balance_zero_lamports():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "result": {"context": {"slot": 1}, "value": 0},
            },
        )

    client = _make_client(handler)
    provider = SolanaProvider(rpc_url="https://api.mainnet-beta.solana.com", client=client)
    res = provider.get_native_balance(VALID_SOLANA_ADDR, "solana")

    assert res.status == ProviderStatus.OK
    assert isinstance(res.data, Decimal)
    assert res.data == Decimal(0)


@pytest.mark.parametrize(
    "invalid_address",
    [
        "0x1111111111111111111111111111111111111111",  # EVM hex address
        "0X5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed",  # EVM hex address
        "not_a_valid_solana_address!",                 # invalid characters
        "short",                                        # too short
        "",                                             # empty
        None,                                           # NoneType
    ],
)
def test_get_native_balance_invalid_address_returns_error_not_exception(invalid_address: Any):
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={"jsonrpc": "2.0", "result": 100})

    client = _make_client(handler)
    provider = SolanaProvider(rpc_url="https://api.mainnet-beta.solana.com", client=client)

    # Must never raise an exception, must return ERROR with data=None
    res = provider.get_native_balance(invalid_address, "solana")
    assert res.status == ProviderStatus.ERROR
    assert res.data is None
    assert res.error is not None
    assert "invalid" in res.error.lower()
    assert not called, "Handler should not be called for invalid address"


def test_get_native_balance_rpc_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "error": {"code": -32602, "message": "Invalid param: Invalid"},
            },
        )

    client = _make_client(handler)
    provider = SolanaProvider(rpc_url="https://api.mainnet-beta.solana.com", client=client)
    res = provider.get_native_balance(VALID_SOLANA_ADDR, "solana")

    assert res.status == ProviderStatus.ERROR
    assert res.data is None
    assert "Invalid param" in (res.error or "")


def test_get_native_balance_transport_and_http_errors():
    # 1. Transport error
    def transport_err_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused")

    client1 = _make_client(transport_err_handler)
    provider1 = SolanaProvider(rpc_url="https://api.mainnet-beta.solana.com", client=client1)
    res1 = provider1.get_native_balance(VALID_SOLANA_ADDR, "solana")
    assert res1.status == ProviderStatus.ERROR
    assert res1.data is None

    # 2. HTTP 500
    def server_err_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="Internal Server Error")

    client2 = _make_client(server_err_handler)
    provider2 = SolanaProvider(rpc_url="https://api.mainnet-beta.solana.com", client=client2)
    res2 = provider2.get_native_balance(VALID_SOLANA_ADDR, "solana")
    assert res2.status == ProviderStatus.ERROR
    assert res2.data is None

    # 3. HTTP 429 Rate limited
    def rate_limit_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="Too Many Requests")

    client3 = _make_client(rate_limit_handler)
    provider3 = SolanaProvider(rpc_url="https://api.mainnet-beta.solana.com", client=client3)
    res3 = provider3.get_native_balance(VALID_SOLANA_ADDR, "solana")
    assert res3.status == ProviderStatus.RATE_LIMITED
    assert res3.data is None


def test_get_latest_block_success():
    def handler(request: httpx.Request) -> httpx.Response:
        data = json.loads(request.content)
        assert data["jsonrpc"] == "2.0"
        assert data["method"] == "getSlot"
        assert data["params"] == []
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "result": 284910234,
            },
        )

    client = _make_client(handler)
    provider = SolanaProvider(rpc_url="https://api.mainnet-beta.solana.com", client=client)
    res = provider.get_latest_block("solana")

    assert res.status == ProviderStatus.OK
    assert isinstance(res.data, int)
    assert not isinstance(res.data, float)
    assert res.data == 284910234
    assert res.source == "solana"
    assert res.error is None


def test_get_latest_block_dict_result():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "result": {"context": {"slot": 10}, "value": 300100200},
            },
        )

    client = _make_client(handler)
    provider = SolanaProvider(rpc_url="https://api.mainnet-beta.solana.com", client=client)
    res = provider.get_latest_block("solana")

    assert res.status == ProviderStatus.OK
    assert isinstance(res.data, int)
    assert res.data == 300100200


def test_get_latest_block_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "error": {"code": -32000, "message": "Slot not found"},
            },
        )

    client = _make_client(handler)
    provider = SolanaProvider(rpc_url="https://api.mainnet-beta.solana.com", client=client)
    res = provider.get_latest_block("solana")

    assert res.status == ProviderStatus.ERROR
    assert "Slot not found" in (res.error or "")


def test_health_check_ok():
    def handler(request: httpx.Request) -> httpx.Response:
        data = json.loads(request.content)
        assert data["jsonrpc"] == "2.0"
        assert data["method"] == "getHealth"
        assert data["params"] == []
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "result": "ok",
            },
        )

    client = _make_client(handler)
    provider = SolanaProvider(rpc_url="https://api.mainnet-beta.solana.com", client=client)
    res = provider.health_check("solana")

    assert res.status == ProviderStatus.OK
    assert res.source == "solana"


@pytest.mark.parametrize(
    "status_code,body",
    [
        (200, {"jsonrpc": "2.0", "id": 1, "error": {"code": -32005, "message": "Node is behind"}}),
        (200, {"jsonrpc": "2.0", "id": 1, "result": "unhealthy"}),
        (200, {"jsonrpc": "2.0", "id": 1, "result": None}),
        (500, {"error": "Server error"}),
        (503, {"error": "Service unavailable"}),
    ],
)
def test_health_check_anything_other_than_ok_returns_error(status_code: int, body: dict[str, Any]):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json=body)

    client = _make_client(handler)
    provider = SolanaProvider(rpc_url="https://api.mainnet-beta.solana.com", client=client)
    res = provider.health_check("solana")

    assert res.status == ProviderStatus.ERROR


def test_health_check_transport_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("Timeout")

    client = _make_client(handler)
    provider = SolanaProvider(rpc_url="https://api.mainnet-beta.solana.com", client=client)
    res = provider.health_check("solana")

    assert res.status == ProviderStatus.ERROR


def test_explicit_unsupported_methods():
    client = _make_client(lambda req: httpx.Response(200, json={}))
    provider = SolanaProvider(rpc_url="https://api.mainnet-beta.solana.com", client=client)

    res_txs = provider.get_transactions(VALID_SOLANA_ADDR, "solana")
    assert res_txs.status == ProviderStatus.UNSUPPORTED
    assert res_txs.source == "solana"

    res_tokens = provider.get_token_balances(VALID_SOLANA_ADDR, "solana")
    assert res_tokens.status == ProviderStatus.UNSUPPORTED
    assert res_tokens.source == "solana"

    res_details = provider.get_transaction_details("5VERv8NMvBoJmDXknsqe...", "solana")
    assert res_details.status == ProviderStatus.UNSUPPORTED
    assert res_details.source == "solana"

    res_meta = provider.get_token_metadata(VALID_SOLANA_ADDR, "solana")
    assert res_meta.status == ProviderStatus.UNSUPPORTED
    assert res_meta.source == "solana"


def test_no_float_hygiene():
    """Ensure app/providers/solana.py contains zero float literals or 'float' names."""
    src = Path("app/providers/solana.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, float):
            pytest.fail(f"Found float constant {node.value} in app/providers/solana.py")
        if isinstance(node, ast.Name) and node.id == "float":
            pytest.fail("Found 'float' identifier in app/providers/solana.py")


def test_no_hex_decoding_hygiene():
    """Verify that integer JSON results are treated as decimal numbers, not hex."""
    # If 1000 was hex decoded, it would be 4096. We verify it remains Decimal(1000).
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "result": {"value": 1000},
            },
        )

    client = _make_client(handler)
    provider = SolanaProvider(rpc_url="https://api.mainnet-beta.solana.com", client=client)
    res = provider.get_native_balance(VALID_SOLANA_ADDR, "solana")

    assert res.status == ProviderStatus.OK
    assert res.data == Decimal(1000)
    assert res.data != Decimal(4096)
