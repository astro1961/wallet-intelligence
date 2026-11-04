"""Base screen class providing common layout, header, sidebar, and status bar."""
from __future__ import annotations

from collections.abc import Iterable
from contextlib import suppress

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import Label, ListItem, ListView

from app.ui.widgets.status_bar import StatusBar

SECTION_ITEMS: list[tuple[str, str]] = [
    ("dashboard", "1. Dashboard"),
    ("wallets", "2. Wallets"),
    ("activities", "3. Activities"),
    ("projects", "4. Projects"),
    ("defi", "5. DeFi"),
    ("networks", "6. Networks"),
    ("graph", "7. Graph"),
    ("import", "8. Import"),
    ("settings", "9. Settings"),
]
SECTION_KEYS: list[str] = [k for k, _ in SECTION_ITEMS]


class BaseAppScreen(Screen):
    """Base screen containing standard top bar, sidebar navigation, and bottom bar."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)

    def compose(self) -> ComposeResult:
        """Compose top bar, sidebar, scrollable content area, and bottom bar."""
        with Horizontal(id="top-bar"):
            yield Label("Wallet Intelligence Tracker", id="app-title")
            yield StatusBar(id="status-bar")

        with Horizontal(id="main-body"):
            with Vertical(id="sidebar"):
                yield Label("SECTIONS", id="sidebar-header")
                yield ListView(
                    *[
                        ListItem(Label(label), id=f"nav_{key}")
                        for key, label in SECTION_ITEMS
                    ],
                    id="sidebar_list",
                )

            with VerticalScroll(id="content-area"):
                yield from self.compose_content()

        yield Label(
            "1-9 Sections  │  a Add  │  i Import  │  r Refresh  │  f Filter  │  g Graph  │  / Search  │  Esc Home  │  q Quit",
            id="bottom-bar",
        )

    def compose_content(self) -> Iterable[Widget]:
        """Override in subclasses to provide screen-specific content."""
        return []

    def on_mount(self) -> None:
        """Update sidebar selection and sync status bar on mount."""
        with suppress(NoMatches, Exception):
            lv = self.query_one("#sidebar_list", ListView)
            if self.id in SECTION_KEYS:
                lv.index = SECTION_KEYS.index(self.id)
            lv.focus()

        # Sync status bar with app state
        if hasattr(self.app, "state") and self.app.state:
            for sb in self.query(StatusBar):
                sb.sync_state = self.app.state.sync_state
                sb.last_update = self.app.state.last_update

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle sidebar item click or Enter selection."""
        if event.item and event.item.id:
            target = event.item.id.removeprefix("nav_")
            if target in SECTION_KEYS and hasattr(self.app, "nav_to"):
                self.app.nav_to(target)
