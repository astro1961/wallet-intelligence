# STAGE 4A — Sync engine + activity tracker (core, no UI)

Spec: `docs/spec.md` §5 (sync), §6 (activities), §11 Этап 4. The provider layer from Stage 3 is
already in place and verified live. This stage consumes it and must stay UI-free.

TDD. Write the tests, watch them fail, implement. `docs/` and the reviewer's gates are off-limits.

## Pinned contract

```python
# app/core/sync_engine.py
@dataclass
class SyncReport:
    wallet_id: int
    network: str
    status: str              # "ok" | "error" | "skipped"
    activities_added: int = 0
    activities_updated: int = 0
    balance_saved: bool = False
    error: str | None = None

class SyncEngine:
    def __init__(self, session_factory, providers: ProviderRegistry, config) -> None
    def sync_wallet(self, wallet_id: int, network: str | None = None) -> SyncReport
    def sync_all(self, network: str | None = None) -> list[SyncReport]
```

```python
# app/core/activity_tracker.py
class ActivityTracker:
    def __init__(self, session_factory, config) -> None
    def record(self, session, wallet, network, tx) -> Activity   # tx: ProviderResult item (TransactionItem)
    def classify(self, wallet_address: str, tx) -> str
```

## Behaviour that is pinned by the gate

1. **One wallet, happy path.** `sync_wallet` fetches the native balance and the transaction list,
   writes one `BalanceSnapshot`, one `Transaction` and one `Activity` per transaction, updates
   `SyncCursor` (`data_type="tx"`, `last_block_number` = latest processed block) and closes a
   `SyncJob` row with `status="completed"`.
2. **Idempotency.** A second run of the same window adds **zero** activities, does not duplicate
   transactions or snapshots. Dedup keys: `Activity (wallet_id, tx_hash, log_index)`,
   `Transaction (wallet_id, network_id, tx_hash)`. Enforce with a unique index — the schema already
   has the columns; add revision `005` if an index is missing, never edit 001–004.
3. **Incremental sync.** The next run reads `SyncCursor.last_block_number` and passes it to the
   provider as `cursor={"block": <n>, "last_block": <n>}` (extra keys allowed). A fresh wallet
   passes `cursor=None`.
4. **Error isolation.** `sync_all` iterates wallets; a provider `ERROR` for one wallet produces
   `SyncReport(status="error", error=...)`, keeps that wallet's `SyncJob.status="failed"`, and the
   remaining wallets still run. No exception escapes `sync_all`.
5. **Classification.** `from == wallet` → `"send"`; `to == wallet` → `"receive"`; a transaction to a
   known `ProjectContract` → `"contract_call"` with `project_id` set and `source="detected"`;
   self-transfers are `"self"`. Amounts stay `Decimal`, timestamps UTC.
6. **Project detection by contract.** The lookup happens by `(network_id, lower(address))` over
   `project_contracts`. No project match → `project_id=None`.
7. **No UI imports, no silent except-pass** in either module.

## Also required

- `SyncJob` rows: `job_type="wallet_sync"`, `started_at`/`finished_at` UTC, `error_message` filled
  on failure.
- Rate-limit aware: `ProviderStatus.RATE_LIMITED` → `SyncReport(status="error")` with a retry hint,
  not a silent skip.
- Logging: one INFO line per wallet with counts, one WARNING per failure with the provider and
  message (never the API key).

## Tests you must write (in `tests/unit/`)

At least: happy path, idempotency, cursor resume, error isolation, classification of
send/receive/contract_call/self, project detection, snapshot precision (`Decimal`, no float).

## Definition of Done

```
uv run pytest -q -m "not live"
uv run ruff check .
```

Gates are run by the reviewer (not present in this working copy — that is intentional).

Report in Russian: the dedup strategy you implemented (and whether a migration 005 was needed), how
the cursor is stored and resumed, and the real test output.
