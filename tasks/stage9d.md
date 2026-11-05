# STAGE 9D — database backup & restore

The spec requires backup and restore of the SQLite database. Add a small, verifiable backup module.

TDD. Gates are outside this repo (intentional). `docs/` is read-only for you.

## Pinned contract

```python
# app/core/backup.py
def backup_database(engine, dest_path: str | Path) -> dict
def restore_database(engine, src_path: str | Path) -> None
def verify_database(engine) -> bool
def verify_backup_file(path: str | Path) -> bool
```

### Semantics (the gate asserts these exactly)

1. **`backup_database`** writes a consistent snapshot of the live SQLite database to `dest_path`
   (use the SQLite backup API / `VACUUM INTO`, not a raw `shutil.copy` of an in-use file) and returns
   `{"sha256": hex, "size_bytes": int, "table_count": int, "path": str}`. The `sha256` MUST match the
   hash of the on-disk file.
2. **`restore_database`** first validates `src_path` with `verify_backup_file`; a non-SQLite/corrupt
   file raises `ValueError` (never silently succeeds). On a valid file it replaces the live database
   so subsequent reads see the backed-up state.
3. **`verify_database(engine)`** runs `PRAGMA integrity_check` and returns `True` only on `"ok"`.
4. **`verify_backup_file(path)`** returns `True` iff the file is a readable SQLite DB whose
   `integrity_check` is `"ok"` (used by `restore_database`).

## Rules

- No `float`, no UI imports in core, no silent `except: pass`.
- No monkeypatching of builtins/sys; no reading the gates.
- Backup must not touch or read `.env` or any secret — it operates only on the database.

## Tests you must write

Backup creates a snapshot with correct sha256; restore reverts to backup state; restore rejects a
corrupt file; verify detects corruption; no-UI hygiene.

## Definition of Done

```
time uv run pytest -q -m "not live"
uv run ruff check .
```

Report in Russian: which SQLite mechanism you used for a consistent snapshot (and why), and the real
test output.
