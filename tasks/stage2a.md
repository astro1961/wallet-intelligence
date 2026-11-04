# STAGE 2A — wallet/group services, validators, bulk import, audit trail

Stage 1A/1B are accepted: schema (22 entities), Alembic revision 001, config, TUI shell with
nine screens. Now build the **business layer** for wallets, groups and import. No UI work in
this stage — `app/ui/` stays as it is (Stage 2B will wire it up). `app/core/` must not import
`textual`, `app.ui`, or any HTTP client.

Read `docs/spec.md` §3.2, §3.3, §3.4, §8, §10 (Тестирование) and `docs/PLAN.md` first.
TDD: test first, then implementation. `acceptance/` is read-only for you.

## Pinned contract (the acceptance gate depends on these names)

### `app/utils/validators.py`
```python
def normalize_evm_address(value: str) -> str   # EIP-55 checksum; ValueError on bad checksum/short/invalid
def is_valid_evm_address(value: str) -> bool
def is_valid_solana_address(value: str) -> bool   # base58, 32-44 chars, not an EVM address
```

### `app/core/group_manager.py` — `GroupManager(session)`
```python
create_group(name, parent_id=None, description=None) -> WalletGroup
get(group_id) -> WalletGroup | None
path(group_id) -> str                     # "Farm / Farm #1 / Deep"
subtree_wallets(group_id) -> list[Wallet]  # wallets of the group AND all descendants
move_group(group_id, new_parent_id)        # ValueError on cycle / self-parent
delete_group(group_id, reassign_to=None)   # wallets AND child groups move to reassign_to or parent; nothing is lost
```
Deleting a group must never orphan or delete wallets (spec §3.3).

### `app/core/wallet_manager.py`
```python
@dataclass
class WalletFilters:
    group_id: int | None = None
    tag: str | None = None
    network_id: int | None = None
    archived: bool | None = False
    include_subgroups: bool = True
    search: str | None = None

class WalletManager(session):
    create_wallet(address, name=None, chain_type="evm", group_id=None, tags=(), notes=None,
                  socials=None) -> Wallet
    update_wallet(wallet_id, **fields) -> Wallet          # whitelist as in Stage 1A
    archive_wallet(wallet_id, archived=True) -> Wallet
    get_wallet(wallet_id) -> Wallet | None
    list_wallets(filters: WalletFilters | None = None) -> list[Wallet]
    search(query) -> list[Wallet]                          # name, address AND tag name
    history(wallet_id) -> list[WalletAuditLog]             # newest last, field/old_value/new_value
```
Every `update_wallet` / `archive_wallet` writes one `WalletAuditLog` row per changed field,
with `old_value`/`new_value` as text. `tags` — list of tag names, created on demand
(`WalletTag` + `WalletTagLink`, M2M). `socials` — dict `{kind: url}` → `WalletSocial`.

### `app/core/import_manager.py`
```python
@dataclass
class ImportRow: address; name; group; network; tags: list[str]; status; error: str | None
@dataclass
class ImportPreview: format; rows: list[ImportRow]; new_count; duplicate_count; error_count
@dataclass
class ImportReport: added; updated; skipped; errors: list[ImportRow]; rows: list[ImportRow]

class ImportManager(session):
    detect_format(text) -> "csv" | "txt" | "json"
    preview(text, fmt=None, default_group_id=None) -> ImportPreview   # MUST NOT write to the DB
    apply(preview, mode="add_only") -> ImportReport                   # "add_only" | "update"
```
Rules:
- formats: **CSV** with header `address,name,group,network,tags` (tags comma- or `;`-separated
  inside the cell), **TXT** one entry per line as `address` or `address,name` (skip blank and
  `#` lines), **JSON** list of objects `{address, name, group, network, tags}`.
- dedupe by `(normalized address, chain_type)` **inside the file and against the database**;
  duplicates count as `duplicate_count` / `skipped`.
- invalid address → row `error` with a human-readable reason (RU or EN), the batch continues.
- `mode="add_only"` never updates existing rows; `mode="update"` updates `name`/`group`/`tags`
  of existing wallets and counts them as `updated`.
- `network` is matched against `Network.name` (case-insensitive). Unknown network → row error.
  A CSV row without `network` still imports the wallet (no `WalletNetwork` link).
- groups are created on demand by name (no nesting syntax needed, but keep the name exact).
- applying the same file twice must be idempotent: second run adds 0.

### `app/core/network_manager.py`
```python
ensure_networks_from_config(session, cfg) -> int   # create missing Network rows from cfg.networks, return created count
```
Idempotent; called once from `main.py` after `init_db`.

### Model + migration
Add `WalletAuditLog` (`id`, `wallet_id` FK CASCADE, `field`, `old_value`, `new_value`,
`changed_at`) to `models.py` and a **real DDL** Alembic revision `002_*` (explicit
`op.create_table` + indexes; `downgrade()` drops it). Revision 001 stays frozen — do not edit it.
Existing dev DBs must upgrade cleanly (`alembic upgrade head`).

## Tests you must write (`tests/unit/`, TDD)
Validators (checksum matrix), group tree (deep nesting, subtree, cycle, delete-reassign),
wallet metadata (tags/notes/socials + audit trail), search/filters, import per format,
import dedupe/idempotency, import row isolation (bad row does not abort), network seeding,
migration 002 up/down.

## Definition of Done
Run each separately, paste real output:
```
uv run pytest -q
env -u WIT_DB_PATH uv run python -m pytest acceptance/gate_stage2a.py -q
env -u WIT_DB_PATH uv run python -m pytest acceptance/gate_stage1a.py acceptance/gate_stage1b.py -q
uv run ruff check .
```
Report in Russian: what changed, real output, ambiguities you resolved (e.g. tag/naming rules),
and what Stage 2B must still build.
