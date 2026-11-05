# STAGE 9A — RPC failover across multiple endpoints

Today `EvmRpcProvider` holds one URL per network and retries the same URL. The `RpcEndpoint` model
already stores `priority`/`is_primary`/`is_backup`/`is_healthy` but is unused. Add a failover provider
that tries several RPC URLs in priority order.

TDD. Gates are outside this repo (intentional). `docs/` is read-only for you.

## Pinned contract

```python
# app/providers/rpc_failover.py
class RpcFailoverProvider(DataProvider):
    name = "rpc_failover"
    def __init__(self, endpoints: list[str], client: httpx.Client | None = None,
                 max_retries: int = 0, backoff_base: float = 0.0) -> None
    @property
    def healthy(self) -> dict[str, bool]   # endpoint url -> health flag
    def get_native_balance(self, address: str, network: str) -> ProviderResult  # wei Decimal
    def get_latest_block(self, network: str) -> ProviderResult                    # int
    def health_check(self, network: str) -> ProviderResult
```

### Semantics (the gate asserts these exactly)

1. **Ordered failover.** On each call, try `endpoints` in the order given. A 5xx, 429, JSON-RPC
   `error`, or transport error (`httpx.TransportError`) on an endpoint marks it `healthy=False` and
   moves to the next; a 200 with a valid `result` marks it `healthy=True` and returns.
2. **`healthy` is an observability flag, not a call filter.** The provider always attempts endpoints
   in order so a recovered primary is retried and re-flagged healthy on success (the gate asserts a
   recovered primary becomes `source` again). Never raise out of a call.
3. **All endpoints down → `ProviderResult(status=ERROR, data=None)`** with the last error text; never
   a thrown exception, never a zero/empty "success".
4. **Parse from hex.** `get_native_balance` → `eth_getBalance` hex → `Decimal` wei;
   `get_latest_block` → `eth_blockNumber` hex → `int`. Do NOT `float`.
5. **Explicit unsupported.** `get_transactions`, `get_token_balances`,
   `get_transaction_details`, `get_token_metadata` return `UNSUPPORTED`.

## Rules

- `Decimal`/`int`, no `float`. Inject the `httpx.Client` (tests pass `httpx.MockTransport`); do not
  bake a client or a URL into the class body.
- Do not modify `EvmRpcProvider`, `registry.py`, or `factory.py` in this stage — the failover
  provider is additive.
- No monkeypatching of builtins/sys; no reading the gates.

## Tests you must write

Fails over on 5xx; fails over on transport error; all-down returns ERROR (not exception); hex
parsing for balance and block; recovery after primary restored; explicit UNSUPPORTED methods.

## Definition of Done

```
time uv run pytest -q -m "not live"
uv run ruff check .
```

Report in Russian: how failover ordering and the `healthy` flag interact, and the real test output.
