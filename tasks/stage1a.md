# STAGE 1A — project skeleton, configuration, SQLite schema, migrations

You are the build agent for **Wallet Intelligence Tracker**. Project root: the current
working directory (`~/Projects/wallet-intelligence`). Read `docs/spec.md` (Russian
specification) and `docs/PLAN.md` (stage breakdown) before writing code.

Work **only** on Stage 1A. Do not build the Textual UI, providers, sync engine, or any
API integration — those are later stages.

## Non-negotiable rules

1. **TDD.** For each unit: write the failing pytest test first, then the minimal
   implementation, then refactor. Tests live in `tests/unit/`. No test may touch the
   network or a real API.
2. **Do NOT modify `acceptance/`** — that directory is the independent acceptance gate
   owned by the reviewer. Reading it is allowed; editing it fails the stage.
3. Do not create fake/placeholder data in production code paths. No secrets in code,
   `config.yaml`, tests, or git.
4. Keep UI, business logic, providers and storage in separate modules (spec §7).
5. Python 3.12+; use `uv` for the environment (`uv venv`, `uv sync`). System python is
   3.14 — if a pinned dependency is incompatible, pin an interpreter with
   `uv python pin 3.12` rather than dropping a dependency.
6. No new dependencies beyond the stack in spec §6 (you may add `pytest`, `ruff`,
   `pytest-asyncio` to the dev group; `respx` only if you need it for later stages —
   prefer `httpx.MockTransport`).

## Deliverables

### 1. Layout (spec §7)
Create the directories/packages named in §7 with `__init__.py` files. Stage 1A fills:

```
main.py, pyproject.toml, README.md, .env.example, .gitignore, config.yaml, alembic.ini
app/__init__.py
app/config.py
app/database/{__init__,models,session,repository}.py
app/utils/{__init__,logging,formatting}.py
migrations/env.py, migrations/script.py.mako, migrations/versions/<rev>_initial_schema.py
tests/unit/…, tests/integration/…, tests/fixtures/…
data/, logs/  (git-ignored, created at runtime)
```

UI modules (`app/ui/...`, `app/application.py`, `app/state.py`) are Stage 1B — leave them
out, but do not make their future addition awkward.

### 2. `pyproject.toml`
Project metadata, `requires-python = ">=3.12"`, runtime deps exactly the §6 stack
(textual, rich, sqlalchemy, alembic, pydantic, httpx, networkx, pyyaml, python-dotenv),
dev group with pytest + ruff + pytest-asyncio. Console entry point
`wallet-intelligence = "main:main"`. `uv sync` must succeed and produce `uv.lock`.

### 3. `app/config.py` — pinned contract
```python
class AppSection(BaseModel):      name: str; refresh_interval_seconds: int = 300; timezone: str = "UTC"
class DatabaseSection(BaseModel): path: str = "data/wallet_tracker.db"
class ProviderSection(BaseModel): enabled: bool = True; api_key_env: str | None = None; base_url: str | None = None
class NetworkConfig(BaseModel):   name: str; type: str = "evm"; chain_id: int | None = None
                                  enabled: bool = True; rpc_url: str | None = None
                                  explorer_url: str | None = None
class AppConfig(BaseModel):
    app: AppSection; database: DatabaseSection
    providers: dict[str, ProviderSection] = {}
    networks: list[NetworkConfig] = []
    extra: dict = {}  # unknown top-level keys allowed

def load_config(path: str | Path | None = None) -> AppConfig: ...
```
- Default path `config.yaml` in the project root, overridable by env `WIT_CONFIG`.
- `load_config` loads `.env` (python-dotenv) and applies env overrides:
  `WIT_DB_PATH` → `database.path`, `WIT_REFRESH_INTERVAL` → `app.refresh_interval_seconds`.
- Unknown keys must not crash validation; providers may be declared without a key.
- Never read or log the value of `*_API_KEY`; only the env var *name*.

### 4. `config.yaml` (spec §4.4)
`app` (name "Wallet Intelligence Tracker", refresh_interval_seconds 300, timezone UTC),
`database.path: data/wallet_tracker.db`, providers etherscan/blockscout/defillama with
`api_key_env` names (no literal keys), networks: Ethereum (1), Arbitrum (42161),
Optimism (10), Base (8453), BNB Chain (56), Polygon (137), Sepolia (11155111) with
`type: evm`, `enabled: true`, public RPC + explorer URLs.

### 5. `app/database/models.py` — pinned entity set
SQLAlchemy 2.0 declarative (`Mapped[...]`/`mapped_column`) classes, **all 22**:

`Wallet, WalletGroup, WalletTag, WalletTagLink, WalletSocial, WalletRelation,
WalletNetwork, Network, RpcEndpoint, Project, ProjectContract, ProjectWallet,
ProjectTask, Activity, Transaction, Token, BalanceSnapshot, DeFiPosition, Provider,
SyncJob, SyncCursor, Note`

Modeling requirements:
- `Wallet`: `address` (normalized lowercase for EVM, original kept in `address_raw`),
  `chain_type` (`evm`/`solana`, default `evm`), `name`, `notes` (text), `group_id`
  FK→`wallet_groups.id` `ON DELETE SET NULL`, `archived` bool, `created_at`,
  `first_activity_at`, `last_activity_at`, timestamps timezone-aware UTC.
  `UniqueConstraint(address, chain_type)`.
- `WalletGroup`: self-referential `parent_id` FK `ON DELETE SET NULL`, name,
  description, `path` or nested-set helper is optional — but cycles must be impossible;
  groups of any depth.
- `WalletNetwork`: association `(wallet_id, network_id)` with `UniqueConstraint`,
  monitoring status, last_sync_at.
- `Network`: unique `(name)`, `(chain_type, chain_id)`; fields per spec §3.8.
- `RpcEndpoint`: `network_id`, `url`, `priority`, `is_primary`, `is_backup`.
- `Activity` / `Transaction`: `source` enum-ish (`chain|provider|manual|inferred`),
  stable dedupe key `(network_id, tx_hash, log_index)` unique for chain-derived rows;
  `is_manual` flag; `occurred_at` UTC.
- `ProjectWallet.source`: one of `detected|manual|task`.
- `DeFiPosition`: `certainty` one of `confirmed|inferred|unknown`; confirmed positions
  must be queryable separately.
- Financial columns: `Numeric(38, 18)` or integer raw units + `decimals` — **never
  `Float`**.
- Foreign keys declared with `ondelete` behaviour; SQLite `PRAGMA foreign_keys=ON` must
  be enabled on every connection (event listener).
- Indexes on: `wallets.address`, `wallets.group_id`, `transactions.tx_hash`,
  activity `occurred_at`, `project_contracts.contract_address`,
  `wallet_networks.network_id`.
- Duplicate protection via unique constraints, not application checks alone.

### 6. `app/database/session.py`
`create_engine_for(cfg)`, `init_db(cfg)` (idempotent: creates `data/` dir, applies the
schema: prefer `alembic upgrade head` programmatically with fallback to
`Base.metadata.create_all` when no revision is present), and a **context manager**
`get_session()` that commits on success, rolls back on exception, closes always.
Engine setup enables SQLite FK enforcement and `check_same_thread=False` where needed.

### 7. `app/database/repository.py`
Thin repository layer, no UI logic: at minimum `WalletRepository`
(`add`, `get`, `list(filter)`, `update`, `archive`) and `GroupRepository`
(`create`, `rename`, `move`, `delete_reassigning_wallets`). Tested in `tests/unit/`.

### 8. Alembic
`alembic.ini` + `migrations/env.py` that resolves the DB URL from `load_config()`
(honouring `WIT_DB_PATH`) instead of a hard-coded URL, `target_metadata = Base.metadata`,
and one initial revision creating the whole schema. `alembic upgrade head` must work on
an empty database and be idempotent on a second call.

### 9. `app/utils/logging.py`
`setup_logging(log_dir: str | Path = "logs", level: str = "INFO")` → rotating file
handler `logs/app.log` + optional console, and a redaction filter that masks values of
`api_key`, `token`, `secret`, `password`, `private_key`, `authorization` (both
`KEY=value` and `"key": "value"` forms) before they reach any handler.

### 10. `.env.example`, `.gitignore`, `README.md`
- `.env.example`: `ETHERSCAN_API_KEY=`, `BLOCKSCOUT_API_KEY=`, `WIT_DB_PATH=`,
  `WIT_CONFIG=`, `LOG_LEVEL=INFO` (empty values only).
- `.gitignore`: `.env`, `.venv/`, `data/`, `logs/`, `__pycache__/`, `*.pyc`, `.pytest_cache/`.
- `README.md`: purpose, security/read-only statement, install (`uv sync`), run
  (`uv run python main.py`), tests (`uv run pytest -q`), migrations, config/env
  description, stage status table. Russian is fine; keep commands exact.

### 11. `main.py`
Argument parsing scaffold (`--config`, `--db`, `--log-level`, `--version`), setup
logging + `init_db`, then import `app.application` lazily: if the Textual app module is
not implemented yet, print a clear message and exit 0. No TUI code in Stage 1A.

### 12. Tests you must write (TDD, `tests/unit/`)
At least: config loading + env override, model constraints (unique wallet
address+chain_type, unique wallet_network, FK rejection), repository CRUD for wallets and
groups (including `delete_reassigning_wallets`), migration from scratch against a temp DB,
logging redaction. Integration test dir may hold the migration test.

## Definition of Done

Run these yourself and paste real output in the final report:

```
uv sync
uv run pytest -q
uv run python -m pytest acceptance/gate_stage1a.py -q
uv run alembic upgrade head   # with WIT_DB_PATH pointing at a throwaway file
```

You are done when `acceptance/gate_stage1a.py` is fully green **without** touching that
file, the project's own tests are green, and the four frozen UI-stage entry points
(`app/application.py`, `app/state.py`, `app/ui/`) are not created yet.

Final report (in Russian): files created with byte sizes, commands run with real output,
what the gate reported, decisions made where the spec was ambiguous, and what remains for
Stage 1B.
