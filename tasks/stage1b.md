# STAGE 1B — Textual TUI shell (navigation over all nine sections)

Stage 1A is accepted: config, 22-entity SQLite schema with a real Alembic revision,
sessions, repositories, redacting logging, `main.py` scaffold. Now build the UI shell
**only** — no CRUD screens, no providers, no sync. Every section is an empty state that
says what will appear there and in which stage.

Read `docs/spec.md` §9 (TUI layout, hotkeys, adaptivity) and `docs/PLAN.md` first.

## Non-negotiable rules

1. **TDD**: write the `App.run_test()` test first, watch it fail, then implement. The TUI
   tests belong to you (`tests/unit/test_ui_*.py`); `acceptance/` belongs to the reviewer
   and must not be modified — read it if you want, it is the contract.
2. UI must not import `httpx`/`requests`/`aiohttp` outside `app/providers/` (Stage 1B is
   offline). No network on startup.
3. Empty state ≠ fake data. Do not invent wallets, balances or projects to make the screen
   look populated. Show a clear "nothing here yet" message.
4. No blocking work on the UI thread; any future long task goes through a Textual worker.
5. Cross-platform: no `curses`, `fcntl`, `termios`, `os.fork`, no shell calls from the UI.
6. `main.py` must now launch the app (`WalletTrackerApp.run()`), keeping its CLI flags
   (`--config`, `--db`, `--log-level`, `--version`) working.

## Pinned contract (the acceptance gate depends on these names)

```
app/application.py      class WalletTrackerApp(App)
                        SCREENS: dict[str, type[Screen]] keyed by
                        "dashboard","wallets","activities","projects","defi",
                        "networks","graph","import","settings"
                        BINDINGS covering: 1-9, q, a, i, r, f, g, slash, escape,
                        up, down, enter
app/state.py            @dataclass AppState: config, engine, session_factory,
                        sync_state ("idle"|"syncing"|"paused"), last_update (datetime|None),
                        filters (dict), active_screen (str)
app/ui/screens/dashboard.py             class DashboardScreen(Screen)   id="dashboard"
app/ui/screens/wallets.py               class WalletsScreen(Screen)     id="wallets"
app/ui/screens/activities.py            class ActivitiesScreen(Screen)  id="activities"
app/ui/screens/projects.py              class ProjectsScreen(Screen)    id="projects"
app/ui/screens/defi.py                  class DeFiScreen(Screen)        id="defi"
app/ui/screens/networks.py              class NetworksScreen(Screen)    id="networks"
app/ui/screens/graph.py                 class GraphScreen(Screen)       id="graph"
app/ui/screens/import_wallets.py        class ImportScreen(Screen)      id="import"
app/ui/screens/settings.py              class SettingsScreen(Screen)    id="settings"
app/ui/widgets/wallet_tree.py           class WalletTree(Widget)
app/ui/widgets/data_table.py            class DataTable(Widget)
app/ui/widgets/status_bar.py            class StatusBar(Widget)   # fields: sync state + last update
app/ui/widgets/activity_feed.py         class ActivityFeed(Widget)
app/ui/styles/app.tcss
```

`WalletTrackerApp()` must be constructible with no arguments and must read `WIT_DB_PATH`
through `load_config()`; the first screen after startup is `dashboard`.

## Behaviour

- **Layout (§9.1):** top bar with app name + sync state + last update; left sidebar with
  the nine sections; central content area; bottom bar with the hotkeys. Sidebar entries are
  clickable (Stage 1B: `ListView` with the nine items or `Button`s).
- **Navigation:** `1`–`9` switch sections; `↑`/`↓` move the sidebar cursor; `Enter` opens
  the highlighted entry; clicking a sidebar row opens it. `Esc` returns to `dashboard`
  (later: closes dialogs). `q` quits.
- **Other hotkeys** (Stage 1B: open a modal or a non-blocking notification naming the stage
  that will implement them): `a` add wallet → Stage 2, `i` import → Stage 2, `r` refresh →
  Stage 4, `f` filters → Stage 2, `g` graph → Stage 7, `/` global search → Stage 2.
- **Status bar:** shows sync state and last update; `r` sets `last_update` to now and emits
  a notification — no background job yet.
- **Hotkeys must not fire while a text input has focus.**
- **Adaptivity (§9.3):** the layout must survive resizes down to 60×20 without raising
  (helpful: sidebar collapses or stacks vertically); test it with `pilot.resize_terminal`.
- **Empty states:** each screen shows its title, one line of what belongs there, and the
  stage that delivers it. Dashboard additionally shows real counters from the database
  (0 wallets / 0 groups / 0 projects / 0 activities / networks enabled from `config.yaml`) —
  computed with plain `SELECT COUNT(*)`, no fake data.
- **Theme:** single consistent `.tcss`, readable on dark and light terminals, no reliance
  on 256-colour-only codes.

## Tests you must write (`tests/unit/test_ui_*.py`, pytest-asyncio, `App.run_test()`)

1. app boots → `dashboard` active, no exception;
2. all nine hotkeys switch to the expected screen id;
3. sidebar navigation with `↑`/`↓`/`Enter`;
4. `q` exits, `is_running` is False afterwards;
5. each screen renders its empty state without errors at 100×30 and 60×20;
6. status bar reflects `last_update` after pressing `r`;
7. dashboard counters are 0 on a fresh database and match inserted rows when the DB is
   seeded directly through the repository (no UI CRUD yet);
8. `main.py main()` starts the app (monkeypatched `run`) and returns 0.

## Definition of Done

```
uv sync
uv run pytest -q
uv run python -m pytest acceptance/gate_stage1b.py -q
uv run ruff check .
uv run python main.py --version
```

Update `README.md`: how to run the TUI, the hotkey table, and a "current stage" note.
Report in Russian: files, real command output, decisions on ambiguity (e.g. how the sidebar
collapses), and anything left for Stage 2.
