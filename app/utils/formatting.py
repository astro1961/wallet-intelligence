"""Formatting helper utilities for numbers, currencies, and addresses."""
from __future__ import annotations

from decimal import Decimal
from typing import Any


def shorten_address(address: str, prefix_len: int = 6, suffix_len: int = 4) -> str:
    """Shorten an address like 0x1234...5678."""
    if not address or len(address) <= prefix_len + suffix_len + 3:
        return address
    return f"{address[:prefix_len]}...{address[-suffix_len:]}"


def format_currency(value: Any, symbol: str = "$", decimals: int = 2) -> str:
    """Format numeric value as localized currency string."""
    if value is None:
        return f"{symbol}0.00"
    try:
        val = Decimal(str(value))
        return f"{symbol}{val:,.{decimals}f}"
    except (ValueError, TypeError, ArithmeticError):
        return f"{symbol}{value}"


def format_token_amount(
    raw_or_decimal: Any,
    decimals: int = 18,
    precision: int = 4,
) -> str:
    """Format token amount given raw units or decimal amount."""
    if raw_or_decimal is None:
        return "0"
    try:
        val = Decimal(str(raw_or_decimal))
        if decimals > 0 and val >= Decimal(10**decimals):
            # If large raw units were provided
            val = val / Decimal(10**decimals)
        # Format without trailing zeros if integer
        formatted = f"{val:.{precision}f}".rstrip("0").rstrip(".")
        return formatted if formatted else "0"
    except (ValueError, TypeError, ArithmeticError):
        return str(raw_or_decimal)
