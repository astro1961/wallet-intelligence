# STAGE 3-FIX — schema change must go into a new Alembic revision

Your Stage 3 work is 90% accepted: 115 non-live tests pass, the acceptance gate covers the
provider layer, and the live Blockscout test passes. One **blocking** defect remains, already
reproduced by the reviewer's gate.

## Blocker: revision 001 was rewritten after being applied

`git diff` showed two added columns inside `migrations/versions/001_initial_schema.py`:

```python
sa.Column("block_number", sa.Integer(), nullable=True),
sa.Column("taken_at", sa.DateTime(timezone=True), nullable=True),
```

The reviewer has already reverted that file to its committed content. Editing an applied
revision means: existing databases never get the columns, newly created ones do, and two
installs of the same version disagree — the history is no longer reproducible.

Proof from the gate now:
```
test_schema_matches_models_after_upgrade  FAILED
  migrations do not produce the model schema: ["balance_snapshots: ['block_number', 'taken_at']"]
test_balance_snapshot_persisted           FAILED
```

## Required fix

1. **Do not touch `001_initial_schema.py` or `002_wallet_audit_log.py`.** Their sha256 is
   pinned in `acceptance/gate_stage3.py` (`test_frozen_revisions_untouched`).
2. Add `migrations/versions/003_balance_snapshot_block_time.py` with
   `down_revision = "002_wallet_audit_log"` that does, per column:
   ```python
   op.add_column("balance_snapshots", sa.Column("block_number", sa.Integer(), nullable=True))
   op.add_column("balance_snapshots", sa.Column("taken_at", sa.DateTime(timezone=True), nullable=True))
   ```
   and `downgrade()` dropping them (SQLite: plain `op.drop_column` is fine on this version).
   Keep it real DDL — no `create_all`, no importing models for schema.
3. If `taken_at` is redundant with `snapshot_at`, you may instead drop the idea of a second
   timestamp — but then `BalanceSnapshot.taken_at` must disappear from `models.py`,
   `balance_manager.py` and its tests, and the gate's `UTC` check must still pass through
   `snapshot_at`. Pick one option and say which.
4. Prove both paths with real commands:
   - fresh DB: `alembic upgrade head` → `PRAGMA table_info(balance_snapshots)` contains the column(s);
   - existing DB: build a DB at revision `002` (`alembic upgrade 002_wallet_audit_log`),
     insert a wallet + snapshot row, then `alembic upgrade head` → the new columns appear and the
     old row survives;
   - `alembic downgrade 002_wallet_audit_log` then `upgrade head` → still consistent.
5. Re-run the whole Definition of Done.

## Definition of Done
Run each separately, paste real output:
```
uv run pytest -q -m "not live"
env -u WIT_DB_PATH uv run python -m pytest acceptance/gate_stage3.py -q        # must be 11 passed
env -u WIT_DB_PATH uv run python -m pytest acceptance/gate_stage1a.py acceptance/gate_stage1b.py acceptance/gate_stage2a.py acceptance/gate_stage2b.py -q
uv run ruff check .
```
`live` tests are not needed for this fix.

Report in Russian: which option you chose for the timestamp, the real upgrade-path output for an
existing 002 database, and anything else you changed.
