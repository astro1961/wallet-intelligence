"""Unit tests for EVM JSON-RPC provider using httpx.MockTransport."""
from __future__ import annotations

import json
from decimal import Decimal

import httpx

from app.providers.base import ProviderStatus
from app.providers.evm_rpc import EvmRpcProvider


def make_mock_client(handler, base_url="https://rpc.example"):
    return httpx.Client(transport=httpx.MockTransport(handler), base_url=base_url)


def test_evm_rpc_get_native_balance_hex():
    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        assert body["method"] == "eth_getBalance"
        assert body["params"][0] == "0x1111111111111111111111111111111111111111"
        assert body["params"][1] == "latest"
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": "0x5035a1c5bd6bf8b90"})

    client = make_mock_client(handler)
    provider = EvmRpcProvider(client=client, rpc_url="https://rpc.example")
    res = provider.get_native_balance("0x1111111111111111111111111111111111111111", "ethereum")

    assert res.status == ProviderStatus.OK
    assert isinstance(res.data, Decimal)
    assert res.data == Decimal(str(int("0x5035a1c5bd6bf8b90", 16)))
    assert res.source == "evm_rpc"


def test_evm_rpc_get_latest_block():
    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        assert body["method"] == "eth_blockNumber"
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": "0x191d2f0"})

    client = make_mock_client(handler)
    provider = EvmRpcProvider(client=client, rpc_url="https://rpc.example")
    res = provider.get_latest_block("ethereum")

    assert res.status == ProviderStatus.OK
    assert isinstance(res.data, int)
    assert res.data == int("0x191d2f0", 16)


def test_evm_rpc_get_transaction_details():
    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        assert body["method"] == "eth_getTransactionByHash"
        assert body["params"] == ["0xdeadbeef"]
        return httpx.Response(200, json={
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "hash": "0xdeadbeef",
                "blockNumber": "0x10",
                "from": "0xfrom",
                "to": "0xto",
                "value": "0x100",
            },
        })

    client = make_mock_client(handler)
    provider = EvmRpcProvider(client=client, rpc_url="https://rpc.example")
    res = provider.get_transaction_details("0xdeadbeef", "ethereum")

    assert res.status == ProviderStatus.OK
    assert res.data["hash"] == "0xdeadbeef"


def test_evm_rpc_get_token_metadata_error_handling():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "jsonrpc": "2.0",
            "id": 1,
            "error": {"code": -32601, "message": "The method eth_call does not exist/is not available"},
        })

    client = make_mock_client(handler)
    provider = EvmRpcProvider(client=client, rpc_url="https://rpc.example")
    res = provider.get_token_metadata("0xtoken", "ethereum")

    assert res.status in {ProviderStatus.UNSUPPORTED, ProviderStatus.ERROR}
    assert res.error is not None


def test_evm_rpc_unsupported_methods():
    client = make_mock_client(lambda r: httpx.Response(200, json={}))
    provider = EvmRpcProvider(client=client, rpc_url="https://rpc.example")

    r_tx = provider.get_transactions("0xaddr", "ethereum")
    assert r_tx.status == ProviderStatus.UNSUPPORTED

    r_bal = provider.get_token_balances("0xaddr", "ethereum")
    assert r_bal.status == ProviderStatus.UNSUPPORTED


def test_evm_rpc_network_error_returns_error_result():
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused")

    client = make_mock_client(handler)
    provider = EvmRpcProvider(client=client, rpc_url="https://rpc.example", max_retries=0)
    res = provider.get_native_balance("0xaddr", "ethereum")

    assert res.status == ProviderStatus.ERROR
    assert res.error is not None


def test_evm_rpc_per_network_routing():
    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(str(req.url))
        val = 111 if "eth.llamarpc" in str(req.url) else 222
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": hex(val)})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    p = EvmRpcProvider(
        client=client,
        rpc_url="https://eth.llamarpc.com",
        rpc_urls={
            "ethereum": "https://eth.llamarpc.com",
            "arbitrum": "https://arb1.arbitrum.io/rpc",
        },
    )

    eth = p.get_native_balance("0x1111111111111111111111111111111111111111", "ethereum")
    arb = p.get_native_balance("0x1111111111111111111111111111111111111111", "arbitrum")
    unknown = p.get_native_balance("0x1111111111111111111111111111111111111111", "solana")

    assert eth.data == Decimal(111)
    assert arb.data == Decimal(222)
    assert len(calls) == 2
    assert "eth.llamarpc.com" in calls[0]
    assert "arb1.arbitrum.io" in calls[1]

    assert unknown.status in {ProviderStatus.ERROR, ProviderStatus.UNSUPPORTED}
    assert unknown.data is None
    assert len(calls) == 2  # no HTTP call made for unknown network
