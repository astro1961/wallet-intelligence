# STAGE 5A — ProjectManager (catalog, per-network contracts, participation report)

Spec: `docs/spec.md` §7 (projects) and §11 Этап 5. Core only — no UI in this stage.

Models already exist: `Project(name, description, category, status, official_url, notes)`,
`ProjectContract(project_id, network_id, contract_address, name, abi)`,
`ProjectWallet(project_id, wallet_id, source, interactions_count, first/last_interaction_at)`,
`ProjectTask(project_id, wallet_id, title, description, status, due_date, completed_at)`.

TDD. The reviewer's gates are not in this working copy. `docs/` is read-only.

## Pinned contract

```python
# app/core/project_manager.py
class ProjectManager:
    def __init__(self, session) -> None

    # catalog
    def create_project(self, name: str, description: str | None = None,
                       category: str | None = None, status: str = "active",
                       official_url: str | None = None, notes: str | None = None) -> Project
    def update_project(self, project_id: int, **fields) -> Project        # explicit whitelist
    def get(self, project_id: int) -> Project | None
    def list_projects(self, status: str | None = None) -> list[Project]
    def count(self) -> int
    def delete_project(self, project_id: int) -> None                      # cascades contracts/wallets/tasks

    # contracts
    def add_contract(self, project_id: int, network: str, contract_address: str,
                     name: str | None = None) -> ProjectContract
    def list_contracts(self, project_id: int) -> list[ProjectContract]
    def find_project_by_contract(self, address: str, network: str) -> Project | None

    # participation
    def link_wallet(self, project_id: int, wallet_id: int, source: str = "manual") -> ProjectWallet
    def detected_wallets(self, project_id: int) -> list[ProjectWallet]
    def add_task(self, project_id: int, title: str, wallet_id: int | None = None,
                 status: str = "todo") -> ProjectTask
    def complete_task(self, task_id: int) -> ProjectTask
    def participation_report(self, project_id: int) -> dict
```

## Behaviour pinned by the gate

1. **Name uniqueness is case-insensitive.** `create_project("arbitrum odyssey")` after
   `"Arbitrum Odyssey"` raises `ValueError`. `count()` reflects inserts/deletes.
2. **Contracts are per network.** The same address on `ethereum` and `polygon` are two rows;
   `find_project_by_contract(addr, "polygon")` returns `None` when only `ethereum` is registered.
3. **Input validation.** `add_contract` normalizes and validates the address with
   `app.utils.validators.normalize_evm_address` (`ValueError` for bad input) and resolves the
   network name through `networks` (`LookupError`/`ValueError` for an unknown chain). No silent
   inserts of garbage.
4. **Participation report** returns:
   ```python
   {"wallets": [{"wallet_id": int, "source": "detected"|"manual"|"task",
                 "interactions": int}],
    "tasks_total": int, "tasks_done": int, "interactions": int}
   ```
   - `detected` comes from synced `activities` whose `project_id` was set by the sync engine
     (Stage 4A did this for `contract_call` activities).
   - `link_wallet` marks a wallet as `manual` **without duplicating** a detected row: the row is
     upgraded (source becomes `manual` only if it was not already `detected`; detected wins).
   - `interactions` per wallet = count of activities for that wallet and project.
5. **`update_project` uses an explicit whitelist** (`name, description, category, status,
   official_url, notes`) and rejects unknown fields instead of `hasattr` checks.
6. **No UI imports, no `except: pass`.**

## Tests you must write

CRUD + duplicate name, per-network contracts + lookup miss, invalid address/unknown network,
detected-vs-manual participation, task counters, cascade delete, whitelist rejection.

## Definition of Done

```
uv run pytest -q -m "not live"
uv run ruff check .
```

Report in Russian: how participation is derived (link to Activities), the whitelist approach, and
the real test output.
