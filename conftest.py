"""Pytest fixtures shared by the project's own tests.

Nothing here may inject names into Python's builtin namespace: doing so hides
missing imports in every module and once propped up a broken acceptance gate
(docs/BUGS.md, B7). Test helpers stay explicit.
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


@pytest.fixture()
def clean_env(monkeypatch):
    """Strip WIT_* overrides so tests never touch a real database."""
    for key in list(os.environ):
        if key.startswith("WIT_"):
            monkeypatch.delenv(key, raising=False)
