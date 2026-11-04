"""Main Textual application shell for Wallet Intelligence Tracker."""
from __future__ import annotations

from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar

from textual.app import App, ScreenStackError
from textual.binding import Binding
from textual.css.query import DOMQuery, NoMatches
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import Input, ListView, TextArea

from app.config import AppConfig, load_config
from app.database.session import init_db, session_factory
from app.state import AppState
from app.ui.screens.activities import ActivitiesScreen
from app.ui.screens.dashboard import DashboardScreen
from app.ui.screens.defi import DeFiScreen
from app.ui.screens.graph import GraphScreen
from app.ui.screens.import_wallets import ImportScreen
from app.ui.screens.networks import NetworksScreen
from app.ui.screens.projects import ProjectsScreen
from app.ui.screens.settings import SettingsScreen
from app.ui.screens.wallets import WalletsScreen
from app.ui.widgets.status_bar import StatusBar

CSS_FILE = Path(__file__).parent / "ui" / "styles" / "app.tcss"


class WalletTrackerApp(App):
    """Textual terminal user interface shell for Wallet Intelligence Tracker."""

    CSS_PATH = CSS_FILE

    SCREENS: ClassVar[dict[str, type[Screen]]] = {
        "dashboard": DashboardScreen,
        "wallets": WalletsScreen,
        "activities": ActivitiesScreen,
        "projects": ProjectsScreen,
        "defi": DeFiScreen,
        "networks": NetworksScreen,
        "graph": GraphScreen,
        "import": ImportScreen,
        "settings": SettingsScreen,
    }

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("1", "nav_to('dashboard')", "Dashboard"),
        Binding("2", "nav_to('wallets')", "Wallets"),
        Binding("3", "nav_to('activities')", "Activities"),
        Binding("4", "nav_to('projects')", "Projects"),
        Binding("5", "nav_to('defi')", "DeFi"),
        Binding("6", "nav_to('networks')", "Networks"),
        Binding("7", "nav_to('graph')", "Graph"),
        Binding("8", "nav_to('import')", "Import"),
        Binding("9", "nav_to('settings')", "Settings"),
        Binding("q", "quit_app", "Quit"),
        Binding("a", "add_wallet", "Add Wallet"),
        Binding("i", "import_wallets", "Import"),
        Binding("r", "refresh", "Refresh"),
        Binding("f", "filters", "Filters"),
        Binding("g", "graph", "Graph"),
        Binding("slash", "search", "Search", key_display="/"),
        Binding("escape", "escape", "Home / Back"),
        Binding("up", "sidebar_up", "Up", show=False),
        Binding("down", "sidebar_down", "Down", show=False),
        Binding("enter", "sidebar_enter", "Select", show=False),
    ]

    def __init__(
        self,
        config: AppConfig | None = None,
        state: AppState | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        if config is None:
            config = load_config()
        if state is None:
            engine = init_db(config)
            session_fact = session_factory(engine)
            state = AppState(
                config=config,
                engine=engine,
                session_factory=session_fact,
                sync_state="idle",
                last_update=None,
                filters={},
                active_screen="dashboard",
            )
        self.config = config
        self.state = state

    def on_mount(self) -> None:
        """Mount initial dashboard screen on startup."""
        self.push_screen("dashboard")

    def query(self, *args: Any, **kwargs: Any) -> DOMQuery:
        """Query widgets in the active screen when available, falling back to app root."""
        with suppress(ScreenStackError, NoMatches, Exception):
            res = self.screen.query(*args, **kwargs)
            if res:
                return res
        return super().query(*args, **kwargs)

    def query_one(self, *args: Any, **kwargs: Any) -> Widget:
        """Query a single widget in the active screen when available, falling back to app root."""
        with suppress(ScreenStackError, NoMatches, Exception):
            return self.screen.query_one(*args, **kwargs)
        return super().query_one(*args, **kwargs)

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        """Prevent app hotkeys from firing when a text input widget is focused."""
        if isinstance(self.focused, (Input, TextArea)) and action in (
            "nav_to",
            "quit_app",
            "add_wallet",
            "action_add_wallet",
            "import_wallets",
            "action_import",
            "refresh",
            "action_refresh",
            "filters",
            "action_filters",
            "graph",
            "action_graph",
            "search",
            "action_search",
            "escape",
            "action_escape",
            "sidebar_up",
            "sidebar_down",
            "sidebar_enter",
        ):
            return False
        return super().check_action(action, parameters)

    def action_nav_to(self, screen_id: str) -> None:
        """Action handler for navigation bindings."""
        self.nav_to(screen_id)

    def nav_to(self, screen_id: str) -> None:
        """Switch active screen and update runtime state."""
        if screen_id in self.SCREENS:
            self.state.active_screen = screen_id
            if self.screen.id != screen_id:
                self.switch_screen(screen_id)

    def action_quit_app(self) -> None:
        """Exit the application."""
        self.exit(0)

    def action_add_wallet(self) -> None:
        """Notify that Add Wallet is scheduled for Stage 2."""
        self.notify("Add Wallet modal dialog will be implemented in Stage 2", title="Stage 2 — Add Wallet")

    def action_import_wallets(self) -> None:
        """Notify that Import Wallets wizard is scheduled for Stage 2."""
        self.notify("Import Wallets parser & wizard will be implemented in Stage 2", title="Stage 2 — Import")

    action_action_import = action_import_wallets

    def action_refresh(self) -> None:
        """Refresh current screen and record last update timestamp."""
        now = datetime.now(UTC)
        self.state.last_update = now
        for status_bar in self.query(StatusBar):
            status_bar.last_update = now

        if isinstance(self.screen, DashboardScreen):
            self.screen.refresh_counters()

        self.notify(f"Refreshed at {now.strftime('%H:%M:%S UTC')} (Full sync engine in Stage 4)", title="Stage 4 — Refresh")

    def action_filters(self) -> None:
        """Notify that Filters modal is scheduled for Stage 2."""
        self.notify("Filter by group, network, project, and activity scheduled for Stage 2", title="Stage 2 — Filters")

    def action_graph(self) -> None:
        """Notify that Graph interactive view is scheduled for Stage 7."""
        self.notify("NetworkX relationship graph canvas scheduled for Stage 7", title="Stage 7 — Graph")

    def action_search(self) -> None:
        """Notify that Global Search is scheduled for Stage 2."""
        self.notify("Global address and metadata search scheduled for Stage 2", title="Stage 2 — Search")

    def action_escape(self) -> None:
        """Return to dashboard screen or close active dialog."""
        if self.screen.id != "dashboard":
            self.nav_to("dashboard")

    def action_sidebar_up(self) -> None:
        """Navigate up in the sidebar list."""
        with suppress(NoMatches, Exception):
            sidebar = self.screen.query_one("#sidebar_list", ListView)
            sidebar.action_cursor_up()

    def action_sidebar_down(self) -> None:
        """Navigate down in the sidebar list."""
        with suppress(NoMatches, Exception):
            sidebar = self.screen.query_one("#sidebar_list", ListView)
            sidebar.action_cursor_down()

    def action_sidebar_enter(self) -> None:
        """Activate the selected item in the sidebar list."""
        with suppress(NoMatches, Exception):
            sidebar = self.screen.query_one("#sidebar_list", ListView)
            sidebar.action_select_cursor()
