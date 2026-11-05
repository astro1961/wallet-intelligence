# STAGE 8 — Relationship Graph (PLAN Этап 7): GraphManager + GraphScreen

Model `WalletRelation` already exists and is wired (`from_wallet_id`, `to_wallet_id`,
`relation_type`, `confidence` default `"inferred"`, `notes`, `detected_at`). `networkx>=3.3` is in
dependencies. Missing: `app/core/graph_manager.py` and a working `GraphScreen` (currently a stub).

TDD. Gates are outside this repo (intentional). `docs/` is read-only for you.

## Pinned contract

```python
# app/core/graph_manager.py
class GraphManager:
    def __init__(self, session: Session) -> None

    def add_relation(self, from_wallet, to_wallet, relation_type: str,
                     confidence: str = "inferred", notes: str | None = None) -> WalletRelation
    def infer_from_transactions(self) -> int
    def neighbors(self, wallet) -> list[dict]
    def build_graph(self) -> "networkx.Graph"
    def export_json(self) -> dict
```

### Semantics (the gate asserts these exactly)

1. **`add_relation`** normalises both addresses via `normalize_evm_address`, rejects a self-loop
   (`from == to`) with `ValueError`, and is **idempotent** per `(from, to, relation_type)`: a repeat
   call returns the existing row, it does not duplicate. `confidence` is `confirmed|inferred|unknown`.
2. **`infer_from_transactions`** walks `Transaction` rows where both `from_address` and `to_address`
   belong to tracked wallets and materialises a `relation_type="transaction"`, `confidence="inferred"`
   edge for each distinct counterparty pair. Returns the number of relations created.
3. **`neighbors(wallet)`** returns one dict per adjacent wallet:
   `{"address": str, "name": str|None, "relation_type": str, "confidence": str}`.
4. **`build_graph`** returns a `networkx.Graph` (not DiGraph): nodes keyed by wallet address with a
   `name` attribute, edges carrying `relation_type` and `confidence` attributes.
5. **`export_json`** returns `{"nodes": [...], "edges": [...]}` — nodes as
   `{"id": address, "name": ...}`, edges as `{"source": ..., "target": ..., "relation_type": ...,
   "confidence": ...}`.

## Rules

- No `float` (money/weights stay `Decimal`/`int`); no UI imports in `core/`; no silent `except: pass`.
- No monkeypatching of builtins/sys; no reading the gates.
- Relations are read-mostly derived data: keep `add_relation`/`infer_from_transactions` transactional
  within the provided session (do not open your own session inside — that deadlocks SQLite).

## Tests you must write

`add_relation` dedup + self-loop + address normalisation; `build_graph` node/edge counts and edge
attributes; `neighbors`; `infer_from_transactions` from a known transfer; `export_json` validity; and
a `GraphScreen` that renders the neighbor list for the selected wallet plus component/density stats.

## Definition of Done

```
time uv run pytest -q -m "not live"       # still under 180s
uv run ruff check .
```

Report in Russian: how self-loops and duplicate edges are handled, how the graph is keyed, and the
real test output.
