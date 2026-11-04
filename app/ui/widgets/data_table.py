"""Data table widget for tabular listings."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Label


class DataTable(Widget):
    """Reusable data table widget for tabular data display."""

    DEFAULT_CSS = """
    DataTable {
        height: auto;
        border: solid $panel;
        padding: 1;
        margin: 1 0;
    }
    """

    def compose(self) -> ComposeResult:
        yield Label("📊 Data Table — Column sorting & pagination coming in Stage 2+", id="data-table-placeholder")
