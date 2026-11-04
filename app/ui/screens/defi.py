"""DeFi positions and token analytics screen."""
from __future__ import annotations

from collections.abc import Iterable

from textual.widget import Widget
from textual.widgets import Label

from app.ui.screens.base import BaseAppScreen
from app.ui.widgets.data_table import DataTable


class DeFiScreen(BaseAppScreen):
    """Screen for analyzing confirmed and inferred DeFi protocol positions and token balances."""

    def __init__(self, *args, **kwargs) -> None:
        kwargs.setdefault("id", "defi")
        super().__init__(*args, **kwargs)

    def compose_content(self) -> Iterable[Widget]:
        yield Label("🏦 DeFi Positions", classes="screen-title")
        yield Label(
            "Analyze confirmed and inferred DeFi positions, token balances, and protocol metrics.",
            classes="screen-desc",
        )
        yield Label(
            "Stage 6 will deliver token balances, DeFiLlama protocol integrations, and position breakdowns.",
            classes="screen-stage",
        )
        yield DataTable()
