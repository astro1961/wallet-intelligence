"""Dashboard screen in netwatch/btop dense monitoring TUI style."""
from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Iterable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, ClassVar, Literal

from rich.text import Text
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import joinedload
from textual import events
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Label, Static

from app.database.models import (
    Activity,
    BalanceSnapshot,
    DeFiPosition,
    Project,
    SyncJob,
    Wallet,
    WalletGroup,
)
from app.database.session import session_scope
from app.ui.screens.base import BaseAppScreen
from app.utils.formatting import format_token_amount, shorten_address

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker

logger = logging.getLogger(__name__)

SPARK_CHARS = (" ", "▂", "▃", "▄", "▅", "▆", "▇", "█")


@dataclass
class WalletInfo:
    """Internal model for wallet row representation in dashboard table."""

    wallet_id: int
    name: str
    address: str
    short_address: str
    group_id: int | None
    group_name: str
    network_name: str
    balance: Decimal
    change_pct: Decimal | None


@dataclass
class ActivityInfo:
    """Internal model for recent activity row."""

    occurred_at: datetime
    address_str: str
    activity_type: str
    amount_str: str
    network_str: str


class NetwatchPanel(Static):
    """Base interactive panel for netwatch dashboard with focus capability."""

    can_focus = True


class DashboardScreen(BaseAppScreen):
    """Main dashboard screen displaying portfolio summary and netwatch telemetry."""

    DEFAULT_CSS = """
    DashboardScreen {
        background: $background;
        color: $text;
    }

    #netwatch-container {
        height: auto;
        width: 100%;
        layout: vertical;
        margin: 0;
        padding: 0;
    }

    .netwatch-panel {
        border: round $primary;
        background: $surface;
        padding: 0 1;
        margin-bottom: 1;
        height: auto;
    }

    .netwatch-panel:focus {
        border: round $accent;
    }

    .panel-header {
        text-style: bold;
        color: $accent;
        padding-bottom: 0;
        border-bottom: solid $panel;
        margin-bottom: 0;
    }

    #panel-metrics {
        height: auto;
    }

    #dashboard-middle-row {
        layout: horizontal;
        height: auto;
        margin-bottom: 0;
    }

    Screen.narrow #dashboard-middle-row {
        layout: vertical;
    }

    #panel-wallets {
        width: 1fr;
        margin-right: 1;
        height: auto;
        min-height: 7;
    }

    Screen.narrow #panel-wallets {
        width: 100%;
        margin-right: 0;
    }

    #panel-activity {
        width: 1fr;
        height: auto;
        min-height: 7;
    }

    Screen.narrow #panel-activity {
        width: 100%;
    }

    #panel-trend {
        height: auto;
    }

    #dashboard-status-line {
        background: $surface-darken-1;
        color: $text-muted;
        padding: 0 1;
        height: auto;
        border: solid $panel;
        text-style: bold;
        margin-top: 0;
    }

    .zoomed {
        display: block !important;
        height: auto !important;
        min-height: 14 !important;
        border: double $accent !important;
    }

    .panel-hidden {
        display: none !important;
    }

    .screen-title {
        margin-bottom: 0;
    }

    .screen-desc {
        margin-bottom: 0;
    }

    .screen-stage {
        margin-bottom: 1;
    }
    """

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("1", "zoom(1)", "Zoom Metrics"),
        Binding("2", "zoom(2)", "Zoom Wallets"),
        Binding("3", "zoom(3)", "Zoom Activity"),
        Binding("4", "zoom(4)", "Zoom Trend"),
        Binding("b", "sort_wallets('balance')", "Sort by Balance"),
        Binding("c", "sort_wallets('change')", "Sort by Change"),
        Binding("f", "toggle_fold", "Fold/Unfold Groups"),
        Binding("escape", "escape_action", "Back / Full View"),
    ]

    def __init__(self, *args, **kwargs) -> None:
        kwargs.setdefault("id", "dashboard")
        super().__init__(*args, **kwargs)
        self._loaded: bool = False
        self._zoomed_panel: int | None = None
        self._sort_by: Literal["balance", "change"] = "balance"
        self._sort_reverse: bool = True
        self._folded_groups: set[int | None] = set()

        self._counts: dict[str, int] = {
            "wallets": 0,
            "groups": 0,
            "projects": 0,
            "activities": 0,
            "networks": 0,
        }
        self._total_balance: Decimal = Decimal(0)
        self._total_balance_change_pct: Decimal | None = None
        self._defi_positions_count: int = 0
        self._last_sync_str: str = "Never"
        self._last_sync_status: str = "idle"
        self._failed_sync_count: int = 0

        self._wallets_data: list[WalletInfo] = []
        self._recent_activities_rows: list[str] = []
        self._recent_activities_data: list[ActivityInfo] = []

        self._trend_points: list[Decimal] = []
        self._trend_min: Decimal = Decimal(0)
        self._trend_max: Decimal = Decimal(0)
        self._trend_current: Decimal = Decimal(0)
        self._trend_saturation: Decimal = Decimal(0)
        self._trend_change_pct: Decimal | None = None

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        """Prevent zoom action from hijacking navigation hotkeys 1-4 when focused on sidebar."""
        if action == "zoom":
            focused = getattr(self.app, "focused", None)
            if focused is not None:
                fid = getattr(focused, "id", "") or ""
                pid = getattr(getattr(focused, "parent", None), "id", "") or ""
                if fid == "sidebar_list" or pid == "sidebar_list":
                    return False
            return True
        return super().check_action(action, parameters)

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

    def zoom_panel(self, panel_idx: int | None) -> None:
        """Toggle zoom / maximize on one of the 4 panels (1-4)."""
        if self._zoomed_panel == panel_idx:
            self._zoomed_panel = None
        else:
            self._zoomed_panel = panel_idx

        panels = {
            1: "#panel-metrics",
            2: "#panel-wallets",
            3: "#panel-activity",
            4: "#panel-trend",
        }

        for idx, selector in panels.items():
            with suppress(Exception):
                node = self.query_one(selector)
                if self._zoomed_panel is None:
                    node.remove_class("zoomed")
                    node.remove_class("panel-hidden")
                elif idx == self._zoomed_panel:
                    node.add_class("zoomed")
                    node.remove_class("panel-hidden")
                    node.focus()
                else:
                    node.add_class("panel-hidden")
                    node.remove_class("zoomed")

        self._render_all_panels()

    def action_zoom(self, panel_idx: int) -> None:
        """Textual action handler for zoom hotkeys 1-4."""
        self.zoom_panel(int(panel_idx))

    def action_escape_action(self) -> None:
        """Esc key handler: unzooms panel if zoomed, else delegates to app."""
        if self._zoomed_panel is not None:
            self.zoom_panel(None)
        else:
            app = getattr(self, "app", None)
            if app and hasattr(app, "action_escape"):
                app.action_escape()

    def action_sort_wallets(self, by: str = "balance") -> None:
        """Sort wallets panel by balance or 24h change."""
        if by in ("balance", "change"):
            if self._sort_by == by:
                self._sort_reverse = not self._sort_reverse
            else:
                self._sort_by = by
                self._sort_reverse = True
            self._render_wallets_panel()

    def action_toggle_fold(self) -> None:
        """Toggle folding of all wallet groups."""
        all_group_ids = {w.group_id for w in self._wallets_data}
        if self._folded_groups.issuperset(all_group_ids):
            self._folded_groups.clear()
        else:
            self._folded_groups = set(all_group_ids)
        self._render_wallets_panel()

    def on_click(self, event: events.Click) -> None:
        """Handle clicks on panel headers to zoom/unzoom."""
        for target in event.widget.ancestors_with_self:
            tid = getattr(target, "id", "") or ""
            if tid == "panel-metrics":
                self.zoom_panel(1)
                event.stop()
                break
            if tid == "panel-wallets":
                # If clicking near top of wallets panel, toggle zoom
                if event.y <= 2:
                    self.zoom_panel(2)
                    event.stop()
                break
            if tid == "panel-activity":
                if event.y <= 2:
                    self.zoom_panel(3)
                    event.stop()
                break
            if tid == "panel-trend":
                self.zoom_panel(4)
                event.stop()
                break

    def refresh_data(self) -> None:
        """(Re)load all real data from DB across models."""
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
        total_change_pct: Decimal | None = None
        defi_count = 0
        failed_syncs = 0
        last_sync = "Never"
        last_status = "idle"

        wallets_list: list[WalletInfo] = []
        recent_rows: list[str] = []
        recent_activities: list[ActivityInfo] = []

        trend_points: list[Decimal] = []
        trend_min = Decimal(0)
        trend_max = Decimal(0)
        trend_cur = Decimal(0)
        trend_sat = Decimal(0)
        trend_chg: Decimal | None = None

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
                    defi_count = session.scalar(select(func.count(DeFiPosition.id))) or 0
                    failed_syncs = (
                        session.scalar(
                            select(func.count(SyncJob.id)).where(SyncJob.status == "failed")
                        )
                        or 0
                    )

                    # 2. Wallets and latest BalanceSnapshot per wallet
                    subq = (
                        select(
                            BalanceSnapshot.wallet_id,
                            func.max(BalanceSnapshot.id).label("max_id"),
                        )
                        .group_by(BalanceSnapshot.wallet_id)
                        .subquery()
                    )
                    latest_snaps = {
                        s.wallet_id: s
                        for s in session.execute(
                            select(BalanceSnapshot)
                            .join(subq, BalanceSnapshot.id == subq.c.max_id)
                            .options(joinedload(BalanceSnapshot.network))
                        )
                        .scalars()
                        .all()
                    }

                    # Previous snapshots (to calculate 24h / previous change)
                    prev_subq = (
                        select(
                            BalanceSnapshot.wallet_id,
                            func.max(BalanceSnapshot.id).label("prev_id"),
                        )
                        .join(subq, BalanceSnapshot.wallet_id == subq.c.wallet_id)
                        .where(BalanceSnapshot.id < subq.c.max_id)
                        .group_by(BalanceSnapshot.wallet_id)
                        .subquery()
                    )
                    prev_snaps = {
                        s.wallet_id: s
                        for s in session.execute(
                            select(BalanceSnapshot).join(
                                prev_subq, BalanceSnapshot.id == prev_subq.c.prev_id
                            )
                        )
                        .scalars()
                        .all()
                    }

                    # Query all wallets with group
                    db_wallets = (
                        session.execute(
                            select(Wallet)
                            .options(joinedload(Wallet.group))
                            .order_by(Wallet.id.asc())
                        )
                        .scalars()
                        .all()
                    )

                    total_prev_balance = Decimal(0)
                    has_any_prev = False

                    for w in db_wallets:
                        snap = latest_snaps.get(w.id)
                        psnap = prev_snaps.get(w.id)

                        bal = snap.balance if (snap and snap.balance is not None) else Decimal(0)
                        total_balance += bal

                        net_name = "—"
                        if snap and snap.network and snap.network.name:
                            net_name = snap.network.name
                        elif w.chain_type:
                            net_name = w.chain_type.upper()

                        change_pct: Decimal | None = None
                        if psnap and psnap.balance is not None:
                            has_any_prev = True
                            total_prev_balance += psnap.balance
                            if psnap.balance > Decimal(0):
                                change_pct = (bal - psnap.balance) / psnap.balance * Decimal(100)
                            elif bal > Decimal(0):
                                change_pct = Decimal(100)
                            else:
                                change_pct = Decimal(0)

                        grp_id = w.group.id if w.group else None
                        grp_name = w.group.name if w.group else "Ungrouped"

                        w_info = WalletInfo(
                            wallet_id=w.id,
                            name=w.name or "",
                            address=w.address,
                            short_address=shorten_address(w.address),
                            group_id=grp_id,
                            group_name=grp_name,
                            network_name=net_name,
                            balance=bal,
                            change_pct=change_pct,
                        )
                        wallets_list.append(w_info)

                    if has_any_prev and total_prev_balance > Decimal(0):
                        total_change_pct = (
                            (total_balance - total_prev_balance)
                            / total_prev_balance
                            * Decimal(100)
                        )
                    elif has_any_prev and total_balance > Decimal(0):
                        total_change_pct = Decimal(100)

                    # 3. Recent Activities (up to 30)
                    acts = (
                        session.execute(
                            select(Activity)
                            .options(
                                joinedload(Activity.wallet),
                                joinedload(Activity.network),
                                joinedload(Activity.project),
                            )
                            .order_by(Activity.occurred_at.desc(), Activity.id.desc())
                            .limit(30)
                        )
                        .scalars()
                        .all()
                    )

                    for act in acts:
                        occ_at = act.occurred_at or act.created_at
                        if occ_at.tzinfo is None:
                            occ_at = occ_at.replace(tzinfo=UTC)
                        occ_utc = occ_at.astimezone(UTC)
                        time_str = occ_utc.strftime("%H:%M:%S")

                        act_type = (act.activity_type or "tx").upper()
                        if act.wallet and act.wallet.address:
                            w_addr = shorten_address(act.wallet.address)
                        else:
                            w_addr = "—"

                        amt_val = (
                            format_token_amount(act.amount) if act.amount is not None else "0"
                        )
                        if act.token_symbol:
                            amt_val = f"{amt_val} {act.token_symbol}"

                        net_str = act.network.name if act.network else "—"

                        recent_activities.append(
                            ActivityInfo(
                                occurred_at=occ_utc,
                                address_str=w_addr,
                                activity_type=act_type,
                                amount_str=amt_val,
                                network_str=net_str,
                            )
                        )
                        recent_rows.append(
                            f"{time_str} · {act_type} · {w_addr} · {net_str} · {amt_val}"
                        )

                    # 4. Last sync status
                    latest_job = session.execute(
                        select(SyncJob).order_by(SyncJob.id.desc()).limit(1)
                    ).scalar_one_or_none()

                    if latest_job is not None:
                        job_ts = (
                            latest_job.finished_at
                            or latest_job.started_at
                            or latest_job.created_at
                        )
                        if job_ts.tzinfo is None:
                            job_ts = job_ts.replace(tzinfo=UTC)
                        ts_str = job_ts.astimezone(UTC).strftime("%H:%M:%S UTC")
                        last_sync = f"{ts_str}"
                        last_status = latest_job.status or "idle"
                    elif app and hasattr(app, "state") and app.state and app.state.last_update:
                        last_sync = app.state.last_update.strftime("%H:%M:%S UTC")
                        last_status = app.state.sync_state

                    # 5. Trend points from all BalanceSnapshots
                    all_snaps = (
                        session.execute(
                            select(BalanceSnapshot).order_by(
                                BalanceSnapshot.snapshot_at.asc(), BalanceSnapshot.id.asc()
                            )
                        )
                        .scalars()
                        .all()
                    )

                    wallet_curr_bal: dict[int, Decimal] = {}
                    for s in all_snaps:
                        if s.balance is not None and s.wallet_id is not None:
                            wallet_curr_bal[s.wallet_id] = s.balance
                            trend_points.append(sum(wallet_curr_bal.values(), Decimal(0)))

                    if trend_points:
                        trend_cur = trend_points[-1]
                        trend_min = min(trend_points)
                        trend_max = max(trend_points)
                        first_val = trend_points[0]
                        if first_val > Decimal(0):
                            trend_chg = (trend_cur - first_val) / first_val * Decimal(100)
                        elif trend_cur > Decimal(0):
                            trend_chg = Decimal(100)
                        else:
                            trend_chg = Decimal(0)

                        if trend_max > trend_min:
                            trend_sat = (
                                (trend_cur - trend_min)
                                / (trend_max - trend_min)
                                * Decimal(100)
                            )
                        else:
                            trend_sat = Decimal(100) if trend_cur > Decimal(0) else Decimal(0)
                    elif total_balance > Decimal(0):
                        trend_cur = total_balance
                        trend_min = total_balance
                        trend_max = total_balance
                        trend_sat = Decimal(100)
            except (SQLAlchemyError, Exception) as exc:  # noqa: BLE001
                logger.warning("Error refreshing dashboard data: %s", exc)

        self._counts = counts
        self._total_balance = total_balance
        self._total_balance_change_pct = total_change_pct
        self._defi_positions_count = defi_count
        self._failed_sync_count = failed_syncs
        self._last_sync_str = last_sync
        self._last_sync_status = last_status

        self._wallets_data = wallets_list
        self._recent_activities_rows = recent_rows
        self._recent_activities_data = recent_activities

        self._trend_points = trend_points
        self._trend_min = trend_min
        self._trend_max = trend_max
        self._trend_current = trend_cur
        self._trend_saturation = trend_sat
        self._trend_change_pct = trend_chg

        self._render_all_panels()

    def _render_all_panels(self) -> None:
        """Update rendered text of all 4 netwatch panels and status line."""
        self._render_metrics_panel()
        self._render_wallets_panel()
        self._render_activity_panel()
        self._render_trend_panel()
        self._render_status_line()

    @staticmethod
    def _format_badge(change: Decimal | None) -> str:
        """Format ▲/▼ colored badge with percentage or —."""
        if change is None:
            return "[dim]—[/dim]"
        if change > Decimal(0):
            return f"[bold green]▲ +{change:.1f}%[/bold green]"
        if change < Decimal(0):
            return f"[bold red]▼ {change:.1f}%[/bold red]"
        return "[dim]— 0.0%[/dim]"

    def _render_metrics_panel(self) -> None:
        """Render Panel 1: Big numbers row + badge."""
        with suppress(Exception):
            p1 = self.query_one("#panel-metrics", NetwatchPanel)
            zoomed = self._zoomed_panel == 1
            z_indicator = " [ZOOMED: Press 1 to exit]" if zoomed else " [Press 1 to zoom]"
            hdr = f"[bold cyan]┌─ [1] SUMMARY METRICS{z_indicator} ──────────────────────────────────────┐[/bold cyan]"

            bal_str = format_token_amount(self._total_balance)
            bal_badge = self._format_badge(self._total_balance_change_pct)

            lines = [
                hdr,
                "  [bold]TOTAL BALANCE[/bold]       [bold]WALLETS[/bold]     [bold]TRACKED TX[/bold]    [bold]DEFI POS[/bold]    [bold]LAST SYNC[/bold]",
                f"  $ {bal_str} {bal_badge}   {self._counts['wallets']:<11} {self._counts['activities']:<13} {self._defi_positions_count:<11} {self._last_sync_str}",
            ]

            if zoomed:
                lines.extend([
                    " [dim]────────────────────────────────────────────────────────────────────────[/dim]",
                    "  [bold white]PORTFOLIO TELEMETRY DETAILED BREAKDOWN:[/bold white]",
                    f"  • Active Wallets:     {self._counts['wallets']} across {self._counts['groups']} groups",
                    f"  • Enabled Networks:   {self._counts['networks']}",
                    f"  • Tracked Projects:   {self._counts['projects']}",
                    f"  • Recorded Activities:{self._counts['activities']}",
                    f"  • DeFi Positions:     {self._defi_positions_count}",
                    f"  • Sync Status:        {self._last_sync_status.upper()} (Failed jobs: {self._failed_sync_count})",
                ])

            lines.append("[bold cyan]└───────────────────────────────────────────────────────────────────────┘[/bold cyan]")
            p1.update(Text.from_markup("\n".join(lines)))

    def _render_wallets_panel(self) -> None:
        """Render Panel 2: Wallets table with sorting and fold/unfold."""
        with suppress(Exception):
            p2 = self.query_one("#panel-wallets", NetwatchPanel)
            zoomed = self._zoomed_panel == 2
            z_indicator = " [ZOOMED: 2 to exit]" if zoomed else " [2: zoom]"
            sort_dir = "▼" if self._sort_reverse else "▲"
            hdr = (
                f"[bold cyan]┌─ [2] WALLETS (b: sort {self._sort_by} {sort_dir}, c: chg, f: fold){z_indicator} ──┐[/bold cyan]"
            )

            # Group wallets
            grouped: dict[int | None, list[WalletInfo]] = defaultdict(list)
            for w in self._wallets_data:
                grouped[w.group_id].append(w)

            # Sort wallets within groups
            def sort_key(item: WalletInfo):
                if self._sort_by == "change":
                    val = item.change_pct
                    return (val is not None, val if val is not None else Decimal(-999999))
                val = item.balance
                return (val is not None, val if val is not None else Decimal(0))

            lines = [
                hdr,
                "  [bold]ADDRESS[/bold]          [bold]BALANCE[/bold]        [bold]CHANGE 24h[/bold]   [bold]NETWORK[/bold]",
            ]

            if not self._wallets_data:
                lines.append("  [dim]No wallets tracked yet (press 'a' to add or 'i' to import)[/dim]")
            else:
                for grp_id, w_list in grouped.items():
                    grp_name = w_list[0].group_name
                    is_folded = grp_id in self._folded_groups
                    fold_sym = "▶" if is_folded else "▼"
                    grp_sum = sum((w.balance for w in w_list), Decimal(0))
                    status_lbl = " [dim](folded)[/dim]" if is_folded else ""
                    lines.append(
                        f" {fold_sym} [bold yellow]{grp_name}[/bold yellow] ({len(w_list)}) — {format_token_amount(grp_sum)}{status_lbl}"
                    )

                    if not is_folded:
                        w_sorted = sorted(w_list, key=sort_key, reverse=self._sort_reverse)
                        limit = 30 if zoomed else 8
                        for w in w_sorted[:limit]:
                            b_str = format_token_amount(w.balance)
                            badge = self._format_badge(w.change_pct)
                            addr_disp = w.name[:12] if w.name else w.short_address
                            lines.append(
                                f"   {addr_disp:<14}  {b_str:>12}  {badge:>10}  [cyan]{w.network_name:<10}[/cyan]"
                            )
                        if len(w_sorted) > limit:
                            lines.append(f"   [dim]... +{len(w_sorted) - limit} more (press 2 to zoom)[/dim]")

            lines.append("[bold cyan]└───────────────────────────────────────────────────────────────────────┘[/bold cyan]")
            p2.update(Text.from_markup("\n".join(lines)))

    def _render_activity_panel(self) -> None:
        """Render Panel 3: Recent Activity feed with badges."""
        with suppress(Exception):
            p3 = self.query_one("#panel-activity", NetwatchPanel)
            zoomed = self._zoomed_panel == 3
            z_indicator = " [ZOOMED: 3 to exit]" if zoomed else " [3: zoom]"
            hdr = f"[bold cyan]┌─ [3] RECENT ACTIVITY{z_indicator} ──────────────────────────────────────┐[/bold cyan]"

            lines = [hdr]
            if not self._recent_activities_data:
                lines.append("  [dim]No activities yet[/dim]")
            else:
                limit = 30 if zoomed else 6
                for act in self._recent_activities_data[:limit]:
                    t_str = act.occurred_at.strftime("%H:%M:%S")
                    t_type = act.activity_type.upper()

                    # Color badge mapping
                    if "TRANSFER" in t_type:
                        badge = f"[bold cyan][{t_type}][/bold cyan]"
                    elif "SWAP" in t_type:
                        badge = f"[bold magenta][{t_type}][/bold magenta]"
                    elif "CLAIM" in t_type or "BUY" in t_type:
                        badge = f"[bold green][{t_type}][/bold green]"
                    elif "SELL" in t_type:
                        badge = f"[bold red][{t_type}][/bold red]"
                    elif "BRIDGE" in t_type:
                        badge = f"[bold yellow][{t_type}][/bold yellow]"
                    else:
                        badge = f"[bold blue][{t_type}][/bold blue]"

                    lines.append(
                        f"  [dim]{t_str}[/dim] · [white]{act.address_str}[/white] · {badge} · [bold]{act.amount_str}[/bold]"
                    )

                if len(self._recent_activities_data) > limit:
                    lines.append(f"  [dim]... +{len(self._recent_activities_data) - limit} more (press 3 to zoom)[/dim]")

            lines.append("[bold cyan]└───────────────────────────────────────────────────────────────────────┘[/bold cyan]")
            p3.update(Text.from_markup("\n".join(lines)))

    def _render_trend_panel(self) -> None:
        """Render Panel 4: Balance trend sparkline and saturation bar."""
        with suppress(Exception):
            p4 = self.query_one("#panel-trend", NetwatchPanel)
            zoomed = self._zoomed_panel == 4
            z_indicator = " [ZOOMED: 4 to exit]" if zoomed else " [4: zoom]"
            hdr = f"[bold cyan]┌─ [4] BALANCE TREND{z_indicator} ─────────────────────────────────────────┐[/bold cyan]"

            # Build sparkline
            pts = self._trend_points
            if pts:
                sample_count = 36 if zoomed else 20
                if len(pts) > sample_count:
                    step = len(pts) / sample_count
                    sampled = [pts[int(i * step)] for i in range(sample_count)]
                else:
                    sampled = pts

                s_min = min(sampled)
                s_max = max(sampled)
                spark_str = ""
                for val in sampled:
                    if s_max > s_min:
                        level = round((val - s_min) / (s_max - s_min) * 7)
                        spark_str += SPARK_CHARS[min(7, max(0, level))]
                    else:
                        spark_str += "▅"
            else:
                spark_str = "[dim]No snapshot data[/dim]"

            # Saturation bar (20 chars)
            bar_len = 24 if zoomed else 16
            filled_len = round(float(self._trend_saturation) / 100.0 * bar_len)
            filled_len = min(bar_len, max(0, filled_len))
            empty_len = bar_len - filled_len
            bar_visual = f"[{'█' * filled_len}{'░' * empty_len}]"

            if self._trend_saturation >= Decimal(70):
                bar_markup = f"[green]{bar_visual}[/green]"
            elif self._trend_saturation >= Decimal(30):
                bar_markup = f"[yellow]{bar_visual}[/yellow]"
            else:
                bar_markup = f"[cyan]{bar_visual}[/cyan]"

            sat_label = f"Saturation: {bar_markup} [bold]{self._trend_saturation:.1f}%[/bold]"
            range_label = f"Min: [bold]{format_token_amount(self._trend_min)}[/bold]  │  Cur: [bold]{format_token_amount(self._trend_current)}[/bold]  │  Max: [bold]{format_token_amount(self._trend_max)}[/bold]"
            chg_badge = self._format_badge(self._trend_change_pct)

            lines = [
                hdr,
                f"  Trend:      [bold cyan]{spark_str}[/bold cyan]    {sat_label}    Change: {chg_badge}",
                f"  Range:      {range_label}",
            ]

            if zoomed and pts:
                lines.extend([
                    " [dim]────────────────────────────────────────────────────────────────────────[/dim]",
                    f"  Snapshot history data points: {len(pts)} total records",
                    f"  Period start value: {format_token_amount(pts[0])}  →  Current: {format_token_amount(self._trend_current)}",
                ])

            lines.append("[bold cyan]└───────────────────────────────────────────────────────────────────────┘[/bold cyan]")
            p4.update(Text.from_markup("\n".join(lines)))

    def _render_status_line(self) -> None:
        """Render bottom status line with sync state, time, issues, and hotkeys."""
        with suppress(Exception):
            s_line = self.query_one("#dashboard-status-line", Static)
            sync_st = self._last_sync_status.lower()
            if sync_st == "syncing":
                sync_badge = "[bold yellow]● syncing[/bold yellow]"
            elif sync_st == "paused":
                sync_badge = "[bold red]⏸ paused[/bold red]"
            else:
                sync_badge = "[bold green]● idle[/bold green]"

            if self._failed_sync_count > 0:
                issues_badge = f"[bold red]issues: {self._failed_sync_count} failed[/bold red]"
            else:
                issues_badge = "[dim green]issues: 0 ok[/dim green]"

            keys_help = "[bold]1-4[/bold] Zoom │ [bold]b[/bold] Bal │ [bold]c[/bold] Chg │ [bold]f[/bold] Fold │ [bold]s[/bold] Sync │ [bold]p[/bold] Pause │ [bold]r[/bold] Refresh │ [bold]q[/bold] Quit"
            text = f"sync: {sync_badge} · {self._last_sync_str}  │  {issues_badge}  │  {keys_help}"
            s_line.update(Text.from_markup(text))

    @property
    def dashboard_text(self) -> str:
        """Rendered dashboard summary text for compatibility with stage tests."""
        if not self._loaded and self._get_session_factory() is not None:
            self.refresh_data()
        lines = [
            f"Wallets: {self._counts['wallets']}",
            f"Activities: {self._counts['activities']}",
            f"Projects: {self._counts['projects']}",
            f"Total Tracked Value: {format_token_amount(self._total_balance)}",
            f"Last Sync: {self._last_sync_str}",
            "Last 5 Activities:",
        ]
        if self._recent_activities_rows:
            lines.extend(self._recent_activities_rows[:5])
        else:
            lines.append("No activities yet")
        return "\n".join(lines)

    def compose_content(self) -> Iterable[Static]:
        """Compose netwatch dense multi-panel monitoring dashboard."""
        yield Label("📊 Dashboard", classes="screen-title")
        yield Static(
            "Portfolio overview, wallet counts, active projects, recent activities and sync status.",
            classes="screen-desc",
        )
        yield Static(
            "Stage 4: Real-time portfolio telemetry and synchronization status.",
            classes="screen-stage",
        )

        with Vertical(id="netwatch-container"):
            # 1. Top panel - summary metrics (big numbers)
            yield NetwatchPanel(id="panel-metrics", classes="netwatch-panel")

            # 2 & 3. Middle row: Wallets table + Recent activity feed
            with Horizontal(id="dashboard-middle-row"):
                yield NetwatchPanel(id="panel-wallets", classes="netwatch-panel")
                yield NetwatchPanel(id="panel-activity", classes="netwatch-panel")

            # 4. Bottom panel - Balance trend sparkline + saturation
            yield NetwatchPanel(id="panel-trend", classes="netwatch-panel")

            # 6. Status line
            yield Static(id="dashboard-status-line")

    def on_mount(self) -> None:
        """Refresh data on mount."""
        super().on_mount()
        self.refresh_data()

    def on_screen_resume(self) -> None:
        """Refresh data when the screen is resumed (Textual sends ScreenResume, not Show)."""
        self.refresh_data()
