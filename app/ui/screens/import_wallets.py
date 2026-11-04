"""Batch wallet import screen."""
from __future__ import annotations

from collections.abc import Iterable

from textual.widget import Widget
from textual.widgets import Label

from app.ui.screens.base import BaseAppScreen


class ImportScreen(BaseAppScreen):
    """Screen for importing wallet addresses in batches from CSV, TXT, and JSON files."""

    def __init__(self, *args, **kwargs) -> None:
        kwargs.setdefault("id", "import")
        super().__init__(*args, **kwargs)

    def compose_content(self) -> Iterable[Widget]:
        yield Label("📥 Import Wallets", classes="screen-title")
        yield Label(
            "Batch import wallet addresses from CSV, TXT, and JSON files with deduplication.",
            classes="screen-desc",
        )
        yield Label(
            "Stage 2 will deliver file format auto-detection, address validation, deduplication, and background workers.",
            classes="screen-stage",
        )
