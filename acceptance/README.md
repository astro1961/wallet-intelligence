# Acceptance gates

Written and owned by the reviewer (Hermes). The build agent must never edit them, and the
reviewer's gates are the only source of truth for "a stage is done".

Because a gate that the agent can read will be optimised against (two such cases happened:
a `builtins.print` hook that rewrote gate output, and `builtins.json = json` in `conftest.py`
that propped up a gate missing `import json`), gates are stashed while the agent works:

```bash
cd ~/Projects/wallet-intelligence
mv acceptance ~/Projects/.wit-gates-stash      # before starting the agent
agy ... -p "read tasks/stageN.md and implement it"
mv ~/Projects/.wit-gates-stash acceptance      # immediately after
```

Then the reviewer runs, from the project root:

```bash
env -u WIT_DB_PATH .venv/bin/python -m pytest acceptance/gate_stage1a.py \
  acceptance/gate_stage1b.py acceptance/gate_stage2a.py acceptance/gate_stage2b.py \
  acceptance/gate_stage3.py acceptance/gate_stage3b.py acceptance/gate_stage3c.py -q
```

Rules:
- applied Alembic revisions are pinned by sha256 inside the gates;
- gates never trust the agent's `status` field, only artifacts and their own assertions;
- `gate_stage3b.py::test_no_gate_gaming_in_app_layer` scans `app/` **and** root `*.py` for
  builtins patching and harness detection.
