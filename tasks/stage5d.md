# STAGE 5D — test suite speed (budget: full run under 180 s, no test over 3 s)

Measured today:

```
10 UI tests = 63 s (setup 0.01 s each, 5–7 s per test)
full `-m "not live"` = over 7 minutes
```

Cause: every UI test boots `WalletTerminalApp`, which calls `init_db()` → six Alembic revisions on
a fresh SQLite file. The migrations are valuable in *one* test and pure overhead in the other 174.

Goal: the full offline suite under **180 s**, and **no single test above 3 s** — without weakening
coverage or letting tests run against a schema the migrations would never produce.

## Approach (pick per test type)

1. **Session-scoped schema template.** In `tests/conftest.py` (or `tests/unit/conftest.py`) build
   one migrated database file per session (via `alembic upgrade head`), then give each test a cheap
   copy — `shutil.copyfile` of a template file is milliseconds. Keep `WIT_DB_PATH` isolation: every
   test still gets its own file, so no cross-test leakage.
2. **Unit tests that only need models** may use `Base.metadata.create_all` on an in-memory or tmp
   SQLite instead of running Alembic.
3. **One test stays on the real migrations** — the migration-correctness tests (upgrade/downgrade
   cycle, frozen revisions) must keep using Alembic; do not shortcut those.

## Hard requirements

- Schema used by fast tests must equal the migrated schema. The reviewer's gate compares table sets
  between `create_all` and `alembic upgrade head`; a drift fails the stage.
- No test may depend on execution order; run single files and the whole suite, both green.
- No `pytest-xdist` dependency (parallelism hides shared-state bugs, we want the real time).
- Keep all existing assertions; deleting a test to hit the budget is a failure.
- No silent `except: pass`, no monkeypatching of builtins.

## Definition of Done

Run separately, paste real output including the timing line:

```
time uv run pytest -q -m "not live"                 # expect < 180s
uv run pytest -q -m "not live" --durations=15       # no entry above 3s
uv run pytest -q -m live
uv run ruff check .
```

Report in Russian: what the old and new per-test cost was, how the template is built and copied,
and how you kept the schema honest.
