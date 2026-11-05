# STAGE 5B — Projects screen (catalog, contracts, participation, creation)

`ProjectManager` from 5A is done and verified. `ProjectsScreen` is still a placeholder. Wire it.

TDD. The reviewer's gates are outside this repository (intentional). `docs/` is read-only.

## Pinned contract

```python
# app/ui/screens/projects.py
class ProjectsScreen(BaseAppScreen):
    def compose_content(self) -> Iterable[Widget]      # table + filters + participation panel
    def refresh_data(self) -> None                     # (re)load catalog from DB
    @property
    def projects_text(self) -> str                     # rendered catalog as text
    @property
    def participation_text(self) -> str                # rendered participation report
    def set_status_filter(self, status: str | None) -> None
    def set_category_filter(self, category: str | None) -> None
    def show_participation(self, project_id: int) -> None
    def create_project(self, name: str, category: str | None = None,
                       status: str = "active") -> int   # returns new project id
```

Catalog row: `Name · Category · Status · Contracts · Wallets · Tasks done/total`.
Empty state: `No projects yet — press a to add one.` (no raw `**` markup).

Participation panel (after `show_participation`):
```
Project: <name> (<status>)
Wallets: <n>  Tasks: <done>/<total>  Interactions: <n>
- <wallet name> (<short address>) · source: manual|detected · interactions: <n>
```
Amounts/counters from `ProjectManager.participation_report`; no SQL in the widget layer beyond
`ProjectManager` calls.

## Behaviour pinned by the gate

1. Catalog lists projects from the DB (name + status), newest first.
2. `set_status_filter("active")` hides `completed` projects; `None` restores all.
3. `show_participation(project_id)` fills `participation_text` with the wallet name/address,
   its source (`manual`/`detected`) and counters.
4. `create_project(...)` inserts a `Project` row through `ProjectManager` and returns its id;
   duplicates raise `ValueError` (from 5A) and must surface as a notification, not a crash.
5. Empty DB → empty-state text, no traceback.
6. No silent `except: pass`.

## Definition of Done

```
uv run pytest -q -m "not live"
uv run ruff check .
```

Report in Russian: how the catalog/participation panels are refreshed (and when), how duplicate
names are handled in the UI, and the real test output.
