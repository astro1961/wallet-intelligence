"""Etherscan v2 API data provider adapter."""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import UTC, datetime
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
from app.providers.blockscout import CHAIN_ID_MAP, _KeyFilter

logger = logging.getLogger(__name__)


class EtherscanProvider(DataProvider):
    """Etherscan v2 API data provider acting as failover."""

    name: str = "etherscan"

    def __init__(
        self,
        client: httpx.Client | None = None,
        api_key: str | None = None,
        default_chain_id: int = 1,
        base_url: str = "https://api.etherscan.io/v2/api",
        max_retries: int = 2,
        backoff_base: float = 0.5,
        page_size: int = 100,
        rps: float = 3.0,
    ) -> None:
        super().__init__(client=client, api_key=api_key)
        self.default_chain_id = default_chain_id
        self.base_url = base_url.rstrip("/")
        self.max_retries = max(0, max_retries)
        self.backoff_base = max(0.0, backoff_base)
        self.page_size = max(1, page_size)
        self.rps = max(0.0, rps)
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

    def close(self) -> None:
        if getattr(self, "_managed_client", False) and self.client:
            self.client.close()

    def _resolve_chain_id(self, network: str | None) -> int:
        if network:
            key = network.strip().lower()
            if key in ("ethereum", "mainnet", "eth"):
                return self.default_chain_id
            if key in CHAIN_ID_MAP:
                return CHAIN_ID_MAP[key]
            try:
                return int(key)
            except ValueError as exc:
                logger.debug("Failed to parse network string '%s' as integer chain_id: %s", key, exc)
        return self.default_chain_id

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

    def _request(self, params: dict[str, Any] | None = None) -> ProviderResult:
        query_params = dict(params or {})
        if self.api_key:
            query_params["apikey"] = self.api_key

        url = "" if (self.client and self.client.base_url and str(self.client.base_url).rstrip("/") != "") else self.base_url
        last_status_code: int | None = None
        last_error_text: str | None = None

        for attempt in range(self.max_retries + 1):
            self._throttle()
            try:
                assert self.client is not None
                resp = self.client.get(url, params=query_params)
                last_status_code = resp.status_code

                if resp.status_code == 429:
                    last_error_text = "Rate limit exceeded"
                    if attempt < self.max_retries:
                        time.sleep(self.backoff_base * (2**attempt))
                        continue
                    logger.warning("Etherscan rate limited: 429")
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
                    logger.warning("Etherscan server error: %d", resp.status_code)
                    return ProviderResult(
                        status=ProviderStatus.ERROR,
                        error=self._sanitize(f"Etherscan server error {resp.status_code}"),
                        source=self.name,
                    )

                if 200 <= resp.status_code < 300:
                    try:
                        data = resp.json()
                    except json.JSONDecodeError as e:
                        return ProviderResult(
                            status=ProviderStatus.ERROR,
                            error=self._sanitize(f"Failed to parse JSON response: {e}"),
                            source=self.name,
                        )

                    if isinstance(data, dict):
                        if "status" in data:
                            status_val = str(data.get("status"))
                            if status_val == "0":
                                msg = str(data.get("message", ""))
                                res_val = str(data.get("result", ""))
                                combined = f"{msg} {res_val}".strip().lower()
                                if "rate limit" in combined:
                                    return ProviderResult(
                                        status=ProviderStatus.RATE_LIMITED,
                                        error=self._sanitize(str(data.get("result") or data.get("message") or "Rate limit exceeded")),
                                        source=self.name,
                                    )
                                if (
                                    params
                                    and params.get("action") == "txlist"
                                    and "no transactions" in msg.lower()
                                    and isinstance(data.get("result"), list)
                                ):
                                    return ProviderResult(
                                        status=ProviderStatus.OK,
                                        data=data,
                                        source=self.name,
                                    )
                                return ProviderResult(
                                    status=ProviderStatus.ERROR,
                                    error=self._sanitize(str(data.get("result") or data.get("message") or "Etherscan error")),
                                    source=self.name,
                                )
                        elif data.get("error"):
                            err_obj = data["error"]
                            err_msg = err_obj.get("message") if isinstance(err_obj, dict) else str(err_obj)
                            return ProviderResult(
                                status=ProviderStatus.ERROR,
                                error=self._sanitize(f"JSON-RPC error: {err_msg}"),
                                source=self.name,
                            )

                    return ProviderResult(status=ProviderStatus.OK, data=data, source=self.name)

                # Client error (4xx other than 429)
                try:
                    data = resp.json()
                    if isinstance(data, dict):
                        msg = str(data.get("message", ""))
                        res_val = str(data.get("result", ""))
                        combined = f"{msg} {res_val}".strip().lower()
                        if "rate limit" in combined:
                            return ProviderResult(
                                status=ProviderStatus.RATE_LIMITED,
                                error=self._sanitize(str(data.get("result") or data.get("message") or "Rate limit exceeded")),
                                source=self.name,
                            )
                        if data.get("status") == "0" or "error" in data:
                            return ProviderResult(
                                status=ProviderStatus.ERROR,
                                error=self._sanitize(str(data.get("result") or data.get("message") or f"Etherscan client error {resp.status_code}")),
                                source=self.name,
                            )
                except (json.JSONDecodeError, ValueError):
                    logger.debug("Failed to decode client error JSON response")

                return ProviderResult(
                    status=ProviderStatus.ERROR,
                    error=self._sanitize(f"Etherscan client error {resp.status_code}"),
                    source=self.name,
                )

            except httpx.TransportError as exc:
                last_error_text = str(exc)
                if attempt < self.max_retries:
                    time.sleep(self.backoff_base * (2**attempt))
                    continue
                logger.warning("Etherscan transport error: %s", self._sanitize(str(exc)))
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
        params = {
            "module": "account",
            "action": "balance",
            "chainid": chain_id,
            "address": address,
            "tag": "latest",
        }
        res = self._request(params=params)
        if res.status != ProviderStatus.OK:
            return res

        data = res.data if isinstance(res.data, dict) else {}
        raw_balance = data.get("result")
        if raw_balance is None:
            raw_balance = "0"

        try:
            balance_dec = Decimal(str(raw_balance))
        except (InvalidOperation, ValueError) as e:
            return ProviderResult(
                status=ProviderStatus.ERROR,
                error=f"Invalid balance format: {e}",
                source=self.name,
            )

        return ProviderResult(status=ProviderStatus.OK, data=balance_dec, source=self.name)

    def get_transactions(self, address: str, network: str, cursor: Any = None) -> ProviderResult:
        chain_id = self._resolve_chain_id(network)
        params: dict[str, Any] = {
            "module": "account",
            "action": "txlist",
            "chainid": chain_id,
            "address": address,
            "sort": "desc",
        }

        current_page = 1
        if isinstance(cursor, dict):
            current_page = int(cursor.get("page", 1))
            params["page"] = current_page
            params["offset"] = cursor.get("offset", self.page_size)
        elif isinstance(cursor, int):
            current_page = cursor
            params["page"] = current_page
            params["offset"] = self.page_size

        res = self._request(params=params)
        if res.status != ProviderStatus.OK:
            return res

        data = res.data if isinstance(res.data, dict) else {}
        raw_items = data.get("result", [])
        if not isinstance(raw_items, list):
            raw_items = []

        parsed_items: list[TransactionItem] = []
        for raw in raw_items:
            if not isinstance(raw, dict):
                continue

            tx_hash = str(raw.get("hash", ""))
            from_addr = str(raw.get("from", ""))
            to_val = raw.get("to")
            to_addr = str(to_val) if to_val is not None else None

            raw_val = raw.get("value", "0")
            try:
                val_dec = Decimal(str(raw_val))
            except (InvalidOperation, ValueError, TypeError):
                val_dec = Decimal(0)

            block_num = raw.get("blockNumber")
            try:
                block_int = int(str(block_num)) if block_num is not None else None
            except (ValueError, TypeError):
                block_int = None

            ts_raw = raw.get("timeStamp")
            ts_dt: datetime | None = None
            if ts_raw is not None:
                try:
                    ts_dt = datetime.fromtimestamp(int(ts_raw), tz=UTC)
                except (ValueError, TypeError, OSError):
                    ts_dt = None

            is_error = str(raw.get("isError", "0"))
            status_str = "ok" if is_error == "0" else "error"

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

        if len(parsed_items) < self.page_size:
            next_cursor = None
        else:
            next_cursor = {"page": current_page + 1, "offset": self.page_size}

        return ProviderResult(
            status=ProviderStatus.OK,
            data=TransactionListResult(items=parsed_items, next_cursor=next_cursor),
            source=self.name,
        )

    def get_latest_block(self, network: str) -> ProviderResult:
        chain_id = self._resolve_chain_id(network)
        params = {
            "module": "proxy",
            "action": "eth_blockNumber",
            "chainid": chain_id,
        }
        res = self._request(params=params)
        if res.status != ProviderStatus.OK:
            return res

        data = res.data if isinstance(res.data, dict) else {}
        result_val = data.get("result")
        if result_val is None:
            return ProviderResult(
                status=ProviderStatus.ERROR,
                error="result missing in proxy response",
                source=self.name,
            )

        try:
            if isinstance(result_val, str) and result_val.startswith("0x"):
                block_int = int(result_val, 16)
            else:
                block_int = int(str(result_val))
        except (ValueError, TypeError) as e:
            return ProviderResult(
                status=ProviderStatus.ERROR,
                error=f"Invalid blockNumber format: {e}",
                source=self.name,
            )

        return ProviderResult(status=ProviderStatus.OK, data=block_int, source=self.name)

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
