# STAGE 8C — fix B11: GraphScreen neighbor list never populates

Defect (from gate `gate_stage8b.py`, currently red): after `refresh_data`, `GraphScreen.selected_wallet`
ends up equal to Textual's `Select.NULL` sentinel, so the neighbor table stays empty even though the
graph stats (`Nodes`/`Edges`) render correctly.

Root cause (in `app/ui/screens/graph.py`):

1. `on_select_changed` filters only `event.value != Select.BLANK`. Textual emits a `Select.Changed`
   whose value is `Select.NULL` when the widget is initialised / `set_options()` resets it, and
   `Select.NULL != Select.BLANK` is `True`, so `select_wallet(Select.NULL)` runs.
2. `select_wallet`'s `else` branch then does `self.selected_wallet = str(wallet)` for an unresolvable
   value, clobbering the valid selection.

Fix contract (the gate asserts these):

- `on_select_changed` must ignore BOTH `Select.BLANK` and `Select.NULL` (i.e. only act on a real
  option value).
- `select_wallet` must leave `selected_wallet` unchanged when the value cannot be resolved to a
  `Wallet` (do not store `str(wallet)` of a sentinel/unresolvable value; do not blank the table to a
  fake "Selected: <garbage>" row).
- After `refresh_data` with two wallets and one relation between them, the neighbor table must show
  exactly one row (the other wallet) with `relation_type` and `confidence` populated.
- Selecting the middle wallet of a 3-wallet chain (a—b—c) must show 2 neighbor rows.

## Rules

- Do not change `app/core/graph_manager.py` — the core gate is green; this is a UI-only fix.
- No monkeypatching, no reading the gates, no UI imports in core.

## Definition of Done

```
time uv run pytest -q -m "not live"
uv run ruff check .
```

Report in Russian: which event/state path set `selected_wallet` to the sentinel, what you changed, and
the real test output.
