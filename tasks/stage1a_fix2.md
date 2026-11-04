# STAGE 1A — fixes, round 2 (resume after a blocked run)

The previous run was killed by a permission prompt, not by a technical problem:
it tried `mv … && rm -f /tmp/… && WIT_DB_PATH=… uv run …` in one line and the `rm` part was
denied. Everything it did before that point is on disk: B2 (address validators), H1
(session hygiene), H2 (repository whitelist) are implemented and green.

## RUN PROTOCOL (read first — this is why the last run died)

- Run **one** command per tool call. No `&&`, no `;`, no `VAR=… command` prefixes, no
  pipelines of several shell programs. If you need an env var, pass it through the tool call
  itself (the shell tool supports `cwd`, or use a two-step Python helper).
- To point the app at a scratch DB, use a tiny Python one-liner with `os.environ` set inside
  Python, or a temporary `config.yaml` copy — not `WIT_DB_PATH=… alembic …`.
- **Do not use `rm`.** Delete files with
  `uv run python -c "import os; os.remove('path')"` or overwrite them.
- Never touch anything outside this project directory and `/tmp`.

## Remaining work

### B1 (blocking). Still a fake migration

`migrations/versions/001_initial_schema.py` is still 30 lines of
`Base.metadata.create_all(op.get_bind())`. Replace it with real frozen DDL:

1. Make sure the models import cleanly (they do).
2. Generate the DDL: run autogenerate against an **empty** scratch database. A safe way is a
   short Python script in `/tmp` that sets `os.environ["WIT_DB_PATH"] = "/tmp/wit_gen.db"`,
   calls `alembic.config.Config("alembic.ini")`, and runs
   `alembic.command.revision(cfg, autogenerate=True, message="tmp")`.
3. Take the generated `op.create_table(...)` / `op.create_index(...)` block, move it into
   the existing revision `001_initial_schema` (keep that revision id and its position as the
   chain root), and write a `downgrade()` that drops the tables in reverse dependency order
   (`op.drop_table(...)` for all of them).
4. The revision must not import `app.database.models`, must not reference `Base` or
   `create_all`, and must be pure `sa.Column`/`sa.ForeignKeyConstraint`/`sa.UniqueConstraint`
   /`op.create_index` calls.
5. Delete the scratch revision and the scratch DB file.
6. Verify, with a scratch DB path: `upgrade head` → 23 tables; `downgrade base` → only
   `alembic_version` remains; second `upgrade head` → works again.

### B3 (blocking). Test isolation: module-global engine

`tests/unit/test_repository.py::test_session_init_and_context_manager` passes alone and fails
in the full suite — a hidden global (`_engine`/`_session_factory` in
`app/database/session.py`) leaks between tests.

Fix: keep `init_db(cfg)` returning the engine, but make the session layer explicit —
e.g. `session_factory(engine)` / `session_scope(factory)` used by repositories and tests, and
`get_session()` as a thin convenience that resolves the *current* factory from
`init_db()`'s result rather than a stale module global. Tests must not depend on execution
order: run the whole suite twice, and once with `-p no:cacheprovider` plus a single-file run,
to prove it.

Keep the reviewer's contract intact: `with get_session() as s:` must work after
`init_db(load_config())`.

## Definition of Done

Run each of these as a separate tool call and paste the real output:

```
uv run pytest -q
uv run python -m pytest acceptance/gate_stage1a.py -q          # 16 passed
uv run ruff check .
uv run python -c "import os; print(os.path.exists('migrations/versions/001_initial_schema.py'))"
```

Report in Russian: what the generated DDL contains (table + index counts), how you fixed the
global engine, and any remaining weakness you know about.
