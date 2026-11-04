"""Hierarchical wallet and group tree widget."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Label


class WalletTree(Widget):
    """Hierarchical tree navigation for wallet groups and addresses."""

    DEFAULT_CSS = """
    WalletTree {
        height: auto;
        border: solid $panel;
        padding: 1;
        margin: 1 0;
    }
    """

    def compose(self) -> ComposeResult:
        yield Label("📁 Wallet Group Hierarchy — Coming in Stage 2", id="wallet-tree-placeholder")
