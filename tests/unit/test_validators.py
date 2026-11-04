"""Unit tests for EVM and Solana address validators."""
from __future__ import annotations

import pytest

from app.utils.validators import (
    is_valid_evm_address,
    is_valid_solana_address,
    normalize_evm_address,
)


def test_normalize_evm_address_valid():
    lower = "0xfb6916095ca1df60bb79ce92ce3ea74c37c5d359"
    checksummed = "0xfB6916095ca1df60bB79Ce92cE3Ea74c37c5d359"
    upper = "0XFB6916095CA1DF60BB79CE92CE3EA74C37C5D359"

    assert normalize_evm_address(lower) == checksummed
    assert normalize_evm_address(checksummed) == checksummed
    assert normalize_evm_address(upper) == checksummed


def test_normalize_evm_address_bad_checksum():
    # Last char changed from 9 to A in mixed-case string
    bad = "0xfB6916095ca1df60bB79Ce92cE3Ea74c37c5d35A"
    with pytest.raises(ValueError, match="checksum"):
        normalize_evm_address(bad)


def test_normalize_evm_address_invalid_format():
    with pytest.raises(ValueError):
        normalize_evm_address("0x1234")
    with pytest.raises(ValueError):
        normalize_evm_address("0x" + "a" * 39)
    with pytest.raises(ValueError):
        normalize_evm_address("0x" + "a" * 41)
    with pytest.raises(ValueError):
        normalize_evm_address("fb6916095ca1df60bb79ce92ce3ea74c37c5d359")
    with pytest.raises(ValueError):
        normalize_evm_address("0xZZ6916095ca1df60bb79ce92ce3ea74c37c5d359")
    with pytest.raises(ValueError):
        normalize_evm_address(123)  # type: ignore[arg-type]


def test_is_valid_evm_address():
    assert is_valid_evm_address("0xfb6916095ca1df60bb79ce92ce3ea74c37c5d359") is True
    assert is_valid_evm_address("0xfB6916095ca1df60bB79Ce92cE3Ea74c37c5d359") is True
    assert is_valid_evm_address("0x1234") is False
    assert is_valid_evm_address("0xfB6916095ca1df60bB79Ce92cE3Ea74c37c5d35A") is False
    assert is_valid_evm_address("not_an_address") is False
    assert is_valid_evm_address(None) is False  # type: ignore[arg-type]


def test_is_valid_solana_address():
    assert is_valid_solana_address("5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1") is True
    assert is_valid_solana_address("0xfB6916095ca1df60bB79Ce92cE3Ea74c37c5d359") is False
    assert is_valid_solana_address("0x1234") is False
    assert is_valid_solana_address("5Q544f") is False  # too short
    assert is_valid_solana_address("5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1" * 2) is False  # too long
    assert is_valid_solana_address("00000000000000000000000000000000") is False  # contains '0', not base58
    assert is_valid_solana_address(None) is False  # type: ignore[arg-type]
