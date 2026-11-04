"""Status bar widget displaying synchronization state and last update timestamp."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from textual.reactive import reactive
from textual.widget import Widget


class StatusBar(Widget):
    """Status bar showing synchronization state and last update timestamp."""

    DEFAULT_CSS = """
    StatusBar {
        height: 1;
        width: 1fr;
        text-align: right;
        color: $text-muted;
    }
    """

    sync_state: reactive[Literal["idle", "syncing", "paused"]] = reactive("idle")
    last_update: reactive[datetime | None] = reactive(None)

    def watch_sync_state(self, new_state: str) -> None:
        self.refresh()

    def watch_last_update(self, new_val: datetime | None) -> None:
        self.refresh()

    def render(self) -> str:
        """Render sync status and last update time."""
        state = self.sync_state
        if state == "syncing":
            sync_indicator = "● Syncing..."
        elif state == "paused":
            sync_indicator = "⏸ Paused"
        else:
            sync_indicator = "● Idle"

        if self.last_update is None:
            time_display = "Never"
        else:
            time_display = self.last_update.strftime("%H:%M:%S UTC")

        return f"Sync: {sync_indicator}  │  Last update: {time_display}"
