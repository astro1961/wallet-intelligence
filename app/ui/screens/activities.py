"""Activities screen for inspecting transactions and events."""
from __future__ import annotations

import logging
from collections.abc import Iterable
from contextlib import suppress
from datetime import UTC
from typing import TYPE_CHECKING

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import joinedload
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.widget import Widget
from textual.widgets import Label, Static

from app.database.models import Activity, Network
from app.database.session import session_scope
from app.ui.screens.base import BaseAppScreen
from app.utils.formatting import format_token_amount, shorten_address

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker

logger = logging.getLogger(__name__)

EMPTY_ACTIVITIES_MSG = "No activities yet — press **s** to sync your wallets."


class ActivitiesScreen(BaseAppScreen):
    """Screen for inspecting on-chain events, transaction histories, and user activities."""

    def __init__(self, *args, **kwargs) -> None:
        kwargs.setdefault("id", "activities")
        super().__init__(*args, **kwargs)
        self.type_filter: str | None = None
        self.network_filter: str | None = None
        self.project_filter: int | None = None
        self._rows: list[str] = []
        self._loaded: bool = False

    def _get_session_factory(self) -> sessionmaker[Session] | None:
        app = getattr(self, "app", None)
        if app and hasattr(app, "state") and app.state and app.state.session_factory:
            return app.state.session_factory
        return None

    def compose_content(self) -> Iterable[Widget]:
        """Compose screen header, filter badges, and scrollable activity feed."""
        yield Label("⚡ Activities", classes="screen-title")
        yield Static(
            "Track on-chain events, transactions, and manual activities across monitored wallets.",
            classes="screen-desc",
        )
        yield Static(
            "Stage 4: Real-time activities feed with synchronization and event deduplication.",
            classes="screen-stage",
        )
        with Horizontal(id="activities-filter-row", classes="filters-bar"):
            yield Label("Filters:", classes="filter-title")
            yield Label(f"[Type: {self.type_filter or 'All'}]", id="filter-type", classes="filter-badge")
            yield Label(f"[Network: {self.network_filter or 'All'}]", id="filter-network", classes="filter-badge")
            yield Label(
                f"[Project: {self.project_filter if self.project_filter is not None else 'All'}]",
                id="filter-project",
                classes="filter-badge",
            )
        with Vertical(id="activities-feed-box", classes="feed-box"):
            yield Static(self.activity_text, id="activities-feed-text")

    def on_mount(self) -> None:
        super().on_mount()
        self.refresh_data()

    def refresh_data(self) -> None:
        """(Re)load activities from DB according to current filters."""
        self._loaded = True
        session_fact = self._get_session_factory()
        if session_fact is None:
            self._rows = []
            self._update_feed_view()
            return

        try:
            with session_scope(session_fact) as session:
                stmt = (
                    select(Activity)
                    .options(
                        joinedload(Activity.wallet),
                        joinedload(Activity.network),
                        joinedload(Activity.project),
                    )
                    .order_by(Activity.occurred_at.desc(), Activity.id.desc())
                )
                if self.type_filter is not None:
                    stmt = stmt.where(func.lower(Activity.activity_type) == self.type_filter.strip().lower())
                if self.network_filter is not None:
                    stmt = stmt.join(Activity.network).where(
                        func.lower(Network.name) == self.network_filter.strip().lower()
                    )
                if self.project_filter is not None:
                    stmt = stmt.where(Activity.project_id == self.project_filter)

                stmt = stmt.limit(200)
                activities = list(session.execute(stmt).scalars().all())

                formatted_rows: list[str] = []
                for act in activities:
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

                    if act.amount is not None:
                        amt_str = format_token_amount(act.amount)
                    else:
                        amt_str = "0"

                    proj_str = act.project.name if (act.project and act.project.name) else "—"

                    if act.tx_hash:
                        hash_str = shorten_address(act.tx_hash)
                    else:
                        hash_str = "—"

                    formatted_rows.append(
                        f"{time_str} · {act_type} · {w_str} · {net_str} · {amt_str} · {proj_str} · {hash_str}"
                    )

                self._rows = formatted_rows
        except (SQLAlchemyError, Exception) as exc:  # noqa: BLE001
            logger.warning("Error refreshing activities data: %s", exc)
            self._rows = []

        self._update_feed_view()

    def _update_feed_view(self) -> None:
        """Update feed Static widget and filter badges."""
        with suppress(NoMatches, Exception):
            feed_widget = self.query_one("#activities-feed-text", Static)
            feed_widget.update(self.activity_text)

            t_lbl = self.query_one("#filter-type", Label)
            t_lbl.update(f"[Type: {self.type_filter or 'All'}]")
            n_lbl = self.query_one("#filter-network", Label)
            n_lbl.update(f"[Network: {self.network_filter or 'All'}]")
            p_lbl = self.query_one("#filter-project", Label)
            p_lbl.update(f"[Project: {self.project_filter if self.project_filter is not None else 'All'}]")

    @property
    def activity_text(self) -> str:
        """Rendered feed as text (used by tests and UI)."""
        if not self._loaded and self._get_session_factory() is not None:
            self.refresh_data()
        if not self._rows:
            return EMPTY_ACTIVITIES_MSG
        return "\n".join(self._rows)

    def set_type_filter(self, activity_type: str | None) -> None:
        """Filter activities by activity_type or restore all if None."""
        self.type_filter = activity_type
        self.refresh_data()

    def set_network_filter(self, network: str | None) -> None:
        """Filter activities by network name or restore all if None."""
        self.network_filter = network
        self.refresh_data()

    def set_project_filter(self, project_id: int | None) -> None:
        """Filter activities by project id or restore all if None."""
        self.project_filter = project_id
        self.refresh_data()
