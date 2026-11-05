"""Relationship graph screen for visualizing wallet interactions and cluster stats."""
from __future__ import annotations

import logging
from collections.abc import Iterable
from contextlib import suppress
from typing import TYPE_CHECKING, Any

import networkx as nx
from sqlalchemy import select
from textual.containers import Grid, Vertical
from textual.css.query import NoMatches
from textual.widget import Widget
from textual.widgets import DataTable, Label, Select, Static

from app.core.graph_manager import GraphManager, _format_address
from app.database.models import Wallet
from app.ui.screens.base import BaseAppScreen

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker

logger = logging.getLogger(__name__)


class GraphScreen(BaseAppScreen):
    """Screen for exploring wallet relationship graphs, neighbors, and network metrics."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("id", "graph")
        super().__init__(*args, **kwargs)
        self.selected_wallet: str | None = None
        self._loaded: bool = False

    def _get_session_factory(self) -> sessionmaker[Session] | None:
        """Obtain session factory from application state or create one from config."""
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

    def compose_content(self) -> Iterable[Widget]:
        """Compose title, stats grid, wallet selector, and neighbors table."""
        yield Label("🕸 Relationship Graph", classes="screen-title")
        yield Static(
            "Explore wallet clusters, inferred counterparty connections, and network metrics.",
            classes="screen-desc",
        )
        yield Static(
            "Stage 8: NetworkX relationship graph, neighbor list, components, and density stats.",
            classes="screen-stage",
        )

        with Vertical(classes="section-box", id="graph-stats-box"):
            yield Label("Network Graph Statistics:", classes="section-subtitle")
            with Grid(classes="counter-grid", id="graph-stats-grid"):
                yield Label("Connected Components: 0", id="graph-components", classes="counter-card")
                yield Label("Graph Density: 0.0000", id="graph-density", classes="counter-card")
                yield Label("Nodes: 0", id="graph-nodes", classes="counter-card")
                yield Label("Edges: 0", id="graph-edges", classes="counter-card")

        with Vertical(classes="section-box", id="graph-selector-box"):
            yield Label("Select Wallet for Neighbor Inspection:", classes="section-subtitle")
            yield Select([], id="wallet-select", prompt="Select a wallet...")
            yield Label("Selected: —", id="graph-selected-wallet")

        table = DataTable(id="neighbors-table", classes="neighbors-table")
        table.cursor_type = "row"
        yield table

        yield Static(
            "No neighbors found for selected wallet or graph is empty.",
            id="empty-state",
        )

    def on_mount(self) -> None:
        super().on_mount()
        self._ensure_table_columns()
        self.refresh_data()

    def _ensure_table_columns(self) -> None:
        try:
            table = self.query_one("#neighbors-table", DataTable)
            if not table.columns:
                table.add_column("Address", key="address")
                table.add_column("Name", key="name")
                table.add_column("Relation Type", key="relation_type")
                table.add_column("Confidence", key="confidence")
        except NoMatches:
            logger.debug("neighbors-table not in DOM during column setup")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Error setting up neighbors-table columns: %s", exc)

    def refresh_data(self) -> None:
        """(Re)load graph statistics and neighbor list for current selection."""
        self._loaded = True
        fact = self._get_session_factory()
        if fact is None:
            return

        try:
            with fact() as session:
                gm = GraphManager(session)

                # 1. Update wallet options in select widget
                wallets = (
                    session.execute(
                        select(Wallet).order_by(Wallet.name, Wallet.address)
                    )
                    .scalars()
                    .all()
                )
                options: list[tuple[str, str]] = []
                for w in wallets:
                    fmt_addr = _format_address(w)
                    label = f"{w.name} ({fmt_addr[:6]}...{fmt_addr[-4:]})" if w.name else fmt_addr
                    options.append((label, fmt_addr))

                with suppress(NoMatches):
                    select_widget = self.query_one("#wallet-select", Select)
                    select_widget.set_options(options)

                # 2. Update graph stats
                G = gm.build_graph()
                num_nodes = G.number_of_nodes()
                num_edges = G.number_of_edges()
                num_comp = nx.number_connected_components(G) if num_nodes > 0 else 0
                density_str = f"{nx.density(G):.4f}" if num_nodes > 1 else "0.0000"

                with suppress(NoMatches):
                    self.query_one("#graph-components", Label).update(
                        f"Connected Components: {num_comp}"
                    )
                    self.query_one("#graph-density", Label).update(
                        f"Graph Density: {density_str}"
                    )
                    self.query_one("#graph-nodes", Label).update(f"Nodes: {num_nodes}")
                    self.query_one("#graph-edges", Label).update(f"Edges: {num_edges}")

                # 3. Update neighbors
                target_wallet = self.selected_wallet
                if not target_wallet and options:
                    target_wallet = options[0][1]
                    self.selected_wallet = target_wallet
                    with suppress(NoMatches):
                        self.query_one("#wallet-select", Select).value = target_wallet

                if target_wallet:
                    w_obj = gm._resolve_wallet(target_wallet)
                    if w_obj:
                        with suppress(NoMatches):
                            lbl = self.query_one("#graph-selected-wallet", Label)
                            disp = (
                                f"Selected: {w_obj.name} ({_format_address(w_obj)})"
                                if w_obj.name
                                else f"Selected: {_format_address(w_obj)}"
                            )
                            lbl.update(disp)
                    neighbors = gm.neighbors(target_wallet)
                    self._update_neighbors_table(neighbors)
                else:
                    self._update_neighbors_table([])
        except Exception as exc:  # noqa: BLE001
            logger.warning("Error refreshing graph screen data: %s", exc)

    def select_wallet(self, wallet: Wallet | str | int) -> None:
        """Select a wallet and render its neighbors."""
        fact = self._get_session_factory()
        if fact is None:
            return

        with fact() as session:
            gm = GraphManager(session)
            w_obj = gm._resolve_wallet(wallet)
            if w_obj is not None:
                addr = _format_address(w_obj)
                self.selected_wallet = addr
                with suppress(NoMatches):
                    self.query_one("#wallet-select", Select).value = addr
                with suppress(NoMatches):
                    lbl = self.query_one("#graph-selected-wallet", Label)
                    disp = (
                        f"Selected: {w_obj.name} ({addr})"
                        if w_obj.name
                        else f"Selected: {addr}"
                    )
                    lbl.update(disp)
                neighbors = gm.neighbors(w_obj)
                self._update_neighbors_table(neighbors)
            else:
                self.selected_wallet = str(wallet)
                with suppress(NoMatches):
                    lbl = self.query_one("#graph-selected-wallet", Label)
                    lbl.update(f"Selected: {wallet}")
                self._update_neighbors_table([])

    def on_select_changed(self, event: Select.Changed) -> None:
        """Handle wallet select dropdown changes."""
        if event.select.id == "wallet-select" and event.value != Select.BLANK:
            self.select_wallet(event.value)

    def _update_neighbors_table(self, neighbors: list[dict[str, Any]]) -> None:
        """Populate DataTable with neighbors or show empty placeholder."""
        try:
            table = self.query_one("#neighbors-table", DataTable)
            table.clear()
            for n in neighbors:
                table.add_row(
                    n["address"],
                    n["name"] or "—",
                    n["relation_type"],
                    n["confidence"],
                )
            empty = self.query_one("#empty-state", Static)
            if neighbors:
                empty.display = False
                table.display = True
            else:
                empty.display = True
                table.display = False
        except NoMatches:
            logger.debug("neighbors-table not found in DOM")
