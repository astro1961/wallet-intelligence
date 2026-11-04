"""Activity feed widget for on-chain events and transactions."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Label


class ActivityFeed(Widget):
    """Activity feed stream showing recent wallet events and transactions."""

    DEFAULT_CSS = """
    ActivityFeed {
        height: auto;
        border: solid $panel;
        padding: 1;
        margin: 1 0;
    }
    """

    def compose(self) -> ComposeResult:
        yield Label("⚡ Activity Feed — Live transaction stream coming in Stage 4", id="activity-feed-placeholder")
