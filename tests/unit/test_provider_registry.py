"""Unit tests for ProviderRegistry and failover logic."""
from __future__ import annotations

from decimal import Decimal

from app.providers.base import DataProvider, ProviderResult, ProviderStatus
from app.providers.registry import ProviderRegistry


class MockProvider(DataProvider):
    def __init__(self, name: str, status: ProviderStatus, data=None, error=None) -> None:
        super().__init__()
        self.name = name
        self.status = status
        self.data = data
        self.error = error
        self.calls = 0

    def get_native_balance(self, address: str, network: str) -> ProviderResult:
        self.calls += 1
        return ProviderResult(status=self.status, data=self.data, error=self.error, source=self.name)

    def health_check(self, network: str) -> ProviderResult:
        return ProviderResult(status=self.status, data=self.data, error=self.error, source=self.name)


def test_registry_failover_from_error_to_ok():
    p1 = MockProvider("p1", ProviderStatus.ERROR, error="connection timeout")
    p2 = MockProvider("p2", ProviderStatus.OK, data=Decimal(100))

    reg = ProviderRegistry([p1, p2])
    res = reg.get_native_balance("0xaddr", "ethereum")

    assert res.status == ProviderStatus.OK
    assert res.data == Decimal(100)
    assert res.source == "p2"
    assert p1.calls == 1
    assert p2.calls == 1


def test_registry_failover_from_rate_limited():
    p1 = MockProvider("p1", ProviderStatus.RATE_LIMITED, error="rate limit exceeded")
    p2 = MockProvider("p2", ProviderStatus.OK, data=Decimal(50))

    reg = ProviderRegistry([p1, p2])
    res = reg.get_native_balance("0xaddr", "ethereum")

    assert res.status == ProviderStatus.OK
    assert res.data == Decimal(50)
    assert res.source == "p2"


def test_registry_failover_from_unsupported():
    p1 = MockProvider("p1", ProviderStatus.UNSUPPORTED, error="unsupported method")
    p2 = MockProvider("p2", ProviderStatus.OK, data=Decimal(25))

    reg = ProviderRegistry([p1, p2])
    res = reg.get_native_balance("0xaddr", "ethereum")

    assert res.status == ProviderStatus.OK
    assert res.data == Decimal(25)
    assert res.source == "p2"


def test_registry_all_fail():
    p1 = MockProvider("p1", ProviderStatus.ERROR, error="err1")
    p2 = MockProvider("p2", ProviderStatus.ERROR, error="err2")

    reg = ProviderRegistry([p1, p2])
    res = reg.get_native_balance("0xaddr", "ethereum")

    assert res.status != ProviderStatus.OK
    assert res.error == "err2"


def test_registry_empty():
    reg = ProviderRegistry([])
    res = reg.get_native_balance("0xaddr", "ethereum")
    assert res.status == ProviderStatus.ERROR


def test_registry_health_check_all():
    p1 = MockProvider("p1", ProviderStatus.OK, data=True)
    p2 = MockProvider("p2", ProviderStatus.ERROR, error="node unreachable")

    reg = ProviderRegistry([p1, p2])
    checks = reg.health_check_all("ethereum")

    assert "p1" in checks
    assert "p2" in checks
    assert checks["p1"].status == ProviderStatus.OK
    assert checks["p2"].status == ProviderStatus.ERROR
