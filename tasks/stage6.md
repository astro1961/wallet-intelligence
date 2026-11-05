# STAGE 6 — close MVP: pause/resume of sync (A7) + manual activities (A8)

Two gaps against `docs/PLAN.md` acceptance criteria:

- **A7** requires "пауза/резюм" for synchronization. `StatusBar` renders a `paused` state, but
  nothing can pause: `SyncEngine` has no pause/resume, the app has no action for it.
- **A8** requires "auto/manual раздельно". `ActivityTracker` writes `is_manual=False` hardcoded,
  there is no way to add a manual activity and no filter in the activities feed.

TDD. Gates are outside this repo (intentional). `docs/` is read-only for you.

## Pinned contract

```python
# app/core/sync_engine.py
class SyncEngine:
    def request_pause(self) -> None
    def request_resume(self) -> None
    @property
    def is_paused(self) -> bool
```
- `request_pause()` takes effect **between wallets**, never mid-wallet: the wallet currently being
  synced finishes and keeps its data.
- `sync_all()` returns one `SyncReport` per wallet. Wallets not processed because of the pause get
  `SyncReport(status="skipped")` with an explanatory `error`. It still returns the whole list, so
  callers can show "1 done, 2 skipped".
- A paused run records `SyncJob.status = "paused"` for the skipped wallets (not `"failed"` — nothing
  went wrong).
- `request_resume()` clears the flag; the next `sync_all()` processes all wallets again.

```python
# app/core/activity_tracker.py
class ActivityTracker:
    def add_manual(self, session, wallet, network, activity_type: str,
                   amount: Decimal | None = None, occurred_at: datetime | None = None,
                   note: str | None = None) -> Activity
```
- `is_manual=True`, `source="manual"`, `status="manual"`.
- `tx_hash` must be a synthetic unique key such as `manual-<uuid4 hex>` — **never** a fake chain
  hash, because it would collide with real transactions and confuse dedup.
- `occurred_at` defaults to now in UTC; `extra_data` stores the note as JSON.

```python
# app/ui/screens/activities.py
class ActivitiesScreen(BaseAppScreen):
    def set_manual_filter(self, kind: str | None) -> None   # "manual" | "auto" | None
```
- `"manual"` shows only `is_manual=True`, `"auto"` only `is_manual=False`, `None` shows both.
- Feed rows of manual activities must be visually distinguishable (a marker such as `✎` before the
  type is enough).

```python
# app/application.py
Binding("p", "toggle_pause", "Pause")   # plus check_action allowance
```
- `action_toggle_pause()` flips `SyncEngine` pause state, reflects it in `StatusBar.sync_state`
  (`"paused"` / `"idle"`) and shows a notification.

## Tests you must write

1. Pause requested from inside a provider call stops after the current wallet; counts are `ok=1`,
   `skipped=2`; `is_paused` is True; `resume` then processes all three.
2. Paused run writes `SyncJob.status="paused"` (or `"skipped"`) and syncs nothing.
3. `add_manual` sets the manual flags, keeps `Decimal` amount, and creates a `manual-…` hash.
4. Manual and auto activities coexist: one of each in the DB after a sync plus an add_manual.
5. Feed filters: `manual` / `auto` / `None`.

## Definition of Done

```
time uv run pytest -q -m "not live"       # still under 180s
uv run ruff check .
```

Report in Russian: where the pause check sits in the loop and why it is between wallets, how the
synthetic hash prevents collisions, and the real test output.
