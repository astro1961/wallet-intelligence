"""Dashboard screen with summary telemetry and database counters."""
from __future__ import annotations

from collections.abc import Iterable
from contextlib import suppress

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from textual.containers import Grid, Vertical
from textual.css.query import NoMatches
from textual.widget import Widget
from textual.widgets import Label

from app.database.models import Activity, Project, Wallet, WalletGroup
from app.ui.screens.base import BaseAppScreen


class DashboardScreen(BaseAppScreen):
    """Main dashboard screen displaying portfolio summary and entity counts."""

    def __init__(self, *args, **kwargs) -> None:
        kwargs.setdefault("id", "dashboard")
        super().__init__(*args, **kwargs)

    def get_counters(self) -> dict[str, int]:
        """Compute real counts from the database and configuration."""
        counts = {
            "wallets": 0,
            "groups": 0,
            "projects": 0,
            "activities": 0,
            "networks": 0,
        }
        app = getattr(self, "app", None)
        if app and hasattr(app, "state") and app.state and app.state.session_factory:
            with (
                suppress(SQLAlchemyError, Exception),
                app.state.session_factory() as session,
            ):
                counts["wallets"] = session.scalar(select(func.count(Wallet.id))) or 0
                counts["groups"] = session.scalar(select(func.count(WalletGroup.id))) or 0
                counts["projects"] = session.scalar(select(func.count(Project.id))) or 0
                counts["activities"] = session.scalar(select(func.count(Activity.id))) or 0

        if app and hasattr(app, "config") and app.config and hasattr(app.config, "networks"):
            counts["networks"] = sum(
                1 for net in app.config.networks if getattr(net, "enabled", True)
            )

        return counts

    def refresh_counters(self) -> None:
        """Update counter widgets with fresh values from DB."""
        counts = self.get_counters()
        with suppress(NoMatches, Exception):
            self.query_one("#cnt-wallets", Label).update(f"Wallets: {counts['wallets']}")
            self.query_one("#cnt-groups", Label).update(f"Groups: {counts['groups']}")
            self.query_one("#cnt-projects", Label).update(f"Projects: {counts['projects']}")
            self.query_one("#cnt-activities", Label).update(f"Activities: {counts['activities']}")
            self.query_one("#cnt-networks", Label).update(f"Networks Enabled: {counts['networks']}")

    def compose_content(self) -> Iterable[Widget]:
        """Compose dashboard title, empty state description, and real counters."""
        counts = self.get_counters()

        yield Label("📊 Dashboard", classes="screen-title")
        yield Label(
            "Portfolio overview, wallet counts, active projects, recent activities and sync status.",
            classes="screen-desc",
        )
        yield Label(
            "Stage 1B: database counters. Full live portfolio aggregation coming in Stage 4–6.",
            classes="screen-stage",
        )

        with Vertical(classes="section-box"):
            yield Label("Database Overview (Real Counters):", classes="section-subtitle")
            with Grid(classes="counter-grid"):
                yield Label(f"Wallets: {counts['wallets']}", id="cnt-wallets", classes="counter-card")
                yield Label(f"Groups: {counts['groups']}", id="cnt-groups", classes="counter-card")
                yield Label(f"Projects: {counts['projects']}", id="cnt-projects", classes="counter-card")
                yield Label(f"Activities: {counts['activities']}", id="cnt-activities", classes="counter-card")
                yield Label(f"Networks Enabled: {counts['networks']}", id="cnt-networks", classes="counter-card")

    def on_mount(self) -> None:
        super().on_mount()
        self.refresh_counters()
