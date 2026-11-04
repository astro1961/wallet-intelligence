# STAGE 2B — wire wallets, groups and import into the TUI

Stage 2A is accepted: `app/core/{wallet_manager,group_manager,import_manager,network_manager}.py`,
validators, `WalletAuditLog` + migration 002, 65 green tests. Now make the UI actually use it.
No new business logic in the UI — call the core managers. `acceptance/` is read-only for you.

TDD: `App.run_test()` tests first. Also fix the three Stage 1B defects listed at the end.

## Wallets screen (`app/ui/screens/wallets.py`) — pinned contract

Layout: left `Tree` (id `#group-tree`) with the group hierarchy (roots + `Unassigned`),
right `textual.widgets.DataTable` (id `#wallet-table`) with columns
`Name | Address | Group | Tags | Networks | Updated`, and a details panel
(id `#wallet-details`) that shows the selected wallet's notes, socials and audit history.

Pinned API (the acceptance gate calls these directly):

```python
class WalletsScreen(Screen):
    history_text: str                      # plain text of the last show_history() call, >= entry per audit row
    def refresh_data(self) -> None         # re-read groups + wallets through WalletManager/GroupManager
    def set_group_filter(self, group_id: int | None) -> None   # None = all; includes subgroups
    def show_history(self, wallet_id: int) -> None             # fills #wallet-details and history_text
```

Behaviour:
- selecting a node in `#group-tree` filters the table (with subgroups);
- `/` focuses a search input that filters by name/address/tag as you type (debounced);
- `a` opens the wallet form modal; `e` edits the selected wallet; `d` archives (with confirm
  modal); `Enter` opens the details panel;
- empty state (no wallets yet) shows a human message plus `A — add your first wallet`
  (the gate greps for `пока нет` / `No wallets` / `Добавьте` in this file);
- after any create/update/archive the table and tree refresh without leaving the screen.

## Wallet form (`app/ui/screens/wallet_form.py`)

```python
class WalletFormScreen(ModalScreen):
    def save_wallet(self, data: dict) -> int   # creates via WalletManager, returns wallet id
```
Fields: address (required, EIP-55 validated with an inline error), name, group (select),
tags (comma-separated), notes, socials (kind=url per line). `Ctrl+S`/`#save-btn` saves,
`Esc` cancels. Validation errors must not crash the modal.

## Groups

Create / rename / move / delete from the tree (`n` new, `F2` rename, `m` move, `Delete`
delete → a confirm modal offering "move wallets to parent" or "to Unassigned"). Deleting a
group must never delete wallets (call `GroupManager.delete_group`).

## Import screen (`app/ui/screens/import_wallets.py`) — pinned contract

```python
class ImportScreen(Screen):
    async def set_text(self, text: str) -> None   # may be a plain sync method too
    async def do_preview(self) -> None            # builds ImportPreview, fills the preview table
    async def do_apply(self) -> None              # applies the last preview, fills the report
```
- `#import-text` (TextArea) for paste, `#file-path` (Input) + `#load-file-btn` to read a file,
  format selector `Auto/CSV/TXT/JSON`, `#default-group` select, mode `add_only`/`update`,
  buttons `#preview-btn` / `#apply-btn`;
- preview table (`textual.widgets.DataTable`) lists **every** input row with status
  `new | duplicate | error` and the error reason; counts line shows
  `N new / M duplicates / K errors`;
- `do_preview()` must not write anything to the DB (the gate checks it);
- `do_apply()` inserts only the valid, non-duplicate rows (mode `update` also updates existing);
- the report line lists added/updated/skipped/errors and sample error reasons;
- large pastes (>= 2000 rows) run in a `@work(thread=True)` Textual worker so the UI stays
  responsive — the preview button shows a spinner while it runs.

## Fix the Stage 1B defects

1. Bottom hotkey bar is clipped at 110 columns (`q Qu…`): make it fit — shorter labels at
   narrow widths (e.g. `1-9 | a | i | r | f | g | / | Esc | q`) and never truncate mid-word.
2. Screen descriptions are cut on the right instead of wrapping: use `Static` with
   `markup`/wrap enabled so text reflows at narrow widths.
3. Keep the layout usable at 60×20 (sidebar collapses to icons/short labels, panels stack).

## Tests you must write (`tests/unit/test_ui_*.py`, `App.run_test()`)

Table/tree rendering from a seeded DB, group filter incl. subgroups, search, add-wallet modal
round-trip, edit → audit history visible, archive, group create/move/delete flows, import
preview → apply (CSV and JSON), preview does not write, row errors shown, resize at 60×20,
and the hotkey bar does not clip at 110 columns (assert the rendered string length <= width).

## Definition of Done
Run each separately, paste real output:
```
uv run pytest -q
env -u WIT_DB_PATH uv run python -m pytest acceptance/gate_stage2b.py -q
env -u WIT_DB_PATH uv run python -m pytest acceptance/gate_stage1a.py acceptance/gate_stage1b.py acceptance/gate_stage2a.py -q
uv run ruff check .
```
Report in Russian: what changed, real output, how the import worker behaves on a big paste,
and any remaining rough edges for Stage 3.
