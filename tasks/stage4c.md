# STAGE 4C — fix B8: shared transaction between two monitored wallets kills the sync

Live reproduction (not a unit test — found while rendering the demo database):

```
sqlite3.IntegrityError: UNIQUE constraint failed: transactions.network_id, transactions.tx_hash
... PendingRollbackError: This Session's transaction has been rolled back due to a previous
exception during flush.
```

Steps: two wallets you own (`A` and `B`), one transfer `A → B`. The provider returns the same
transaction hash for both wallets (correct — it is one on-chain tx). `sync_wallet(A)` succeeds,
`sync_wallet(B)` crashes: the unique index is `(network_id, tx_hash)`.

This is a data-model mistake, not an edge case: any transfer **between your own wallets**, and any
approval/contract call involving two monitored addresses, breaks the second sync. The failed flush
also leaves the session unusable, so the next statement raises `PendingRollbackError`.

## Required fixes

1. **Uniqueness must be per wallet.** Add revision `006_transactions_unique_per_wallet`:
   drop `uq_transaction_wallet_network_tx` if it is `(network_id, tx_hash)`, then create a unique
   index on `(wallet_id, network_id, tx_hash)` — the same shape `activities` already uses.
   `001`–`005` are frozen (sha256 pinned by the reviewer's gates); do not edit them. Verify both a
   fresh `upgrade head` and an upgrade from `005` on an existing database.
2. **Rollback hygiene in `SyncEngine`.** Wrap the per-wallet unit of work so a failed flush does
   `session.rollback()` before the session is reused or closed, and return
   `SyncReport(status="error", error="...")`. No `PendingRollbackError` may escape
   `sync_wallet`/`sync_all`, and a failure must not poison the next wallet's sync.
3. **Empty state markup.** `EMPTY_ACTIVITIES_MSG` contains `**s**`; the detail panel renders it
   literally, so users see asterisks instead of the key. Either render with markup enabled or drop
   the markers — the visible text must read `press s to sync your wallets`.

## Tests you must write

1. Two wallets, one shared tx hash → both syncs `ok`, `transactions` holds 2 rows (one per wallet),
   `activities` holds 4 (shared + own for each).
2. Sync is still idempotent per wallet: re-running adds 0 rows.
3. After an injected `IntegrityError` (or a duplicate insert), the session is usable — the next
   `sync_wallet` succeeds and no `PendingRollbackError` is raised.
4. Empty-state text contains no literal `**`.

## Definition of Done

```
uv run pytest -q -m "not live"
uv run ruff check .
```

Report in Russian: the index change (with the real `PRAGMA index_list('transactions')` output), how
you made the session recover after a failed flush, and the real test output.
