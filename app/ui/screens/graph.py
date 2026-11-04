"""Relationship graph screen for visualizing wallet interactions."""
from __future__ import annotations

from collections.abc import Iterable

from textual.widget import Widget
from textual.widgets import Label

from app.ui.screens.base import BaseAppScreen


class GraphScreen(BaseAppScreen):
    """Screen for visualizing relationships between wallets, projects, and entities."""

    def __init__(self, *args, **kwargs) -> None:
        kwargs.setdefault("id", "graph")
        super().__init__(*args, **kwargs)

    def compose_content(self) -> Iterable[Widget]:
        yield Label("🕸 Relationship Graph", classes="screen-title")
        yield Label(
            "Visualize and explore on-chain relationships, interactions, and entity clusters.",
            classes="screen-desc",
        )
        yield Label(
            "Stage 7 will deliver NetworkX graph analysis, neighbor lists, confidence levels, and exports.",
            classes="screen-stage",
        )
