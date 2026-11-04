"""Provider registry and failover coordinator."""
from __future__ import annotations

import logging
from typing import Any

from app.providers.base import (
    DataProvider,
    ProviderResult,
    ProviderStatus,
)

logger = logging.getLogger(__name__)


class ProviderRegistry:
    """Manages an ordered chain of data providers with automatic failover."""

    def __init__(self, providers: list[DataProvider] | None = None) -> None:
        self.providers: list[DataProvider] = list(providers or [])

    def add_provider(self, provider: DataProvider) -> None:
        self.providers.append(provider)

    def get_provider(self, name: str) -> DataProvider | None:
        for p in self.providers:
            if p.name.lower() == name.lower():
                return p
        return None

    def _execute_with_failover(self, method_name: str, *args: Any, **kwargs: Any) -> ProviderResult:
        if not self.providers:
            return ProviderResult(
                status=ProviderStatus.ERROR,
                error=f"No providers registered to execute '{method_name}'",
                source="registry",
            )

        last_res: ProviderResult | None = None
        for p in self.providers:
            method = getattr(p, method_name, None)
            if not callable(method):
                continue

            try:
                res: ProviderResult = method(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001
                res = ProviderResult(
                    status=ProviderStatus.ERROR,
                    error=f"Provider {p.name} unhandled exception in {method_name}: {exc}",
                    source=p.name,
                )

            if res.status == ProviderStatus.OK:
                return res

            last_res = res
            logger.debug(
                "Provider '%s' returned status %s for '%s': %s. Trying next provider.",
                p.name,
                res.status.name,
                method_name,
                res.error,
            )

        return last_res or ProviderResult(
            status=ProviderStatus.ERROR,
            error=f"All providers failed or unsupported for '{method_name}'",
            source="registry",
        )

    def get_native_balance(self, address: str, network: str) -> ProviderResult:
        return self._execute_with_failover("get_native_balance", address, network)

    def get_token_balances(self, address: str, network: str) -> ProviderResult:
        return self._execute_with_failover("get_token_balances", address, network)

    def get_transactions(self, address: str, network: str, cursor: Any = None) -> ProviderResult:
        return self._execute_with_failover("get_transactions", address, network, cursor=cursor)

    def get_transaction_details(self, tx_hash: str, network: str) -> ProviderResult:
        return self._execute_with_failover("get_transaction_details", tx_hash, network)

    def get_token_metadata(self, contract: str, network: str) -> ProviderResult:
        return self._execute_with_failover("get_token_metadata", contract, network)

    def get_latest_block(self, network: str) -> ProviderResult:
        return self._execute_with_failover("get_latest_block", network)

    def health_check_all(self, network: str) -> dict[str, ProviderResult]:
        results: dict[str, ProviderResult] = {}
        for p in self.providers:
            try:
                results[p.name] = p.health_check(network)
            except Exception as exc:  # noqa: BLE001
                results[p.name] = ProviderResult(
                    status=ProviderStatus.ERROR,
                    error=f"Health check failed: {exc}",
                    source=p.name,
                )
        return results


def build_default_registry(cfg: Any = None) -> ProviderRegistry:
    from app.providers.factory import create_provider_registry

    return create_provider_registry(cfg)
