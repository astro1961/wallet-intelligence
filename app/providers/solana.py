"""Solana JSON-RPC data provider adapter (Stage 9C)."""
from __future__ import annotations

import json
import logging
from decimal import Decimal, InvalidOperation
from typing import Any, Self

import httpx

from app.providers.base import (
    DataProvider,
    ProviderResult,
    ProviderStatus,
)
from app.utils.validators import is_valid_solana_address

logger = logging.getLogger(__name__)


class SolanaProvider(DataProvider):
    """Direct Solana JSON-RPC provider for standard node calls."""

    name: str = "solana"

    def __init__(self, rpc_url: str, client: httpx.Client | None = None) -> None:
        super().__init__(client=client, api_key=None)
        self.rpc_url = rpc_url
        if self.client is None:
            self._managed_client = True
            self.client = httpx.Client(timeout=15)
        else:
            self._managed_client = False

    def close(self) -> None:
        """Close managed HTTP client session."""
        if self._managed_client and self.client:
            self.client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _call_rpc(self, method: str, params: list[Any] | None = None) -> ProviderResult:
        """Execute a JSON-RPC request to the Solana node."""
        payload: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params if params is not None else [],
        }

        try:
            assert self.client is not None
            resp = self.client.post(self.rpc_url, json=payload)
        except httpx.TransportError as exc:
            return ProviderResult(
                status=ProviderStatus.ERROR,
                error=f"Transport error: {exc}",
                source=self.name,
            )
        except httpx.HTTPError as exc:
            return ProviderResult(
                status=ProviderStatus.ERROR,
                error=f"HTTP error: {exc}",
                source=self.name,
            )

        if resp.status_code == 429:
            return ProviderResult(
                status=ProviderStatus.RATE_LIMITED,
                error="Rate limit exceeded",
                source=self.name,
            )

        if resp.status_code < 200 or resp.status_code >= 300:
            return ProviderResult(
                status=ProviderStatus.ERROR,
                error=f"HTTP {resp.status_code}: {resp.text}",
                source=self.name,
            )

        try:
            data = resp.json()
        except (json.JSONDecodeError, ValueError) as exc:
            return ProviderResult(
                status=ProviderStatus.ERROR,
                error=f"Invalid JSON-RPC response: {exc}",
                source=self.name,
            )

        if isinstance(data, dict) and "error" in data:
            err_obj = data["error"]
            err_msg = (
                err_obj.get("message", str(err_obj))
                if isinstance(err_obj, dict)
                else str(err_obj)
            )
            return ProviderResult(
                status=ProviderStatus.ERROR,
                error=f"JSON-RPC error: {err_msg}",
                source=self.name,
            )

        if not isinstance(data, dict) or "result" not in data:
            return ProviderResult(
                status=ProviderStatus.ERROR,
                error="Missing result in JSON-RPC response",
                source=self.name,
            )

        return ProviderResult(
            status=ProviderStatus.OK,
            data=data["result"],
            source=self.name,
        )

    def get_native_balance(self, address: str, network: str = "solana") -> ProviderResult:
        """Fetch native SOL balance in raw lamports as a Decimal."""
        if not is_valid_solana_address(address):
            return ProviderResult(
                status=ProviderStatus.ERROR,
                data=None,
                error=f"Invalid Solana address: {address}",
                source=self.name,
            )

        res = self._call_rpc("getBalance", [address])
        if res.status != ProviderStatus.OK:
            return ProviderResult(
                status=res.status,
                data=None,
                error=res.error,
                source=self.name,
            )

        result = res.data
        if isinstance(result, dict) and "value" in result:
            val = result["value"]
        else:
            val = result

        if val is None or isinstance(val, bool):
            return ProviderResult(
                status=ProviderStatus.ERROR,
                data=None,
                error="Missing or invalid balance value in JSON-RPC response",
                source=self.name,
            )

        try:
            lamports = Decimal(str(val))
        except (InvalidOperation, TypeError, ValueError) as exc:
            return ProviderResult(
                status=ProviderStatus.ERROR,
                data=None,
                error=f"Cannot parse lamports balance: {exc}",
                source=self.name,
            )

        return ProviderResult(
            status=ProviderStatus.OK,
            data=lamports,
            source=self.name,
        )

    def get_latest_block(self, network: str = "solana") -> ProviderResult:
        """Fetch current slot number as an int."""
        res = self._call_rpc("getSlot")
        if res.status != ProviderStatus.OK:
            return res

        result = res.data
        if isinstance(result, dict) and "value" in result:
            val = result["value"]
        else:
            val = result

        if val is None or isinstance(val, bool):
            return ProviderResult(
                status=ProviderStatus.ERROR,
                error="Missing slot in JSON-RPC response",
                source=self.name,
            )

        try:
            slot = int(val)
        except (ValueError, TypeError) as exc:
            return ProviderResult(
                status=ProviderStatus.ERROR,
                error=f"Cannot parse slot as int: {exc}",
                source=self.name,
            )

        return ProviderResult(
            status=ProviderStatus.OK,
            data=slot,
            source=self.name,
        )

    def health_check(self, network: str = "solana") -> ProviderResult:
        """Check Solana node health via getHealth. Result == 'ok' -> OK else ERROR."""
        res = self._call_rpc("getHealth")
        if res.status == ProviderStatus.OK and res.data == "ok":
            return ProviderResult(
                status=ProviderStatus.OK,
                data="ok",
                source=self.name,
            )
        return ProviderResult(
            status=ProviderStatus.ERROR,
            error=res.error or f"Health check returned: {res.data}",
            source=self.name,
        )

    def get_transactions(
        self, address: str, network: str = "solana", cursor: Any = None
    ) -> ProviderResult:
        """Unsupported method on raw Solana JSON-RPC."""
        return ProviderResult(
            status=ProviderStatus.UNSUPPORTED,
            error="Solana JSON-RPC does not support indexed transactions",
            source=self.name,
        )

    def get_token_balances(self, address: str, network: str = "solana") -> ProviderResult:
        """Unsupported method on raw Solana JSON-RPC."""
        return ProviderResult(
            status=ProviderStatus.UNSUPPORTED,
            error="Solana JSON-RPC does not support token balances enumeration",
            source=self.name,
        )

    def get_transaction_details(self, tx_hash: str, network: str = "solana") -> ProviderResult:
        """Unsupported method on raw Solana JSON-RPC."""
        return ProviderResult(
            status=ProviderStatus.UNSUPPORTED,
            error="Solana JSON-RPC does not support transaction details",
            source=self.name,
        )

    def get_token_metadata(self, contract: str, network: str = "solana") -> ProviderResult:
        """Unsupported method on raw Solana JSON-RPC."""
        return ProviderResult(
            status=ProviderStatus.UNSUPPORTED,
            error="Solana JSON-RPC does not support token metadata",
            source=self.name,
        )
