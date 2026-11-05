# STAGE 9C — Solana JSON-RPC provider

The spec requires a separate Solana adapter (architected as its own stage). EVM providers exist;
add a minimal, correct Solana JSON-RPC provider. Address validation is already available
(`is_valid_solana_address` in `app/utils/validators.py`).

TDD. Gates are outside this repo (intentional). `docs/` is read-only for you.

## Pinned contract

```python
# app/providers/solana.py
class SolanaProvider(DataProvider):
    name = "solana"
    def __init__(self, rpc_url: str, client: httpx.Client | None = None) -> None
    def get_native_balance(self, address: str, network: str) -> ProviderResult   # lamports Decimal
    def get_latest_block(self, network: str) -> ProviderResult                    # slot int
    def health_check(self, network: str) -> ProviderResult
```

### Semantics (the gate asserts these exactly)

1. **`get_native_balance`** POSTs `getBalance` and returns the lamports value as a **`Decimal`**
   (raw units — the same convention as wei for EVM; do not convert to SOL, do not `float`). An
   invalid address (`is_valid_solana_address` False) returns `ERROR` with `data=None`, never a thrown
   exception.
2. **`get_latest_block`** POSTs `getSlot` and returns the slot as an **`int`**.
3. **`health_check`** POSTs `getHealth`; `result == "ok"` → `OK`, anything else → `ERROR`.
4. **Explicit unsupported.** `get_transactions`, `get_token_balances`,
   `get_transaction_details`, `get_token_metadata` return `UNSUPPORTED`.
5. **Solana returns JSON numbers, not hex.** Do not hex-decode (`int(value, 16)`); `getBalance`/`getSlot`
   values are plain integers in the JSON `result`.

## Rules

- Inject the `httpx.Client` (tests pass `httpx.MockTransport`); don't bake a client into the class.
- `Decimal`/`int`, no `float`. Use the existing `is_valid_solana_address`; don't reimplement base58.
- No monkeypatching of builtins/sys; no reading the gates.

## Tests you must write

Lamports balance as Decimal; slot as int; health ok/error; invalid address → ERROR; explicit
UNSUPPORTED; and no-float/no-hex hygiene.

## Definition of Done

```
time uv run pytest -q -m "not live"
uv run ruff check .
```

Report in Russian: how the raw-lamports convention matches the EVM wei convention, and the real test
output.
