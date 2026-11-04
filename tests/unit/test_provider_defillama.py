"""Unit tests for DeFiLlama data provider using httpx.MockTransport."""
from __future__ import annotations

from decimal import Decimal

import httpx

from app.providers.base import ProviderStatus
from app.providers.defillama import DefiLlamaProvider


def make_mock_client(handler, base_url="https://coins.llama.fi"):
    return httpx.Client(transport=httpx.MockTransport(handler), base_url=base_url)


def test_defillama_get_token_price_success():
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/prices/current/ethereum:0x0000000000000000000000000000000000000000"
        return httpx.Response(200, json={
            "coins": {
                "ethereum:0x0000000000000000000000000000000000000000": {
                    "price": 2432.58,
                    "symbol": "ETH",
                    "decimals": 18,
                    "timestamp": 1793816723,
                }
            }
        })

    client = make_mock_client(handler)
    provider = DefiLlamaProvider(client=client)
    res = provider.get_token_price("ethereum", "0x0000000000000000000000000000000000000000")

    assert res.status == ProviderStatus.OK
    assert isinstance(res.data, Decimal)
    assert res.data == Decimal("2432.58")
    assert res.source == "defillama"


def test_defillama_get_token_price_not_found():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"coins": {}})

    client = make_mock_client(handler)
    provider = DefiLlamaProvider(client=client)
    res = provider.get_token_price("ethereum", "0xunknown")

    assert res.status == ProviderStatus.ERROR
    assert res.error is not None


def test_defillama_health_check():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "coins": {
                "ethereum:0x0000000000000000000000000000000000000000": {"price": 2500}
            }
        })

    client = make_mock_client(handler)
    provider = DefiLlamaProvider(client=client)
    res = provider.health_check("ethereum")

    assert res.status == ProviderStatus.OK
    assert res.data is True


def test_defillama_unsupported_methods():
    client = make_mock_client(lambda r: httpx.Response(200, json={}))
    provider = DefiLlamaProvider(client=client)

    assert provider.get_native_balance("0x1", "ethereum").status == ProviderStatus.UNSUPPORTED
    assert provider.get_transactions("0x1", "ethereum").status == ProviderStatus.UNSUPPORTED
    assert provider.get_latest_block("ethereum").status == ProviderStatus.UNSUPPORTED
