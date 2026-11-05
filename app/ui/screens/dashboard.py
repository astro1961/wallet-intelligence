"""Dashboard screen with summary telemetry and database counters."""
from __future__ import annotations

import logging
from collections.abc import Iterable
from contextlib import suppress
from datetime import UTC
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import joinedload
from textual.containers import Grid, Vertical
from textual.css.query import NoMatches
from textual.widget import Widget
from textual.widgets import Label, Static

from app.database.models import Activity, BalanceSnapshot, Project, SyncJob, Wallet, WalletGroup
from app.database.session import session_scope
from app.ui.screens.base import BaseAppScreen
from app.utils.formatting import format_token_amount, shorten_address

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker

logger = logging.getLogger(__name__)


class DashboardScreen(BaseAppScreen):
    """Main dashboard screen displaying portfolio summary and entity counts."""

    def __init__(self, *args, **kwargs) -> None:
        kwargs.setdefault("id", "dashboard")
        super().__init__(*args, **kwargs)
        self._loaded: bool = False
        self._counts: dict[str, int] = {
            "wallets": 0,
            "groups": 0,
            "projects": 0,
            "activities": 0,
            "networks": 0,
        }
        self._tracked_value_str: str = "0"
        self._recent_activities_rows: list[str] = []
        self._last_sync_str: str = "Never"

    def _get_session_factory(self) -> sessionmaker[Session] | None:
        app = getattr(self, "app", None)
        if app and hasattr(app, "state") and app.state and app.state.session_factory:
            return app.state.session_factory
        return None

    def get_counters(self) -> dict[str, int]:
        """Compute real counts from the database and configuration."""
        if not self._loaded and self._get_session_factory() is not None:
            self.refresh_data()
        return dict(self._counts)

    def refresh_counters(self) -> None:
        """Update counter widgets with fresh values from DB."""
        self.refresh_data()

    def refresh_data(self) -> None:
        """(Re)load counts, tracked value, last 5 activities, and sync status."""
        self._loaded = True
        session_fact = self._get_session_factory()

        counts = {
            "wallets": 0,
            "groups": 0,
            "projects": 0,
            "activities": 0,
            "networks": 0,
        }
        total_balance = Decimal(0)
        recent_rows: list[str] = []
        last_sync = "Never"

        app = getattr(self, "app", None)
        if app and hasattr(app, "config") and app.config and hasattr(app.config, "networks"):
            counts["networks"] = sum(
                1 for net in app.config.networks if getattr(net, "enabled", True)
            )

        if session_fact is not None:
            try:
                with session_scope(session_fact) as session:
                    # 1. Counts
                    counts["wallets"] = session.scalar(select(func.count(Wallet.id))) or 0
                    counts["groups"] = session.scalar(select(func.count(WalletGroup.id))) or 0
                    counts["projects"] = session.scalar(select(func.count(Project.id))) or 0
                    counts["activities"] = session.scalar(select(func.count(Activity.id))) or 0

                    # 2. Total tracked value (sum of latest BalanceSnapshot per wallet)
                    subq = (
                        select(
                            BalanceSnapshot.wallet_id,
                            func.max(BalanceSnapshot.id).label("max_id"),
                        )
                        .group_by(BalanceSnapshot.wallet_id)
                        .subquery()
                    )
                    latest_snaps = session.execute(
                        select(BalanceSnapshot).join(
                            subq,
                            BalanceSnapshot.id == subq.c.max_id,
                        )
                    ).scalars().all()

                    total_balance = sum((s.balance for s in latest_snaps if s.balance is not None), Decimal(0))

                    # 3. Last 5 activities
                    acts = session.execute(
                        select(Activity)
                        .options(
                            joinedload(Activity.wallet),
                            joinedload(Activity.network),
                            joinedload(Activity.project),
                        )
                        .order_by(Activity.occurred_at.desc(), Activity.id.desc())
                        .limit(5)
                    ).scalars().all()

                    for act in acts:
                        occ_at = act.occurred_at or act.created_at
                        if occ_at.tzinfo is None:
                            occ_at = occ_at.replace(tzinfo=UTC)
                        occ_utc = occ_at.astimezone(UTC)
                        time_str = occ_utc.strftime("%H:%M %d.%m")
                        act_type = act.activity_type or "unknown"
                        if act.wallet and act.wallet.name:
                            w_str = act.wallet.name
                        elif act.wallet and act.wallet.address:
                            w_str = act.wallet.address
                        else:
                            w_str = "—"
                        net_str = act.network.name if act.network else "—"
                        amt_str = format_token_amount(act.amount) if act.amount is not None else "0"
                        proj_str = act.project.name if (act.project and act.project.name) else "—"
                        hash_str = shorten_address(act.tx_hash) if act.tx_hash else "—"
                        recent_rows.append(
                            f"{time_str} · {act_type} · {w_str} · {net_str} · {amt_str} · {proj_str} · {hash_str}"
                        )

                    # 4. Last sync status (SyncJob newest row: type + status + time)
                    latest_job = session.execute(
                        select(SyncJob).order_by(SyncJob.id.desc()).limit(1)
                    ).scalar_one_or_none()

                    if latest_job is not None:
                        job_ts = latest_job.finished_at or latest_job.started_at or latest_job.created_at
                        if job_ts.tzinfo is None:
                            job_ts = job_ts.replace(tzinfo=UTC)
                        ts_str = job_ts.astimezone(UTC).strftime("%H:%M:%S UTC")
                        last_sync = f"{latest_job.job_type} · {latest_job.status} · {ts_str}"
            except (SQLAlchemyError, Exception) as exc:  # noqa: BLE001
                logger.warning("Error refreshing dashboard data: %s", exc)

        self._counts = counts
        self._tracked_value_str = format_token_amount(total_balance)
        self._recent_activities_rows = recent_rows
        self._last_sync_str = last_sync

        self._update_ui_widgets()

    def _update_ui_widgets(self) -> None:
        """Update counter widgets and summary cards."""
        with suppress(NoMatches, Exception):
            self.query_one("#cnt-wallets", Label).update(f"Wallets: {self._counts['wallets']}")
            self.query_one("#cnt-groups", Label).update(f"Groups: {self._counts['groups']}")
            self.query_one("#cnt-projects", Label).update(f"Projects: {self._counts['projects']}")
            self.query_one("#cnt-activities", Label).update(f"Activities: {self._counts['activities']}")
            self.query_one("#cnt-networks", Label).update(f"Networks Enabled: {self._counts['networks']}")
            self.query_one("#val-tracked", Label).update(f"Total Tracked Value: {self._tracked_value_str}")
            self.query_one("#val-sync", Label).update(f"Last Sync: {self._last_sync_str}")
            recent_widget = self.query_one("#dashboard-recent-activities", Static)
            if self._recent_activities_rows:
                recent_widget.update("\n".join(self._recent_activities_rows))
            else:
                recent_widget.update("No activities yet")

    @property
    def dashboard_text(self) -> str:
        """Rendered dashboard summary text."""
        if not self._loaded and self._get_session_factory() is not None:
            self.refresh_data()
        lines = [
            f"Wallets: {self._counts['wallets']}",
            f"Activities: {self._counts['activities']}",
            f"Projects: {self._counts['projects']}",
            f"Total Tracked Value: {self._tracked_value_str}",
            f"Last Sync: {self._last_sync_str}",
            "Last 5 Activities:",
        ]
        if self._recent_activities_rows:
            lines.extend(self._recent_activities_rows)
        else:
            lines.append("No activities yet")
        return "\n".join(lines)

    def compose_content(self) -> Iterable[Widget]:
        """Compose dashboard title, descriptions, real counters, and telemetry."""
        counts = self.get_counters()

        yield Label("📊 Dashboard", classes="screen-title")
        yield Static(
            "Portfolio overview, wallet counts, active projects, recent activities and sync status.",
            classes="screen-desc",
        )
        yield Static(
            "Stage 4: Real-time portfolio telemetry and synchronization status.",
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
                yield Label(f"Total Tracked Value: {self._tracked_value_str}", id="val-tracked", classes="counter-card")
                yield Label(f"Last Sync: {self._last_sync_str}", id="val-sync", classes="counter-card")

        with Vertical(classes="section-box"):
            yield Label("Recent Activities (Last 5):", classes="section-subtitle")
            recent_text = "\n".join(self._recent_activities_rows) if self._recent_activities_rows else "No activities yet"
            yield Static(recent_text, id="dashboard-recent-activities")

    def on_mount(self) -> None:
        super().on_mount()
        self.refresh_data()
