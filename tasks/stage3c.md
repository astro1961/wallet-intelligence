# STAGE 3C — bug fixes: multi-network routing, silent failures, duplicate timestamp, TUI polish

Bug-hunting pass. Every item below is reproduced by the reviewer's gate
(`acceptance/gate_stage3c.py`, currently 5 failed / 1 passed) or by a screenshot.
Fix the cause, not the symptom. `acceptance/` and `docs/` are read-only for you.

## 1. Critical: one RPC endpoint used for every network

`app/providers/factory.py` picks the **first** EVM `rpc_url` and gives it to a single
`EvmRpcProvider`. Consequence: `get_native_balance(addr, "arbitrum")` posts `eth_getBalance` to the
Ethereum node and returns Ethereum's balance labelled as Arbitrum — wrong data, no error.

Required:
```python
class EvmRpcProvider(DataProvider):
    def __init__(self, client=None, rpc_url: str | None = None,
                 rpc_urls: dict[str, str] | None = None, max_retries: int = 2,
                 backoff_base: float = 0.5) -> None
```
- `rpc_urls` maps a network key (`"ethereum"`, `"arbitrum"`, …) to an endpoint; `rpc_url` stays the
  default for unknown keys only if you decide that is safe — better: an unknown network returns
  `ERROR` with `data=None` and no HTTP request at all.
- All methods (`get_native_balance`, `get_latest_block`, `get_transaction_details`,
  `get_token_metadata`) must use the endpoint resolved from the network argument.
- `factory.py` builds `rpc_urls` from `cfg.networks` (`name.lower() → rpc_url`), keeps
  `rpc_url` as the first entry for compatibility, and does **not** collapse the map.

## 2. Silent failures

- `app/config.py`: `WIT_REFRESH_INTERVAL="not-a-number"` is swallowed by `except ValueError: pass`.
  Log a warning naming the variable and the rejected value, keep the default, and continue.
- `app/core/import_manager.py`: several `except (AttributeError, ValueError, KeyError): pass` blocks
  hide malformed rows. Every skipped row must be logged (warning with the row number and reason) so
  the import report can show *why* a row was rejected.

Gate check `test_no_silent_except_pass` scans `app/` for `except ...: pass` — zero allowed.

## 3. Duplicate snapshot timestamp

`BalanceSnapshot` currently has both `snapshot_at` (spec) and `taken_at` (added earlier to satisfy a
gate that has since been corrected). Keep **`snapshot_at` only**:
- remove `taken_at` from `models.py`, `balance_manager.py` and their tests;
- `save_native_balance` must set `snapshot_at` in UTC (timezone-aware);
- add a real revision `004_drop_balance_snapshot_taken_at` with
  `op.add_column`-free `op.drop_column("balance_snapshots", "taken_at")` and a `downgrade` that adds
  it back as `nullable=True`;
- **`001`–`003` are frozen.** Their sha256 is pinned in `acceptance/gate_stage3.py`
  (`FROZEN_REVISIONS`). Editing them fails the gate.

## 4. TUI polish (three cosmetics from the 140-column screenshots)

1. Wallets table: on a 140-column terminal the right-most column collapses to one character.
   Give the columns sensible widths / a minimum and let the wide one flex.
2. Hotkey footer is clipped at 110 columns. Either wrap it or shorten labels so nothing is cut.
3. Long descriptions in the details panel do not wrap by words. Enable word wrapping.

Verify visually, not only in tests: `App.run_test()` → `export_screenshot()` → SVG → PNG, look at
120 and 140 columns.

## Definition of Done
Run each separately, paste real output:
```
uv run pytest -q -m "not live"
env -u WIT_DB_PATH uv run python -m pytest acceptance/gate_stage3c.py -q      # 6 passed
env -u WIT_DB_PATH uv run python -m pytest acceptance/gate_stage3.py acceptance/gate_stage3b.py -q
env -u WIT_DB_PATH uv run python -m pytest acceptance/gate_stage1a.py acceptance/gate_stage1b.py acceptance/gate_stage2a.py acceptance/gate_stage2b.py -q
uv run ruff check .
```
Plus the two screenshots (120 and 140 columns) as PNG files in `runs/shots/`.

Report in Russian: what each fix changed, the migration output for 004 (fresh DB and upgrade from
003), and the two screenshot paths.
