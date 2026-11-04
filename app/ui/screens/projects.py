"""Projects and testnets catalog screen."""
from __future__ import annotations

from collections.abc import Iterable

from textual.widget import Widget
from textual.widgets import Label, Static

from app.ui.screens.base import BaseAppScreen
from app.ui.widgets.data_table import DataTable


class ProjectsScreen(BaseAppScreen):
    """Screen for tracking crypto projects, testnet participations, and checklists."""

    def __init__(self, *args, **kwargs) -> None:
        kwargs.setdefault("id", "projects")
        super().__init__(*args, **kwargs)

    def compose_content(self) -> Iterable[Widget]:
        yield Label("🚀 Projects & Testnets", classes="screen-title")
        yield Static(
            "Directory of crypto projects, testnets, smart contracts, and task checklists.",
            classes="screen-desc",
        )
        yield Static(
            "Stage 5 will deliver project catalog, contract registry, participation reports, and tasks.",
            classes="screen-stage",
        )
        yield DataTable()
