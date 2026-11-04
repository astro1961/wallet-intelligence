"""Networks screen for managing blockchain networks and RPC endpoints."""
from __future__ import annotations

from collections.abc import Iterable

from textual.widget import Widget
from textual.widgets import Label, Static

from app.ui.screens.base import BaseAppScreen
from app.ui.widgets.data_table import DataTable


class NetworksScreen(BaseAppScreen):
    """Screen for managing EVM and non-EVM blockchain networks and RPC endpoints."""

    def __init__(self, *args, **kwargs) -> None:
        kwargs.setdefault("id", "networks")
        super().__init__(*args, **kwargs)

    def compose_content(self) -> Iterable[Widget]:
        yield Label("🌐 Networks", classes="screen-title")
        yield Static(
            "Manage supported EVM and Solana blockchain networks, RPC endpoints, and explorers.",
            classes="screen-desc",
        )
        yield Static(
            "Stage 3 will deliver EVM JSON-RPC provider adapters; Stage 8 will deliver Solana and custom networks.",
            classes="screen-stage",
        )
        yield DataTable()
