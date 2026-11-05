# STAGE 9B — RpcManager: custom networks + per-network RPC endpoints

The `Network` model already has `rpc_url`/`chain_type`/`chain_id`, and `RpcEndpoint` already stores
`priority`/`is_primary`/`is_backup`/`is_healthy` — but nothing manages them. Add a session-based
manager for custom networks and their RPC endpoints, including primary switching and chain-id
verification.

TDD. Gates are outside this repo (intentional). `docs/` is read-only for you.

## Pinned contract

```python
# app/core/rpc_manager.py
class RpcManager:
    def __init__(self, session: Session) -> None

    def add_network(self, name, chain_type="evm", chain_id=None, rpc_url=None,
                    explorer_url=None, native_token="ETH", symbol=None, decimals=18,
                    is_testnet=False, enabled=True) -> Network
    def edit_network(self, network, **fields) -> Network
    def add_rpc_endpoint(self, network, url, priority=1, is_primary=False,
                         is_backup=False) -> RpcEndpoint
    def set_primary(self, network, endpoint_id: int) -> RpcEndpoint
    def list_rpc_endpoints(self, network) -> list[RpcEndpoint]
    def check_chain_id(self, network, client: httpx.Client | None = None) -> ProviderResult
    def check_connection(self, network, client: httpx.Client | None = None) -> ProviderResult
```

### Semantics (the gate asserts these exactly)

1. **`add_network`** validates: `chain_type` is a closed set (`evm`|`solana`); a duplicate name
   (case-insensitive) or a duplicate `(chain_type, chain_id)` raises `ValueError`; `chain_id` is
   required for `evm` and optional for `solana`. `decimals`/`symbol`/`native_token` get sane defaults.
2. **`add_rpc_endpoint`** appends an `RpcEndpoint` with the given `priority`; a URL already present
   for the network is not duplicated.
3. **`list_rpc_endpoints`** returns endpoints ordered by `priority` ascending.
4. **`set_primary`** makes exactly one endpoint `is_primary=True` (clearing the previous primary);
   the endpoint's `priority` does not need to be 1, but the switch must be unambiguous.
5. **`check_chain_id`** POSTs `eth_chainId` to the network's RPC (or the primary endpoint) through an
   injectable `client`, parses the hex result to `int`, and returns `OK` when it equals
   `network.chain_id`, `ERROR` otherwise (never a thrown exception on transport/RPC error).
6. **`check_connection`** returns `OK`/`ERROR` based on `eth_blockNumber` reachability.

## Rules

- Use `Decimal`/`int`, no `float`; `client` is injectable (tests pass `httpx.MockTransport`).
- Work inside the provided session (do not open your own); no UI imports in core.
- No monkeypatching of builtins/sys; no reading the gates.

## Tests you must write

Add network + duplicate/type validation; endpoint priority order; `set_primary` yields exactly one
primary; `check_chain_id` match and mismatch; `check_connection`; and no-float/no-UI hygiene.

## Definition of Done

```
time uv run pytest -q -m "not live"
uv run ruff check .
```

Report in Russian: how `set_primary` keeps the primary unique, and the real test output.
