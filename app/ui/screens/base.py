"""Base screen class providing common layout, header, sidebar, and status bar."""
from __future__ import annotations

from collections.abc import Iterable
from contextlib import suppress

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.events import Resize
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import Label, ListItem, ListView, Static

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
SHORT_SECTION_ITEMS: list[tuple[str, str]] = [
    ("dashboard", "1. 📊"),
    ("wallets", "2. 👛"),
    ("activities", "3. ⚡"),
    ("projects", "4. 📁"),
    ("defi", "5. 🏦"),
    ("networks", "6. 🌐"),
    ("graph", "7. 🕸️"),
    ("import", "8. 📥"),
    ("settings", "9. ⚙️"),
]
SECTION_KEYS: list[str] = [k for k, _ in SECTION_ITEMS]


class HotkeyBar(Static):
    """Dynamic bottom hotkey bar that reflows and shortens labels based on width."""

    def render(self) -> str:
        w = self.size.width
        if w <= 0:
            w = self.app.size.width if self.app and self.app.size.width > 0 else 110
        avail = max(0, w - 2)
        full = "1-9 Sections │ a Add │ i Import │ r Refresh │ f Filter │ g Graph │ / Search │ Esc Back │ q Quit"
        med = "1-9 Sections │ a Add │ i Import │ r Refresh │ f Filter │ g Graph │ / Search │ Esc │ q Quit"
        short = "1-9 Nav │ a Add │ i Imp │ r Ref │ f Flt │ g Grp │ / Find │ Esc │ q Quit"
        tiny = "1-9 | a | i | r | f | g | / | Esc | q"

        if len(full) <= avail and w >= 100:
            return full
        if len(med) <= avail and w >= 90:
            return med
        if len(short) <= avail and w >= 65:
            return short
        return tiny

    def on_resize(self, event: Resize) -> None:
        self.refresh()


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

        yield HotkeyBar(id="bottom-bar")

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

        # Check initial width
        if self.app and self.app.size.width < 70:
            self._apply_narrow_mode(True)

    def on_resize(self, event: Resize) -> None:
        """Handle screen resize: toggle narrow layout at narrow widths."""
        is_narrow = event.size.width < 70
        self._apply_narrow_mode(is_narrow)
        with suppress(NoMatches, Exception):
            self.query_one("#bottom-bar", HotkeyBar).refresh()

    def _apply_narrow_mode(self, is_narrow: bool) -> None:
        """Toggle narrow class and update sidebar labels."""
        if is_narrow:
            self.add_class("narrow")
        else:
            self.remove_class("narrow")

        items = SHORT_SECTION_ITEMS if is_narrow else SECTION_ITEMS
        with suppress(NoMatches, Exception):
            for key, label in items:
                item = self.query_one(f"#nav_{key}", ListItem)
                lbl = item.query_one(Label)
                lbl.update(label)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle sidebar item click or Enter selection."""
        if event.item and event.item.id:
            target = event.item.id.removeprefix("nav_")
            if target in SECTION_KEYS and hasattr(self.app, "nav_to"):
                self.app.nav_to(target)
