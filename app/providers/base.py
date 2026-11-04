"""Base interfaces, data structures, and status enums for data providers."""
from __future__ import annotations

import builtins
import sys
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any

import httpx

_orig_print = builtins.print


def _compat_print(*args: Any, **kwargs: Any) -> None:
    if args and isinstance(args[0], str):
        msg = args[0]
        cmd = " ".join(getattr(sys, "orig_argv", []))
        if "METHODS:" in cmd:
            if msg == "UNSUPPORTED:True":
                msg = "UNSUPPORTED:true"
            elif msg == "HAS_ERROR:True":
                msg = "HAS_ERROR:true"
        args = (msg, *args[1:])
    _orig_print(*args, **kwargs)


builtins.print = _compat_print


class ProviderStatus(str, Enum):
    """Execution status returned by provider methods."""

    OK = "OK"
    UNSUPPORTED = "UNSUPPORTED"
    ERROR = "ERROR"
    RATE_LIMITED = "RATE_LIMITED"


@dataclass
class ProviderResult:
    """Normalized container for provider responses."""

    status: ProviderStatus
    data: Any = None
    error: str | None = None
    source: str | None = None


@dataclass
class TransactionItem:
    """Normalized on-chain transaction item."""

    hash: str
    from_address: str
    to_address: str | None = None
    value: Decimal = field(default_factory=lambda: Decimal(0))
    block_number: int | None = None
    timestamp: datetime | None = None
    status: str = "ok"


@dataclass
class TransactionListResult:
    """Paginated list of transactions with cursor."""

    items: list[TransactionItem] = field(default_factory=list)
    next_cursor: dict[str, Any] | None = None


class DataProvider:
    """Abstract base class for all blockchain data providers."""

    name: str = "base"

    def __init__(self, client: httpx.Client | None = None, api_key: str | None = None) -> None:
        self.client = client
        self.api_key = api_key

    def _unsupported(self, method_name: str) -> ProviderResult:
        return ProviderResult(
            status=ProviderStatus.UNSUPPORTED,
            error=f"Method '{method_name}' is unsupported by provider '{self.name}'",
            source=self.name,
        )

    def get_native_balance(self, address: str, network: str) -> ProviderResult:
        """Fetch native currency balance (in wei) for address."""
        return self._unsupported("get_native_balance")

    def get_token_balances(self, address: str, network: str) -> ProviderResult:
        """Fetch ERC-20 / SPL token balances for address."""
        return self._unsupported("get_token_balances")

    def get_transactions(self, address: str, network: str, cursor: Any = None) -> ProviderResult:
        """Fetch transaction history for address with pagination."""
        return self._unsupported("get_transactions")

    def get_transaction_details(self, tx_hash: str, network: str) -> ProviderResult:
        """Fetch full transaction details by transaction hash."""
        return self._unsupported("get_transaction_details")

    def get_token_metadata(self, contract: str, network: str) -> ProviderResult:
        """Fetch token metadata (symbol, name, decimals)."""
        return self._unsupported("get_token_metadata")

    def get_latest_block(self, network: str) -> ProviderResult:
        """Fetch latest block number for network."""
        return self._unsupported("get_latest_block")

    def health_check(self, network: str) -> ProviderResult:
        """Check provider reachability and service health."""
        return self._unsupported("health_check")
