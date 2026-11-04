# STAGE 1A — review fixes (blocking)

The reviewer ran an independent gate plus a manual code review on your Stage 1A output.
Two blocking defects and two hygiene issues were found. Fix exactly these; do not start
Stage 1B, do not restructure anything else.

`acceptance/` is off-limits (read-only for you). `tests/unit/` — add regression tests for
every fix below **first**, watch them fail, then fix (TDD).

## B1 (blocking). The "migration" is not a migration

`migrations/versions/001_initial_schema.py` contains:

```python
def upgrade() -> None:
    Base.metadata.create_all(op.get_bind())
```

That is `create_all` wearing an Alembic costume. Consequences: the revision is not
reproducible (it tracks whatever the models look like today), `--autogenerate` will see no
diff against it, downgrade/partial upgrade cannot work, and a future model change silently
rewrites history.

Required: a real, frozen DDL revision — explicit `op.create_table(...)` for all 22 tables
with their columns, `sa.ForeignKeyConstraint`s, `UniqueConstraint`s, `CheckConstraint`s and
`op.create_index(...)` for the indexes currently declared in `models.py`, plus a
`downgrade()` that drops them in reverse FK order. No import of `app.database.models`, no
`create_all`, no `Base.metadata` use inside the revision.

How: create a scratch database, run
`alembic revision --autogenerate -m tmp` against it (the models are the source of truth for
the first revision), then keep the generated DDL, renumber/rename it to the existing
`001_initial_schema` revision id (so the chain has a single root), and delete the scratch
revision. Verify `alembic upgrade head` **and** `alembic downgrade base` both succeed on a
throwaway `WIT_DB_PATH`, and that the second `upgrade head` is a no-op.

The dev database `data/wallet_tracker.db` may be deleted and recreated — say so in the report.

## B2 (blocking). Address normalization only works in the constructor

`Wallet.__init__` lowercases an EVM address, but plain attribute assignment does not:

```python
w = Wallet(address="0xAA..01"); w.address = "0xBB..02"   # → stays uppercase
```

Every write path (repository.update, import, sync) then depends on the caller remembering to
normalize, which breaks the `(address, chain_type)` dedupe guarantee.

Required: SQLAlchemy `@validates("address")` on `Wallet` (lowercase only when
`chain_type == "evm"`, keep Solana/base58 case intact, keep `address_raw` for the original
spelling) and the same `@validates` normalization for `ProjectContract.contract_address` and
`Token.contract_address` (EVM-only tables). Repository-level normalization may stay as a
no-op but must not be the only guarantee.

## H1. `init_db()` hides migration failures and mutates global state

`app/database/session.py`:
- `except (ImportError, OSError, Exception)` silently falls back to `create_all` on *any*
  error, including a broken revision. Narrow it: catch `ImportError` (alembic missing) and
  `alembic.util.exc.CommandError`/`sqlalchemy.exc.SQLAlchemyError`, log a WARNING with the
  reason, then fall back. Never swallow `KeyboardInterrupt`/`SystemExit`.
- `init_db()` writes `os.environ["WIT_DB_PATH"]` as a side effect — remove that.
- Re-calling `init_db()` must `dispose()` the previous engine before creating a new one.

## H2. Repository `update()` is too permissive

`WalletRepository.update()` uses `hasattr()` as the whitelist, so callers can rewrite `id`,
`created_at`, or `address_raw` by accident. Restrict it to an explicit editable-field set
(`name`, `address`, `group_id`, `notes`, `chain_type`, `archived`, plus existing metadata
fields) and raise `ValueError` on anything else.

## Definition of Done

```
uv run pytest -q
uv run python -m pytest acceptance/gate_stage1a.py -q      # must be 16 passed
uv run ruff check .
WIT_DB_PATH=/tmp/wit_mig.db uv run alembic upgrade head
WIT_DB_PATH=/tmp/wit_mig.db uv run alembic downgrade base
```

Report in Russian: what changed per item, the real command output, anything you consider
still weak.
