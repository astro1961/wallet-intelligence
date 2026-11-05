"""DeFi positions and token analytics screen."""
from __future__ import annotations

import logging
from collections.abc import Iterable
from contextlib import suppress
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from textual.containers import Grid, Vertical
from textual.css.query import NoMatches
from textual.widget import Widget
from textual.widgets import DataTable, Label, Static

from app.core.defi_analyzer import DeFiAnalyzer
from app.ui.screens.base import BaseAppScreen
from app.utils.formatting import format_currency, format_token_amount

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker

logger = logging.getLogger(__name__)


class DeFiScreen(BaseAppScreen):
    """Screen for analyzing confirmed and inferred DeFi protocol positions and token balances."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("id", "defi")
        super().__init__(*args, **kwargs)
        self._loaded: bool = False
        self._aggregate: dict[str, Any] = {
            "total_value": Decimal(0),
            "by_protocol": {},
            "by_network": {},
            "by_certainty": {
                "confirmed": Decimal(0),
                "inferred": Decimal(0),
                "unknown": Decimal(0),
            },
        }
        self._positions: list[Any] = []

    def _get_session_factory(self) -> sessionmaker[Session] | None:
        app = getattr(self, "app", None)
        if app and hasattr(app, "state") and app.state and app.state.session_factory:
            return app.state.session_factory
        try:
            from app.config import load_config
            from app.database.session import init_db, session_factory

            return session_factory(init_db(load_config()))
        except Exception as exc:  # noqa: BLE001
            logger.debug("Could not resolve session factory from app state or default DB: %s", exc)
            return None

    def _get_analyzer(self) -> DeFiAnalyzer | None:
        app = getattr(self, "app", None)
        if app and hasattr(app, "defi_analyzer") and app.defi_analyzer is not None:
            return app.defi_analyzer

        fact = self._get_session_factory()
        if fact is None:
            return None

        cfg = getattr(app, "config", None) if app else None
        providers = getattr(getattr(app, "state", None), "providers", None) if app else None
        price_prov = providers.get("defillama") if providers and hasattr(providers, "get") else None
        return DeFiAnalyzer(fact, price_provider=price_prov, config=cfg)

    def compose_content(self) -> Iterable[Widget]:
        """Compose title, descriptions, aggregate summary cards, and positions table."""
        yield Label("🏦 DeFi Positions", classes="screen-title")
        yield Static(
            "Analyze confirmed and inferred DeFi positions, token balances, and protocol metrics.",
            classes="screen-desc",
        )
        yield Static(
            "Stage 7: DeFi protocol positions, token balances, and portfolio aggregation.",
            classes="screen-stage",
        )

        with Vertical(classes="section-box", id="defi-aggregate-box"):
            yield Label("Portfolio DeFi Aggregate:", classes="section-subtitle")
            with Grid(classes="counter-grid", id="defi-aggregate-grid"):
                yield Label("Total Value: $0.00", id="defi-total-value", classes="counter-card")
                yield Label("Confirmed: $0.00", id="defi-confirmed-value", classes="counter-card")
                yield Label("Inferred: $0.00", id="defi-inferred-value", classes="counter-card")
                yield Label("Unknown: $0.00", id="defi-unknown-value", classes="counter-card")
            yield Static("Protocols: —\nNetworks: —", id="defi-breakdown-text")

        table = DataTable(id="positions-table", classes="positions-table")
        table.cursor_type = "row"
        yield table

        yield Static(
            "No DeFi positions found. Add or sync positions to view breakdown.",
            id="empty-state",
        )

    def on_mount(self) -> None:
        super().on_mount()
        self._ensure_table_columns()
        self.refresh_data()

    def _ensure_table_columns(self) -> None:
        try:
            table = self.query_one(DataTable)
            if not table.columns:
                table.add_column("Protocol", key="protocol")
                table.add_column("Network", key="network")
                table.add_column("Type", key="type")
                table.add_column("Amount", key="amount")
                table.add_column("USD Value", key="usd_value")
                table.add_column("Certainty", key="certainty")
                table.add_column("Details", key="details")
        except NoMatches:
            logger.debug("positions-table not in DOM during column setup")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Error setting up positions-table columns: %s", exc)

    def refresh_data(self) -> None:
        """(Re)load aggregate and positions from DeFiAnalyzer."""
        self._loaded = True
        analyzer = self._get_analyzer()
        if analyzer is None:
            return

        try:
            self._aggregate = analyzer.aggregate()
            self._positions = analyzer.list_positions()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Error refreshing DeFi positions: %s", exc)
            return

        self._update_views()

    def _update_views(self) -> None:
        tot_str = format_currency(self._aggregate.get("total_value", Decimal(0)))
        by_cert = self._aggregate.get("by_certainty", {})
        conf_str = format_currency(by_cert.get("confirmed", Decimal(0)))
        inf_str = format_currency(by_cert.get("inferred", Decimal(0)))
        unk_str = format_currency(by_cert.get("unknown", Decimal(0)))

        with suppress(NoMatches, Exception):
            self.query_one("#defi-total-value", Label).update(f"Total Value: {tot_str}")
            self.query_one("#defi-confirmed-value", Label).update(f"Confirmed: {conf_str}")
            self.query_one("#defi-inferred-value", Label).update(f"Inferred: {inf_str}")
            self.query_one("#defi-unknown-value", Label).update(f"Unknown: {unk_str}")

            by_proto = self._aggregate.get("by_protocol", {})
            by_net = self._aggregate.get("by_network", {})
            proto_str = (
                ", ".join(f"{k}: {format_currency(v)}" for k, v in by_proto.items())
                if by_proto
                else "—"
            )
            net_str = (
                ", ".join(f"{k}: {format_currency(v)}" for k, v in by_net.items())
                if by_net
                else "—"
            )
            self.query_one("#defi-breakdown-text", Static).update(
                f"Protocols: {proto_str}\nNetworks: {net_str}"
            )

        has_items = bool(self._positions)
        with suppress(NoMatches, Exception):
            empty_state = self.query_one("#empty-state", Static)
            empty_state.display = not has_items

        with suppress(NoMatches, Exception):
            table = self.query_one(DataTable)
            table.display = has_items
            table.clear()
            for pos in self._positions:
                net_name = pos.network.name if pos.network else f"ID:{pos.network_id}"
                amt_str = format_token_amount(pos.amount) if pos.amount is not None else "—"
                usd_str = format_currency(pos.usd_value) if pos.usd_value is not None else "—"
                details_str = pos.details or "—"
                table.add_row(
                    pos.protocol,
                    net_name,
                    pos.position_type,
                    amt_str,
                    usd_str,
                    pos.certainty,
                    details_str,
                    key=str(pos.id),
                )
