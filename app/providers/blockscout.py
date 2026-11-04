"""Blockscout Pro EVM explorer API adapter."""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from app.providers.base import (
    DataProvider,
    ProviderResult,
    ProviderStatus,
    TransactionItem,
    TransactionListResult,
)

logger = logging.getLogger(__name__)


class _KeyFilter(logging.Filter):
    """Logging filter ensuring API keys never leak into log records."""

    def __init__(self, key: str | None) -> None:
        super().__init__()
        self.key = key

    def filter(self, record: logging.LogRecord) -> bool:
        if self.key:
            if isinstance(record.msg, str) and self.key in record.msg:
                record.msg = record.msg.replace(self.key, "***")
            if record.args:
                record.args = tuple(
                    str(a).replace(self.key, "***") if self.key in str(a) else a
                    for a in record.args
                )
        return True


CHAIN_ID_MAP: dict[str, int] = {
    "ethereum": 1,
    "mainnet": 1,
    "eth": 1,
    "arbitrum": 42161,
    "optimism": 10,
    "base": 8453,
    "bnb": 56,
    "bsc": 56,
    "polygon": 137,
    "sepolia": 11155111,
}


class BlockscoutProvider(DataProvider):
    """Blockscout Pro REST API provider for EVM chains."""

    name: str = "blockscout"

    def __init__(
        self,
        client: httpx.Client | None = None,
        api_key: str | None = None,
        chain_id: int = 1,
        base_url: str = "https://api.blockscout.com",
        max_retries: int = 2,
        backoff_base: float = 0.5,
        rps: float = 5.0,
    ) -> None:
        super().__init__(client=client, api_key=api_key)
        self.chain_id = chain_id
        self.base_url = base_url.rstrip("/")
        self.max_retries = max(0, max_retries)
        self.backoff_base = max(0.0, backoff_base)
        self.rps = rps
        self._last_request_time: float = 0.0

        if self.api_key:
            key_filter = _KeyFilter(self.api_key)
            logging.getLogger("httpx").addFilter(key_filter)
            logging.getLogger().addFilter(key_filter)

        if self.client is None:
            self._managed_client = True
            self.client = httpx.Client(base_url=self.base_url, timeout=10.0)
        else:
            self._managed_client = False

    def _resolve_chain_id(self, network: str | None) -> int:
        if network:
            key = network.strip().lower()
            if key in CHAIN_ID_MAP:
                return CHAIN_ID_MAP[key]
            try:
                return int(key)
            except ValueError:
                pass
        return self.chain_id

    def _sanitize(self, message: str) -> str:
        if not self.api_key:
            return message
        sanitized = message.replace(self.api_key, "***")
        sanitized = re.sub(r"apikey=[^&\s'\"]+", "apikey=***", sanitized)
        return sanitized

    def _throttle(self) -> None:
        if self.rps > 0:
            now = time.monotonic()
            min_interval = 1.0 / self.rps
            elapsed = now - self._last_request_time
            if elapsed < min_interval:
                time.sleep(min_interval - elapsed)
            self._last_request_time = time.monotonic()

    def _request(self, path: str, params: dict[str, Any] | None = None) -> ProviderResult:
        query_params = dict(params or {})
        if self.api_key:
            query_params["apikey"] = self.api_key

        last_status_code: int | None = None
        last_error_text: str | None = None

        for attempt in range(self.max_retries + 1):
            self._throttle()
            try:
                assert self.client is not None
                resp = self.client.get(path, params=query_params)
                last_status_code = resp.status_code

                if resp.status_code == 429:
                    last_error_text = "Rate limit exceeded"
                    if attempt < self.max_retries:
                        time.sleep(self.backoff_base * (2**attempt))
                        continue
                    logger.warning("Blockscout rate limited: 429")
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
                    logger.warning("Blockscout server error: %d", resp.status_code)
                    return ProviderResult(
                        status=ProviderStatus.ERROR,
                        error=self._sanitize(f"Blockscout server error {resp.status_code}"),
                        source=self.name,
                    )

                if 200 <= resp.status_code < 300:
                    try:
                        data = resp.json()
                        return ProviderResult(status=ProviderStatus.OK, data=data, source=self.name)
                    except json.JSONDecodeError as e:
                        return ProviderResult(
                            status=ProviderStatus.ERROR,
                            error=self._sanitize(f"Failed to parse JSON response: {e}"),
                            source=self.name,
                        )

                # Client error (4xx other than 429)
                return ProviderResult(
                    status=ProviderStatus.ERROR,
                    error=self._sanitize(f"Blockscout client error {resp.status_code}"),
                    source=self.name,
                )

            except httpx.TransportError as exc:
                last_error_text = str(exc)
                if attempt < self.max_retries:
                    time.sleep(self.backoff_base * (2**attempt))
                    continue
                logger.warning("Blockscout transport error: %s", self._sanitize(str(exc)))
                return ProviderResult(
                    status=ProviderStatus.ERROR,
                    error=self._sanitize(f"Transport error: {exc}"),
                    source=self.name,
                )
            except Exception as exc:  # noqa: BLE001
                return ProviderResult(
                    status=ProviderStatus.ERROR,
                    error=self._sanitize(f"Unexpected error: {exc}"),
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
            error=self._sanitize(last_error_text or "Max retries exceeded"),
            source=self.name,
        )

    def get_native_balance(self, address: str, network: str) -> ProviderResult:
        chain_id = self._resolve_chain_id(network)
        path = f"/{chain_id}/api/v2/addresses/{address}"
        res = self._request(path)
        if res.status != ProviderStatus.OK:
            return res

        raw_balance = res.data.get("coin_balance") if isinstance(res.data, dict) else None
        if raw_balance is None:
            raw_balance = "0"

        try:
            balance_dec = Decimal(str(raw_balance))
        except (InvalidOperation, ValueError) as e:
            return ProviderResult(
                status=ProviderStatus.ERROR,
                error=f"Invalid coin_balance format: {e}",
                source=self.name,
            )

        return ProviderResult(status=ProviderStatus.OK, data=balance_dec, source=self.name)

    def get_transactions(self, address: str, network: str, cursor: Any = None) -> ProviderResult:
        chain_id = self._resolve_chain_id(network)
        path = f"/{chain_id}/api/v2/addresses/{address}/transactions"

        params: dict[str, Any] = {}
        if isinstance(cursor, dict):
            params.update(cursor)

        res = self._request(path, params=params)
        if res.status != ProviderStatus.OK:
            return res

        data = res.data if isinstance(res.data, dict) else {}
        raw_items = data.get("items", [])
        next_cursor = data.get("next_page_params")

        parsed_items: list[TransactionItem] = []
        for raw in raw_items:
            if not isinstance(raw, dict):
                continue

            tx_hash = str(raw.get("hash", ""))

            from_val = raw.get("from")
            if isinstance(from_val, dict):
                from_addr = str(from_val.get("hash", ""))
            else:
                from_addr = str(from_val or raw.get("from_address") or "")

            to_val = raw.get("to")
            if isinstance(to_val, dict):
                to_addr: str | None = to_val.get("hash")
            else:
                to_addr = to_val or raw.get("to_address")
            if to_addr is not None:
                to_addr = str(to_addr)

            raw_val = raw.get("value", "0")
            try:
                val_dec = Decimal(str(raw_val))
            except (InvalidOperation, ValueError, TypeError):
                val_dec = Decimal(0)

            block_num = raw.get("block_number")
            try:
                block_int = int(block_num) if block_num is not None else None
            except (ValueError, TypeError):
                block_int = None

            ts_raw = raw.get("timestamp")
            ts_dt: datetime | None = None
            if ts_raw:
                try:
                    ts_dt = datetime.fromisoformat(str(ts_raw))
                except (ValueError, TypeError):
                    ts_dt = None

            status_str = str(raw.get("status", "ok"))

            parsed_items.append(
                TransactionItem(
                    hash=tx_hash,
                    from_address=from_addr,
                    to_address=to_addr,
                    value=val_dec,
                    block_number=block_int,
                    timestamp=ts_dt,
                    status=status_str,
                )
            )

        return ProviderResult(
            status=ProviderStatus.OK,
            data=TransactionListResult(items=parsed_items, next_cursor=next_cursor),
            source=self.name,
        )

    def get_latest_block(self, network: str) -> ProviderResult:
        chain_id = self._resolve_chain_id(network)
        path = f"/{chain_id}/api/v2/stats"
        res = self._request(path)
        if res.status != ProviderStatus.OK:
            return res

        data = res.data if isinstance(res.data, dict) else {}
        total_blocks_raw = data.get("total_blocks")
        if total_blocks_raw is None:
            return ProviderResult(
                status=ProviderStatus.ERROR,
                error="total_blocks missing from stats response",
                source=self.name,
            )

        try:
            total_blocks = int(str(total_blocks_raw))
        except (ValueError, TypeError) as e:
            return ProviderResult(
                status=ProviderStatus.ERROR,
                error=f"Invalid total_blocks format: {e}",
                source=self.name,
            )

        return ProviderResult(status=ProviderStatus.OK, data=total_blocks, source=self.name)

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

    def get_transaction_details(self, tx_hash: str, network: str) -> ProviderResult:
        chain_id = self._resolve_chain_id(network)
        path = f"/{chain_id}/api/v2/transactions/{tx_hash}"
        return self._request(path)

    def get_token_metadata(self, contract: str, network: str) -> ProviderResult:
        chain_id = self._resolve_chain_id(network)
        path = f"/{chain_id}/api/v2/tokens/{contract}"
        return self._request(path)
