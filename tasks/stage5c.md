# STAGE 5C — `show_participation` must not be overwritten by the cursor event

Reproduced by the reviewer's gate:

```python
screen.show_participation(active_project_id)   # Arbitrum Odyssey
await pilot.pause()
screen.participation_text                      # -> "Project: LayerZero (completed)"
```

Cause: `show_participation` fills `_participation_text` and updates the widget, but the table still
has its cursor on another row; the pending `DataTable.RowHighlighted` message then calls the same
renderer for the cursor row and overwrites the panel. Effect: any caller that passes an explicit
project id (a dashboard "open project" link, a search hit, a task drill-down) shows the wrong
project — the user reads another project's numbers.

## Required behaviour

`show_participation(project_id)` is an explicit command: after it returns and the event loop has
settled, the panel shows **that** project, whatever row the cursor was on before.

Pick the simplest consistent model and implement it:

- **Option A (preferred):** move the table cursor to the project's row, so cursor and panel agree.
  Use the row key (`project_id`) and `DataTable.get_row_index` / `move_cursor`; guard against a
  missing row (project filtered out) — then just render the panel without moving the cursor.
- **Option B:** render the explicit project and ignore the next highlight event exactly once
  (a flag cleared after handling). More moving parts — prefer A.

Other requirements:
- Cursor movement (arrows, mouse) must **still** update the panel (this worked, do not regress it).
- Filtering that hides the selected project must reset the panel to a neutral state, not leave stale
  numbers.
- Empty table → empty state, no traceback.
- No silent `except: pass`.

## Tests you must write

1. `show_participation(project_id_of_second_row)` → panel shows that project after a pause.
2. `table.move_cursor(0)` afterwards → panel follows the cursor again.
3. Filter that hides the selected project → panel shows a neutral placeholder, not stale data.

## Definition of Done

```
uv run pytest -q -m "not live"
uv run ruff check .
```

Report in Russian: which option you chose and why, and the real test output.
