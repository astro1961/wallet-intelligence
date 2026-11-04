"""Unit tests for DataProvider base interfaces and types."""
from __future__ import annotations

from app.providers.base import DataProvider, ProviderResult, ProviderStatus


def test_provider_status_enum_values():
    assert ProviderStatus.OK == "OK"
    assert ProviderStatus.UNSUPPORTED == "UNSUPPORTED"
    assert ProviderStatus.ERROR == "ERROR"
    assert ProviderStatus.RATE_LIMITED == "RATE_LIMITED"


def test_provider_result_dataclass():
    res = ProviderResult(status=ProviderStatus.OK, data=123, error=None, source="test")
    assert res.status == ProviderStatus.OK
    assert res.data == 123
    assert res.error is None
    assert res.source == "test"


def test_base_provider_default_methods_return_unsupported():
    class TestProvider(DataProvider):
        name = "test_subclass"

    p = TestProvider()
    assert p.name == "test_subclass"

    methods = [
        ("get_native_balance", ("0x123", "ethereum")),
        ("get_token_balances", ("0x123", "ethereum")),
        ("get_transactions", ("0x123", "ethereum")),
        ("get_transaction_details", ("0xhash", "ethereum")),
        ("get_token_metadata", ("0xtoken", "ethereum")),
        ("get_latest_block", ("ethereum",)),
        ("health_check", ("ethereum",)),
    ]

    for method_name, args in methods:
        method = getattr(p, method_name)
        result: ProviderResult = method(*args)
        assert isinstance(result, ProviderResult), f"{method_name} must return ProviderResult"
        assert result.status == ProviderStatus.UNSUPPORTED, f"{method_name} status was {result.status}"
        assert result.error, f"{method_name} must carry an error reason"
        assert result.data is None
