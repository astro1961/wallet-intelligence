# STAGE 7A — DeFi Analyzer (PLAN Этап 6): token balances, positions, aggregation

Models already exist and are wired (`Token`, `BalanceSnapshot`, `DeFiPosition`) and the price
provider is done (`DefiLlamaProvider.get_token_price(chain, token) -> Decimal`). What is missing is
the analysis layer `app/core/defi_analyzer.py` and a working `DeFiScreen`.

TDD. Gates are outside this repo (intentional). `docs/` is read-only for you.

## Pinned contract

```python
# app/core/defi_analyzer.py
class DeFiAnalyzer:
    def __init__(self, session_factory, price_provider, config) -> None

    def snapshot_token_balance(self, wallet, network, token,
                               raw_balance: Decimal | int) -> BalanceSnapshot
    def upsert_position(self, wallet, network, protocol: str, position_type: str,
                        amount: Decimal | None = None, usd_value: Decimal | None = None,
                        certainty: str = "confirmed", details: str | None = None) -> DeFiPosition
    def list_positions(self, wallet_id: int | None = None) -> list[DeFiPosition]
    def aggregate(self, wallet_id: int | None = None) -> dict
    def value_history(self, wallet_id: int | None = None, limit: int = 100) -> list[dict]
```

### Semantics (the gate asserts these exactly)

1. **`snapshot_token_balance`** resolves the price via
   `price_provider.get_token_price(network.name, token.contract_address)`, stores `usd_price` and
   computes `usd_value = balance * price`. `balance` is the human amount = `raw_balance / 10**token.decimals`
   — apply `Decimal`, never `float`. A missing/failed price leaves `usd_price=None, usd_value=None`
   but **still** writes the snapshot (the balance is a fact even when the price is unknown). Each
   call adds a new row (this is the history source), it does not update an existing row.
2. **`upsert_position`** is idempotent per `(wallet_id, network_id, protocol, position_type)`: the
   first call creates, a later call updates `amount`/`usd_value`/`certainty`/`details`/`last_updated_at`
   and returns the same row (no duplicate).
3. **`certainty` is a closed set** — `confirmed|inferred|unknown`; anything else raises `ValueError`.
4. **`aggregate()`** returns
   ```python
   {"total_value": Decimal,                     # sum of all positions' usd_value
    "by_protocol": {protocol: Decimal},
    "by_network":   {network_name: Decimal},
    "by_certainty": {"confirmed": Decimal, "inferred": Decimal, "unknown": Decimal}}
   ```
   Confirmed value is tracked **separately** from inferred/unknown — "confirmed positions" is a
   first-class figure, not a label lost in a grand total.
5. **`value_history()`** returns one dict per `BalanceSnapshot` (oldest→newest):
   `{"snapshot_at": datetime, "balance": Decimal, "usd_value": Decimal|None}`.

## Rules

- All money arithmetic in `Decimal`; `float` is forbidden (the gate greps for `float(`).
- No UI imports in `core/`; no silent `except: pass`.
- No monkeypatching of builtins/sys; no reading the gates.
- Amounts come from `Numeric` as `Decimal` — keep them `Decimal` end to end.

## Tests you must write

Token snapshot with price and without; decimals scaling; upsert dedup + invalid certainty; aggregate
confirmed/inferred/unknown split; value history ordering; and a `DeFiScreen` that renders the
aggregate and a positions table with a certainty column.

## Definition of Done

```
time uv run pytest -q -m "not live"       # still under 180s
uv run ruff check .
```

Report in Russian: the decimals handling, how a missing price is represented, and the real test output.
