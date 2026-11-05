"""RPC failover provider with ordered endpoint fallback."""
from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from decimal import Decimal
from typing import Any

import httpx

from app.providers.base import (
    DataProvider,
    ProviderResult,
    ProviderStatus,
)

logger = logging.getLogger(__name__)


def _parse_balance(val: Any) -> Decimal:
    """Parse eth_getBalance result into Decimal wei."""
    if isinstance(val, bool):
        raise TypeError("Boolean is not a valid balance")
    if isinstance(val, int):
        return Decimal(str(val))
    if isinstance(val, str):
        val_str = val.strip()
        if not val_str:
            raise ValueError("Empty balance hex string")
        return Decimal(str(int(val_str, 16)))
    raise TypeError(f"Cannot parse balance from {type(val).__name__}")


def _parse_block_number(val: Any) -> int:
    """Parse eth_blockNumber result into integer block number."""
    if isinstance(val, bool):
        raise TypeError("Boolean is not a valid block number")
    if isinstance(val, int):
        return val
    if isinstance(val, str):
        val_str = val.strip()
        if not val_str:
            raise ValueError("Empty block hex string")
        return int(val_str, 16)
    raise TypeError(f"Cannot parse block number from {type(val).__name__}")


class RpcFailoverProvider(DataProvider):
    """Data provider executing failover across ordered RPC endpoints."""

    name: str = "rpc_failover"

    def __init__(
        self,
        endpoints: list[str],
        client: httpx.Client | None = None,
        max_retries: int = 0,
        backoff_base: float = 0.0,
    ) -> None:
        super().__init__(client=client, api_key=None)
        self.endpoints: list[str] = list(endpoints)
        self.max_retries: int = max(0, max_retries)
        self.backoff_base: float = max(0.0, backoff_base)
        self._healthy: dict[str, bool] = {ep: True for ep in self.endpoints}

        if self.client is None:
            self.client = httpx.Client(timeout=15.0)

    @property
    def healthy(self) -> dict[str, bool]:
        """Observability health flags for configured endpoints."""
        return dict(self._healthy)

    def _execute_failover(
        self,
        method: str,
        params: list[Any],
        parser: Callable[[Any], Any],
    ) -> ProviderResult:
        if not self.endpoints:
            return ProviderResult(
                status=ProviderStatus.ERROR,
                data=None,
                error="No RPC endpoints configured",
                source=self.name,
            )

        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params,
        }

        last_error = "Unknown error"

        for endpoint in self.endpoints:
            endpoint_failed = False
            endpoint_error: str | None = None

            for attempt in range(self.max_retries + 1):
                try:
                    assert self.client is not None
                    resp = self.client.post(endpoint, json=payload)

                    if resp.status_code == 429:
                        err_msg = "Rate limit exceeded"
                        try:
                            body = resp.json()
                            if (
                                isinstance(body, dict)
                                and "error" in body
                                and body["error"] is not None
                            ):
                                err_obj = body["error"]
                                err_msg = (
                                    err_obj.get("message", str(err_obj))
                                    if isinstance(err_obj, dict)
                                    else str(err_obj)
                                )
                        except (ValueError, KeyError):
                            if resp.text.strip():
                                err_msg = resp.text.strip()
                        endpoint_error = err_msg
                        endpoint_failed = True
                        if attempt < self.max_retries:
                            if self.backoff_base > 0:
                                time.sleep(self.backoff_base * (2**attempt))
                            continue
                        break

                    if 500 <= resp.status_code < 600:
                        err_msg = f"HTTP {resp.status_code}"
                        try:
                            body = resp.json()
                            if (
                                isinstance(body, dict)
                                and "error" in body
                                and body["error"] is not None
                            ):
                                err_obj = body["error"]
                                err_msg = (
                                    err_obj.get("message", str(err_obj))
                                    if isinstance(err_obj, dict)
                                    else str(err_obj)
                                )
                        except (ValueError, KeyError):
                            if resp.text.strip():
                                err_msg = resp.text.strip()
                        endpoint_error = err_msg
                        endpoint_failed = True
                        if attempt < self.max_retries:
                            if self.backoff_base > 0:
                                time.sleep(self.backoff_base * (2**attempt))
                            continue
                        break

                    if resp.status_code == 200:
                        try:
                            data = resp.json()
                        except (ValueError, json.JSONDecodeError) as exc:
                            endpoint_error = f"Invalid JSON response: {exc}"
                            endpoint_failed = True
                            break

                        if not isinstance(data, dict):
                            endpoint_error = f"Malformed JSON-RPC response: {data!r}"
                            endpoint_failed = True
                            break

                        if "error" in data and data["error"] is not None:
                            err_obj = data["error"]
                            err_msg = (
                                err_obj.get("message", str(err_obj))
                                if isinstance(err_obj, dict)
                                else str(err_obj)
                            )
                            endpoint_error = err_msg
                            endpoint_failed = True
                            break

                        if "result" not in data or data["result"] is None:
                            endpoint_error = "Missing result in JSON-RPC response"
                            endpoint_failed = True
                            break

                        try:
                            parsed_val = parser(data["result"])
                        except (ValueError, TypeError) as exc:
                            endpoint_error = f"Failed to parse result hex: {exc}"
                            endpoint_failed = True
                            break

                        self._healthy[endpoint] = True
                        return ProviderResult(
                            status=ProviderStatus.OK,
                            data=parsed_val,
                            source=endpoint,
                        )

                    # Non-200, non-5xx, non-429
                    err_msg = f"HTTP {resp.status_code}"
                    if resp.text.strip():
                        err_msg = f"{err_msg}: {resp.text.strip()}"
                    endpoint_error = err_msg
                    endpoint_failed = True
                    break

                except httpx.TransportError as exc:
                    endpoint_error = str(exc) or exc.__class__.__name__
                    endpoint_failed = True
                    if attempt < self.max_retries:
                        if self.backoff_base > 0:
                            time.sleep(self.backoff_base * (2**attempt))
                        continue
                    break
                except Exception as exc:  # noqa: BLE001
                    endpoint_error = str(exc) or exc.__class__.__name__
                    endpoint_failed = True
                    break

            if endpoint_failed:
                self._healthy[endpoint] = False
                last_error = endpoint_error or "Unknown endpoint failure"

        return ProviderResult(
            status=ProviderStatus.ERROR,
            data=None,
            error=last_error,
            source=self.name,
        )

    def get_native_balance(self, address: str, network: str = "ethereum") -> ProviderResult:
        """Fetch native currency balance (wei Decimal) with ordered endpoint failover."""
        return self._execute_failover("eth_getBalance", [address, "latest"], _parse_balance)

    def get_latest_block(self, network: str = "ethereum") -> ProviderResult:
        """Fetch latest block number (int) with ordered endpoint failover."""
        return self._execute_failover("eth_blockNumber", [], _parse_block_number)

    def health_check(self, network: str = "ethereum") -> ProviderResult:
        """Check provider reachability using latest block query."""
        return self.get_latest_block(network)

    def get_transactions(
        self, address: str, network: str = "ethereum", cursor: Any = None
    ) -> ProviderResult:
        """Unsupported method."""
        return self._unsupported("get_transactions")

    def get_token_balances(
        self, address: str, network: str = "ethereum"
    ) -> ProviderResult:
        """Unsupported method."""
        return self._unsupported("get_token_balances")

    def get_transaction_details(
        self, tx_hash: str, network: str = "ethereum"
    ) -> ProviderResult:
        """Unsupported method."""
        return self._unsupported("get_transaction_details")

    def get_token_metadata(
        self, contract: str, network: str = "ethereum"
    ) -> ProviderResult:
        """Unsupported method."""
        return self._unsupported("get_token_metadata")
