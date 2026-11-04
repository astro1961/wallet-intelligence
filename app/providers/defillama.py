"""DeFiLlama token price and protocol data provider adapter."""
from __future__ import annotations

import json
import logging
import time
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from app.providers.base import (
    DataProvider,
    ProviderResult,
    ProviderStatus,
)

logger = logging.getLogger(__name__)


class DefiLlamaProvider(DataProvider):
    """DeFiLlama coins and pricing API adapter."""

    name: str = "defillama"

    def __init__(
        self,
        client: httpx.Client | None = None,
        base_url: str = "https://coins.llama.fi",
        max_retries: int = 2,
        backoff_base: float = 0.5,
    ) -> None:
        super().__init__(client=client, api_key=None)
        self.base_url = base_url.rstrip("/")
        self.max_retries = max(0, max_retries)
        self.backoff_base = max(0.0, backoff_base)

        if self.client is None:
            self._managed_client = True
            self.client = httpx.Client(base_url=self.base_url, timeout=10.0)
        else:
            self._managed_client = False

    def _request(self, path: str, params: dict[str, Any] | None = None) -> ProviderResult:
        last_status_code: int | None = None
        last_error_text: str | None = None

        for attempt in range(self.max_retries + 1):
            try:
                assert self.client is not None
                resp = self.client.get(path, params=params)
                last_status_code = resp.status_code

                if resp.status_code == 429:
                    last_error_text = "Rate limit exceeded"
                    if attempt < self.max_retries:
                        time.sleep(self.backoff_base * (2**attempt))
                        continue
                    return ProviderResult(
                        status=ProviderStatus.RATE_LIMITED,
                        error="Rate limit exceeded",
                        source=self.name,
                    )

                if 500 <= resp.status_code < 600:
                    last_error_text = f"HTTP {resp.status_code}"
                    if attempt < self.max_retries:
                        time.sleep(self.backoff_base * (2**attempt))
                        continue
                    return ProviderResult(
                        status=ProviderStatus.ERROR,
                        error=f"DeFiLlama server error {resp.status_code}",
                        source=self.name,
                    )

                if 200 <= resp.status_code < 300:
                    try:
                        return ProviderResult(status=ProviderStatus.OK, data=resp.json(), source=self.name)
                    except json.JSONDecodeError as e:
                        return ProviderResult(
                            status=ProviderStatus.ERROR,
                            error=f"Failed to parse JSON response: {e}",
                            source=self.name,
                        )

                return ProviderResult(
                    status=ProviderStatus.ERROR,
                    error=f"DeFiLlama client error {resp.status_code}",
                    source=self.name,
                )

            except httpx.TransportError as exc:
                last_error_text = str(exc)
                if attempt < self.max_retries:
                    time.sleep(self.backoff_base * (2**attempt))
                    continue
                return ProviderResult(
                    status=ProviderStatus.ERROR,
                    error=f"Transport error: {exc}",
                    source=self.name,
                )
            except Exception as exc:  # noqa: BLE001
                return ProviderResult(
                    status=ProviderStatus.ERROR,
                    error=f"Unexpected error: {exc}",
                    source=self.name,
                )

        if last_status_code == 429:
            return ProviderResult(
                status=ProviderStatus.RATE_LIMITED,
                error="Rate limit exceeded",
                source=self.name,
            )
        return ProviderResult(
            status=ProviderStatus.ERROR,
            error=last_error_text or "Max retries exceeded",
            source=self.name,
        )

    def get_token_price(self, chain: str, token: str) -> ProviderResult:
        key = f"{chain.strip().lower()}:{token.strip().lower()}"
        path = f"/prices/current/{key}"
        res = self._request(path)
        if res.status != ProviderStatus.OK:
            return res

        data = res.data if isinstance(res.data, dict) else {}
        coins = data.get("coins", {})

        # Try key, or case-insensitive match
        matched_coin = coins.get(key)
        if not matched_coin:
            for k, v in coins.items():
                if k.lower() == key:
                    matched_coin = v
                    break

        if not matched_coin or "price" not in matched_coin:
            return ProviderResult(
                status=ProviderStatus.ERROR,
                error=f"Price not found for token {key}",
                source=self.name,
            )

        try:
            price_dec = Decimal(str(matched_coin["price"]))
            return ProviderResult(status=ProviderStatus.OK, data=price_dec, source=self.name)
        except (InvalidOperation, ValueError, TypeError) as e:
            return ProviderResult(
                status=ProviderStatus.ERROR,
                error=f"Invalid price value format: {e}",
                source=self.name,
            )

    def health_check(self, network: str = "ethereum") -> ProviderResult:
        # Check canonical zero address on ethereum
        path = f"/prices/current/{network.strip().lower()}:0x0000000000000000000000000000000000000000"
        res = self._request(path)
        if res.status == ProviderStatus.OK:
            return ProviderResult(status=ProviderStatus.OK, data=True, source=self.name)
        return ProviderResult(
            status=res.status,
            error=res.error or "DeFiLlama health check failed",
            source=self.name,
        )
