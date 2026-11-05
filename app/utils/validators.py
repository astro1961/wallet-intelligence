"""Address validation and normalization utilities for EVM and Solana."""
from __future__ import annotations

import functools

_HEX_CHARS = set("0123456789abcdefABCDEF")
_BASE58_ALPHABET = set("123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz")
_KECCAK_ROTC = (
    (0, 36, 3, 41, 18),
    (1, 44, 10, 45, 2),
    (62, 6, 43, 15, 61),
    (28, 55, 25, 21, 56),
    (27, 20, 39, 8, 14),
)
_KECCAK_RC = (
    0x0000000000000001,
    0x0000000000008082,
    0x800000000000808A,
    0x8000000080008000,
    0x000000000000808B,
    0x0000000080000001,
    0x8000000080008081,
    0x8000000000008009,
    0x000000000000008A,
    0x0000000000000088,
    0x0000000080008009,
    0x000000008000000A,
    0x000000008000808B,
    0x800000000000008B,
    0x8000000000008089,
    0x8000000000008003,
    0x8000000000008002,
    0x8000000000000080,
    0x000000000000800A,
    0x800000008000000A,
    0x8000000080008081,
    0x8000000000008080,
    0x0000000080000001,
    0x8000000080008008,
)


def _keccak_256(data: bytes) -> bytes:
    """Pure-Python implementation of Keccak-256 hash."""
    rate = 136  # 1088 bits = 136 bytes
    pad_len = rate - (len(data) % rate)
    if pad_len == 1:
        padding = b"\x81"
    else:
        padding = b"\x01" + b"\x00" * (pad_len - 2) + b"\x80"
    padded = data + padding

    state = [[0] * 5 for _ in range(5)]

    for block_idx in range(0, len(padded), rate):
        block = padded[block_idx : block_idx + rate]
        for i in range(rate // 8):
            x = i % 5
            y = i // 5
            val = int.from_bytes(block[i * 8 : (i + 1) * 8], "little")
            state[x][y] ^= val

        for round_idx in range(24):
            # Theta step
            c = [
                state[x][0] ^ state[x][1] ^ state[x][2] ^ state[x][3] ^ state[x][4]
                for x in range(5)
            ]
            d = [
                c[(x - 1) % 5]
                ^ (((c[(x + 1) % 5] << 1) | (c[(x + 1) % 5] >> 63)) & 0xFFFFFFFFFFFFFFFF)
                for x in range(5)
            ]
            for x in range(5):
                for y in range(5):
                    state[x][y] ^= d[x]

            # Rho and Pi steps
            b = [[0] * 5 for _ in range(5)]
            for x in range(5):
                for y in range(5):
                    rot = _KECCAK_ROTC[x][y]
                    val = state[x][y]
                    b[y][(2 * x + 3 * y) % 5] = (
                        ((val << rot) | (val >> (64 - rot))) & 0xFFFFFFFFFFFFFFFF if rot else val
                    )

            # Chi step
            for x in range(5):
                for y in range(5):
                    state[x][y] = b[x][y] ^ ((~b[(x + 1) % 5][y]) & b[(x + 2) % 5][y])

            # Iota step
            state[0][0] ^= _KECCAK_RC[round_idx]

    out_bytes = bytearray()
    for i in range(4):
        x = i % 5
        y = i // 5
        out_bytes.extend(state[x][y].to_bytes(8, "little"))
    return bytes(out_bytes)


@functools.lru_cache(maxsize=4096)
def _compute_checksum_address(hex_addr: str) -> str:
    """Compute EIP-55 checksum address from lowercase 40-character hex address."""
    h = _keccak_256(hex_addr.encode("ascii")).hex()
    checksummed = "".join(
        c.upper() if int(h[i], 16) >= 8 else c for i, c in enumerate(hex_addr)
    )
    return "0x" + checksummed


@functools.lru_cache(maxsize=4096)
def normalize_evm_address(value: str) -> str:
    """Normalize and validate an EVM address according to EIP-55 checksum rules.

    Raises ValueError if the address is not a valid 20-byte hex address or if
    a mixed-case address has an invalid checksum.
    """
    if not isinstance(value, str):
        raise ValueError(f"EVM address must be a string, got {type(value).__name__}")  # noqa: TRY004

    val = value.strip()
    if not val.startswith(("0x", "0X")):
        raise ValueError(f"EVM address must start with '0x', got {val!r}")

    hex_part = val[2:]
    if len(hex_part) != 40:
        raise ValueError(f"EVM address must be 40 hex characters (20 bytes), got length {len(hex_part)}")

    if not all(c in _HEX_CHARS for c in hex_part):
        raise ValueError(f"EVM address contains invalid hexadecimal characters: {val!r}")

    lower_hex = hex_part.lower()
    checksummed = _compute_checksum_address(lower_hex)

    # If the input has mixed case (both upper and lower letters), it asserts an EIP-55 checksum
    has_upper = any(c.isupper() for c in hex_part)
    has_lower = any(c.islower() for c in hex_part)
    if has_upper and has_lower and ("0x" + hex_part) != checksummed:
        raise ValueError(f"Invalid EIP-55 checksum for address {val!r}")

    return checksummed


def is_valid_evm_address(value: str) -> bool:
    """Return True if value is a valid EVM address, False otherwise."""
    try:
        normalize_evm_address(value)
        return True
    except (ValueError, TypeError, AttributeError):
        return False


def is_valid_solana_address(value: str) -> bool:
    """Return True if value is a valid Solana address (base58, 32-44 chars, not EVM)."""
    if not isinstance(value, str):
        return False

    val = value.strip()
    if val.startswith(("0x", "0X")):
        return False

    if not (32 <= len(val) <= 44):
        return False

    return all(c in _BASE58_ALPHABET for c in val)
