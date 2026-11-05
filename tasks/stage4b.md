# STAGE 4B — Activities + Dashboard wired to real data, `s` sync hotkey

Stage 4A delivered `SyncEngine` and `ActivityTracker` (verified: 153 tests, dedup indexes in
revision 005). Both `ActivitiesScreen` and `DashboardScreen` are still placeholders that promise
"Stage 4 will deliver…". This stage delivers them.

TDD. The reviewer's gates are not in this working copy (intentional). `docs/` is read-only for you.

## Pinned contract

```python
# app/state.py
@dataclass
class AppState:
    ...
    providers: Any | None = None      # ProviderRegistry injected by the app or by tests
```

```python
# app/application.py
WalletTrackerApp.BINDINGS += Binding("s", "sync_now", "Sync")
```
- `action_sync_now()` runs the sync **off the UI thread** (Textual `@work(thread=True)` or a
  worker), so the interface stays responsive; on start set `StatusBar.sync_state = "syncing"`,
  on finish set `"idle"` and `last_update = datetime.now(UTC)`, and show a short notification with
  the report (wallets ok / failed).
- The engine is built from `self.state`: `SyncEngine(state.session_factory or session_factory(...),
  state.providers or create_provider_registry(config), config)`. If `state.providers` is `None`,
  build the default registry — never crash.
- No wallets → no sync, keep the UI alive (no traceback, status returns to `idle`).

```python
# app/ui/screens/activities.py
class ActivitiesScreen(BaseAppScreen):
    def compose_content(self) -> Iterable[Widget]      # feed + filter row + empty state
    def refresh_data(self) -> None                     # (re)load from DB
    @property
    def activity_text(self) -> str                     # rendered feed as text (used by tests)
    def set_type_filter(self, activity_type: str | None) -> None
    def set_network_filter(self, network: str | None) -> None
    def set_project_filter(self, project_id: int | None) -> None
```
Feed row format: `HH:MM DD.MM · <type> · <wallet name> · <network> · <amount> · <project|—> ·
<short tx hash>`. Newest first, limit 200 rows. Empty state:
"No activities yet — press **s** to sync your wallets."

```python
# app/ui/screens/dashboard.py
class DashboardScreen(BaseAppScreen):
    def refresh_data(self) -> None
    @property
    def dashboard_text(self) -> str
```
Dashboard must show: wallets count, activities count, projects count, total tracked value line
(sum of latest `BalanceSnapshot` per wallet, formatted), the last 5 activities, and the last sync
status (`SyncJob` newest row: type + status + time).

## Rules

- Amounts from `Numeric` come back as `Decimal` — format for display, never `float()` them.
- Timestamps are UTC; render them as-is or convert for display, but never naive-local assumptions.
- Do not put SQL in widget callbacks: reuse `session_scope`, keep queries in the screen methods.
- No silent `except: pass` (gate 3C scans for it).
- No network calls in UI tests: providers are injected.

## Tests you must write (in `tests/unit/`)

1. Activities feed loads rows produced by `SyncEngine` and shows type + short hash.
2. `set_type_filter("receive")` narrows the feed; `None` restores it.
3. Empty DB → empty-state text, no traceback.
4. Dashboard counts match seeded wallets/activities/projects.
5. `s` with a fake provider: `SyncJob` created, status bar returns to idle, `last_update` set.
6. `s` with a failing provider: `SyncJob.status == "failed"`, UI alive.

## Definition of Done

```
uv run pytest -q -m "not live"
uv run ruff check .
```

Report in Russian: how the sync runs off the UI thread, the feed/filter implementation, and the
real test output.
