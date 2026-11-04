# STAGE 3D — details panel must follow the table cursor (bug B6)

Reproduced by the reviewer:

1. Open Wallets, seed two wallets (`Alpha`, `Beta`).
2. `table.move_cursor(row=1)` — the highlight moves to `Beta`.
3. The details panel still shows the previous wallet (or the placeholder
   "Select a wallet and press Enter to view details and audit history.").

Consequence: the screenshot shows row `Alpha` highlighted while the panel displays another wallet —
the UI contradicts itself, and a user reading the panel attributes the wrong notes/address to the
highlighted row.

## Required behaviour

- Moving the cursor (arrow keys, mouse click, programmatic `move_cursor`) updates `#wallet-details`
  for the newly highlighted row **without requiring Enter**.
- Enter keeps its current meaning: load the full audit history into the details panel
  (`history_text` must stay filled — an existing test depends on it).
- Empty table (no wallets) must not crash and must keep the placeholder text.
- Rapid cursor movement must not leak sessions or block the UI: reuse the existing
  `session_scope` pattern, keep the query small (one wallet + group), debounce if you find it
  necessary.

## Implementation notes

- Add an `on_data_table_row_highlighted` handler next to the existing
  `on_data_table_row_selected` in `app/ui/screens/wallets.py`.
- `DataTable.RowHighlighted.row_key` gives the wallet id; `row_index` may be `None` on an empty
  table — guard it.
- After `_refresh_wallet_table()` re-populates rows, keep the panel consistent with the cursor
  position instead of a stale `selected_wallet_id`.
- Do **not** swallow exceptions silently; log with a reason (the gate for stage 3C enforces
  "no `except: pass`").

## Tests you must write (TDD, in `tests/unit/`)

1. `move_cursor(0)` → panel contains the first wallet's name/address.
2. `move_cursor(1)` → panel contains the second wallet's name/address and no longer the first.
3. `press("enter")` on a row → `history_text` is filled (regression guard).
4. Empty table → panel keeps the placeholder, no traceback.

## Definition of Done

Run each separately, paste real output:

```
uv run pytest -q -m "not live"
uv run ruff check .
```

The reviewer runs the acceptance gates separately — they are not in this working copy while you
work, which is intentional.

Report in Russian: the handler you added, why the panel could go stale before, and the real test
output.
