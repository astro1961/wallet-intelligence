# Acceptance gates moved out of this repository

They live in `~/.hermes/workspace/wallet-intelligence-gates/` (own git repository) so that the
build agent cannot read them. See `docs/BUGS.md` (B5, B7) for why.

Run from the project root:

```bash
WIT_PROJECT_ROOT=$PWD PYTHONPATH=$PWD .venv/bin/python -m pytest \
  ~/.hermes/workspace/wallet-intelligence-gates/gate_stage*.py -q
```
