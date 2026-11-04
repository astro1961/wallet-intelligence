"""Wallets screen for managing crypto addresses and groups."""
from __future__ import annotations

from collections.abc import Iterable

from textual.widget import Widget
from textual.widgets import Label

from app.ui.screens.base import BaseAppScreen
from app.ui.widgets.wallet_tree import WalletTree


class WalletsScreen(BaseAppScreen):
    """Screen for managing wallet addresses, hierarchical groups, and metadata."""

    def __init__(self, *args, **kwargs) -> None:
        kwargs.setdefault("id", "wallets")
        super().__init__(*args, **kwargs)

    def compose_content(self) -> Iterable[Widget]:
        yield Label("👛 Wallets", classes="screen-title")
        yield Label(
            "Manage cryptocurrency addresses, hierarchical groups, metadata, notes, and tags.",
            classes="screen-desc",
        )
        yield Label(
            "Stage 2 will deliver wallet & group CRUD, nested hierarchy, tags, notes, and balance inspection.",
            classes="screen-stage",
        )
        yield WalletTree()
