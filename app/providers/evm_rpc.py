"""EVM JSON-RPC data provider adapter."""
from __future__ import annotations

import json
import logging
import time
from decimal import Decimal
from typing import Any

import httpx

from app.providers.base import (
    DataProvider,
    ProviderResult,
    ProviderStatus,
)

logger = logging.getLogger(__name__)


class EvmRpcProvider(DataProvider):
    """Direct EVM JSON-RPC provider for standard node calls."""

    name: str = "evm_rpc"

    def __init__(
        self,
        client: httpx.Client | None = None,
        rpc_url: str | None = None,
        rpc_urls: dict[str, str] | None = None,
        max_retries: int = 2,
        backoff_base: float = 0.5,
    ) -> None:
        super().__init__(client=client, api_key=None)
        self.max_retries = max(0, max_retries)
        self.backoff_base = max(0.0, backoff_base)

        if rpc_urls is not None:
            self.rpc_urls: dict[str, str] = {
                k.strip().lower(): str(v) for k, v in rpc_urls.items()
            }
        else:
            self.rpc_urls = {}

        if rpc_url:
            self.rpc_url = rpc_url
        elif self.rpc_urls:
            self.rpc_url = next(iter(self.rpc_urls.values()))
        else:
            self.rpc_url = "https://eth.llamarpc.com"

        if self.client is None:
            self._managed_client = True
            self.client = httpx.Client(timeout=15.0)
        else:
            self._managed_client = False

    def _resolve_url(self, network: str | None) -> str | None:
        if not network:
            return None
        key = network.strip().lower()
        if key in self.rpc_urls:
            return self.rpc_urls[key]

        aliases = {
            "eth": "ethereum",
            "mainnet": "ethereum",
            "arb": "arbitrum",
            "op": "optimism",
            "bsc": "bnb chain",
            "bnb": "bnb chain",
            "polygon": "polygon",
            "matic": "polygon",
        }
        canonical = aliases.get(key)
        if canonical and canonical in self.rpc_urls:
            return self.rpc_urls[canonical]

        if not self.rpc_urls and self.rpc_url and key in ("ethereum", "mainnet", "eth"):
            return self.rpc_url
        return None

    def _call_rpc(
        self, method: str, params: list[Any], endpoint: str | None = None
    ) -> ProviderResult:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params,
        }

        url = endpoint or self.rpc_url
        if not url:
            return ProviderResult(
                status=ProviderStatus.ERROR,
                error="No RPC endpoint URL available",
                source=self.name,
                data=None,
            )

        last_status_code: int | None = None
        last_error_text: str | None = None

        for attempt in range(self.max_retries + 1):
            try:
                assert self.client is not None
                resp = self.client.post(url, json=payload)

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
                        error=f"EVM RPC server error {resp.status_code}",
                        source=self.name,
                    )

                if 200 <= resp.status_code < 300:
                    try:
                        data = resp.json()
                    except json.JSONDecodeError as e:
                        return ProviderResult(
                            status=ProviderStatus.ERROR,
                            error=f"Invalid JSON-RPC response: {e}",
                            source=self.name,
                        )

                    if "error" in data:
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

                    if "result" not in data:
                        return ProviderResult(
                            status=ProviderStatus.ERROR,
                            error="Missing result in JSON-RPC response",
                            source=self.name,
                        )

                    return ProviderResult(status=ProviderStatus.OK, data=data["result"], source=self.name)

                return ProviderResult(
                    status=ProviderStatus.ERROR,
                    error=f"EVM RPC client error {resp.status_code}",
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

    def get_native_balance(self, address: str, network: str) -> ProviderResult:
        url = self._resolve_url(network)
        if not url:
            return ProviderResult(
                status=ProviderStatus.ERROR,
                error=f"Unsupported or unconfigured network: '{network}'",
                source=self.name,
                data=None,
            )
        res = self._call_rpc("eth_getBalance", [address, "latest"], endpoint=url)
        if res.status != ProviderStatus.OK:
            return res

        try:
            hex_str = str(res.data)
            val_int = int(hex_str, 16)
            return ProviderResult(status=ProviderStatus.OK, data=Decimal(str(val_int)), source=self.name)
        except (ValueError, TypeError) as e:
            return ProviderResult(
                status=ProviderStatus.ERROR,
                error=f"Failed to parse balance hex: {e}",
                source=self.name,
            )

    def get_latest_block(self, network: str) -> ProviderResult:
        url = self._resolve_url(network)
        if not url:
            return ProviderResult(
                status=ProviderStatus.ERROR,
                error=f"Unsupported or unconfigured network: '{network}'",
                source=self.name,
                data=None,
            )
        res = self._call_rpc("eth_blockNumber", [], endpoint=url)
        if res.status != ProviderStatus.OK:
            return res

        try:
            hex_str = str(res.data)
            block_int = int(hex_str, 16)
            return ProviderResult(status=ProviderStatus.OK, data=block_int, source=self.name)
        except (ValueError, TypeError) as e:
            return ProviderResult(
                status=ProviderStatus.ERROR,
                error=f"Failed to parse blockNumber hex: {e}",
                source=self.name,
            )

    def get_transaction_details(self, tx_hash: str, network: str) -> ProviderResult:
        url = self._resolve_url(network)
        if not url:
            return ProviderResult(
                status=ProviderStatus.ERROR,
                error=f"Unsupported or unconfigured network: '{network}'",
                source=self.name,
                data=None,
            )
        return self._call_rpc("eth_getTransactionByHash", [tx_hash], endpoint=url)

    def get_token_metadata(self, contract: str, network: str) -> ProviderResult:
        url = self._resolve_url(network)
        if not url:
            return ProviderResult(
                status=ProviderStatus.ERROR,
                error=f"Unsupported or unconfigured network: '{network}'",
                source=self.name,
                data=None,
            )
        # eth_call for decimals() selector: 0x313ce567
        res_dec = self._call_rpc(
            "eth_call", [{"to": contract, "data": "0x313ce567"}, "latest"], endpoint=url
        )
        if res_dec.status != ProviderStatus.OK:
            return ProviderResult(
                status=ProviderStatus.UNSUPPORTED,
                error=f"eth_call unsupported or failed: {res_dec.error}",
                source=self.name,
            )

        # eth_call for symbol() selector: 0x95d89b41
        res_sym = self._call_rpc(
            "eth_call", [{"to": contract, "data": "0x95d89b41"}, "latest"], endpoint=url
        )

        decimals: int | None = None
        if isinstance(res_dec.data, str):
            try:
                decimals = int(res_dec.data, 16)
            except ValueError as exc:
                logger.warning("Failed to parse token decimals '%s': %s", res_dec.data, exc)

        return ProviderResult(
            status=ProviderStatus.OK,
            data={"contract": contract, "decimals": decimals, "symbol_raw": res_sym.data},
            source=self.name,
        )

    def health_check(self, network: str) -> ProviderResult:
        block_res = self.get_latest_block(network)
        if block_res.status == ProviderStatus.OK:
            return ProviderResult(
                status=ProviderStatus.OK,
                data=block_res.data,
                source=self.name,
            )
        return ProviderResult(
            status=block_res.status,
            error=block_res.error,
            source=self.name,
        )

    def get_transactions(self, address: str, network: str, cursor: Any = None) -> ProviderResult:
        return ProviderResult(
            status=ProviderStatus.UNSUPPORTED,
            error="EVM JSON-RPC does not support indexed transactions",
            source=self.name,
        )

    def get_token_balances(self, address: str, network: str) -> ProviderResult:
        return ProviderResult(
            status=ProviderStatus.UNSUPPORTED,
            error="EVM JSON-RPC does not support token balances enumeration",
            source=self.name,
        )
