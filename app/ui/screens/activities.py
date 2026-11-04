"""Activities screen for inspecting transactions and events."""
from __future__ import annotations

from collections.abc import Iterable

from textual.widget import Widget
from textual.widgets import Label, Static

from app.ui.screens.base import BaseAppScreen
from app.ui.widgets.activity_feed import ActivityFeed


class ActivitiesScreen(BaseAppScreen):
    """Screen for inspecting on-chain events, transaction histories, and user activities."""

    def __init__(self, *args, **kwargs) -> None:
        kwargs.setdefault("id", "activities")
        super().__init__(*args, **kwargs)

    def compose_content(self) -> Iterable[Widget]:
        yield Label("⚡ Activities", classes="screen-title")
        yield Static(
            "Track on-chain events, transactions, and manual activities across monitored wallets.",
            classes="screen-desc",
        )
        yield Static(
            "Stage 4 will deliver automatic synchronization, event deduplication, and activity filters.",
            classes="screen-stage",
        )
        yield ActivityFeed()
