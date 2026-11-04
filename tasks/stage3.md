# STAGE 3 — EVM data providers (Blockscout Pro, EVM JSON-RPC, DeFiLlama), offline-testable

Stage 2A/2B accepted. Now build the provider layer per `docs/spec.md` §4 and §11 (Этап 3).
Business logic must not depend on a concrete vendor: UI and core talk to `app/providers/base.py`
interfaces only.

`acceptance/` is read-only for you. TDD: write the test, watch it fail, implement.

## Real API facts (verified by the reviewer on this host, use them)

- **Blockscout Pro API** — base `https://api.blockscout.com`, key required (already in `.env`
  as `BLOCKSCOUT_API_KEY`), 5 RPS / 100K credits per day, all EVM chains.
  Paths (chain id first): `/{chain_id}/api/v2/addresses/{hash}` → `coin_balance` (string wei),
  `/{chain_id}/api/v2/addresses/{hash}/transactions` → `{items:[…], next_page_params:{…}}`,
  `/{chain_id}/api/v2/transactions/{hash}`, `/{chain_id}/api/v2/tokens/{token}`,
  `/{chain_id}/api/v2/stats` → `total_blocks`.
- Auth is a query param `apikey=…` (headers also accept it, but the gate pins the query form).
- Verified live: `/1/api/v2/stats` → 200 `total_blocks=26342704`;
  `/{VITALIK}` → 200 `coin_balance=5780441042197210512`.
- Public EVM JSON-RPC needs no key. `eth_getBalance`, `eth_blockNumber`,
  `eth_getTransactionByHash`, `eth_call`.

## Pinned contract (the acceptance gate depends on these names)

### `app/providers/base.py`
```python
class ProviderStatus(str, Enum): OK; UNSUPPORTED; ERROR; RATE_LIMITED
@dataclass
class ProviderResult:                      # generic-ish, data is typed per call
    status: ProviderStatus
    data: Any = None
    error: str | None = None
    source: str | None = None

class DataProvider:
    name: str = "base"
    def __init__(self, client: httpx.Client | None = None, api_key: str | None = None) -> None: ...
    # every method returns ProviderResult; unimplemented ones return UNSUPPORTED with a reason
    def get_native_balance(self, address: str, network: str) -> ProviderResult
    def get_token_balances(self, address: str, network: str) -> ProviderResult
    def get_transactions(self, address: str, network: str, cursor=None) -> ProviderResult
    def get_transaction_details(self, tx_hash: str, network: str) -> ProviderResult
    def get_token_metadata(self, contract: str, network: str) -> ProviderResult
    def get_latest_block(self, network: str) -> ProviderResult
    def health_check(self, network: str) -> ProviderResult
```
No method may raise on transport/HTTP failure — return `ERROR`/`RATE_LIMITED` with a message.
Never put the API key into `error`, logs or exception text.

### `app/providers/blockscout.py`
```python
class BlockscoutProvider(DataProvider):
    name = "blockscout"
    def __init__(self, client, api_key, chain_id: int = 1,
                 base_url: str = "https://api.blockscout.com",
                 max_retries: int = 2, backoff_base: float = 0.5, rps: float = 5.0) -> None
```
- injectable `httpx.Client` (tests pass `httpx.MockTransport`); if `client is None`, build one.
- `get_native_balance` → `Decimal` (wei as int→Decimal), status `OK`.
- `get_transactions` → `data` with `.items` (list of dataclasses: `hash`, `from_address`,
  `to_address`, `value: Decimal`, `block_number: int`, `timestamp: datetime`, `status: str`)
  and `.next_cursor` (the raw `next_page_params` dict or `None`); on the next call those params
  must be forwarded as query params verbatim. `cursor=None` sends no pagination params.
- `get_latest_block` → `int` from `stats.total_blocks`; `health_check` → `OK` + latest block.
- retries on `429`/`5xx` with exponential backoff (`backoff_base * 2**attempt`), then
  `RATE_LIMITED` (429) or `ERROR`; client-side throttle to `rps`.

### `app/providers/evm_rpc.py`
```python
class EvmRpcProvider(DataProvider):
    name = "evm_rpc"
    def __init__(self, client, rpc_url: str, max_retries: int = 2, backoff_base: float = 0.5) -> None
```
`get_native_balance` → `Decimal` from `eth_getBalance` hex; `get_latest_block` → `int`;
`get_transaction_details` via `eth_getTransactionByHash`; `get_token_metadata` via `eth_call`
(`decimals()`, `symbol()`) — if the node returns a JSON-RPC error, return `UNSUPPORTED`
(or `ERROR`), never raise.

### `app/providers/defillama.py`
`DefiLlamaProvider(client, base_url="https://coins.llama.fi")`,
`get_token_price(chain: str, token: str) -> ProviderResult` (Decimal), `health_check`.

### `app/providers/registry.py`
```python
class ProviderRegistry:
    def __init__(self, providers: list[DataProvider]) -> None
    def get_native_balance(self, address, network) -> ProviderResult   # failover on ERROR/RATE_LIMITED/UNSUPPORTED
    def health_check_all(self, network) -> dict[str, ProviderResult]
```

### `app/core/balance_manager.py`
`save_native_balance(session, wallet, network, amount: Decimal, block_number: int | None = None)
-> BalanceSnapshot` — stores raw wei (int/Decimal, never float), `taken_at` in UTC.

### Config & wiring
- `config.yaml`: `providers.blockscout.base_url: https://api.blockscout.com`,
  `providers.etherscan.base_url: https://api.etherscan.io/v2/api`,
  `providers.defillama.base_url: https://coins.llama.fi`; keep `api_key_env` names.
- `app/providers/factory.py` (or `registry.build_default_registry(cfg)`): build providers from
  config, reading keys with `os.getenv(cfg.providers[...].api_key_env)`; a missing key disables
  that provider with a warning (never a crash).
- Live integration test `tests/integration/test_providers_live.py`, marked
  `@pytest.mark.live`, skipped when `BLOCKSCOUT_API_KEY` is absent; asserts real
  `get_native_balance(VITALIK)` > 0 and `get_latest_block() > 26_000_000`.
  Register the `live` marker in `pyproject.toml`.

## Tests you must write
MockTransport unit tests for both providers (success, pagination, 429 retry, 500 error,
JSON-RPC error, hex parsing), the registry failover, the balance snapshot, and the
"no key in logs/errors" rule. No test may hit the network except the `live`-marked one.

## Definition of Done
Run each separately, paste real output:
```
uv run pytest -q -m "not live"
env -u WIT_DB_PATH uv run python -m pytest acceptance/gate_stage3.py -q
env -u WIT_DB_PATH uv run python -m pytest acceptance/gate_stage1a.py acceptance/gate_stage1b.py acceptance/gate_stage2a.py acceptance/gate_stage2b.py -q
uv run ruff check .
uv run pytest -q -m live      # real Blockscout call, key is in .env
```
Report in Russian: what changed, real output including the live test, which spec §4.2 methods are
supported vs `unsupported` per provider, and what Stage 4 must consume from this layer.
