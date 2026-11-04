"""Settings and configuration screen."""
from __future__ import annotations

from collections.abc import Iterable

from textual.widget import Widget
from textual.widgets import Label

from app.ui.screens.base import BaseAppScreen


class SettingsScreen(BaseAppScreen):
    """Screen for reviewing and updating application settings, database paths, and API keys."""

    def __init__(self, *args, **kwargs) -> None:
        kwargs.setdefault("id", "settings")
        super().__init__(*args, **kwargs)

    def compose_content(self) -> Iterable[Widget]:
        yield Label("⚙ Settings", classes="screen-title")
        yield Label(
            "Configure application parameters, database location, provider API keys, and backups.",
            classes="screen-desc",
        )
        yield Label(
            "Stage 8 will deliver interactive configuration editing, secret key management, and database backup/restore.",
            classes="screen-stage",
        )
