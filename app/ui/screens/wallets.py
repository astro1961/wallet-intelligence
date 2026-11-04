"""Wallets screen for managing crypto addresses, hierarchical groups, and metadata."""
from __future__ import annotations

from collections.abc import Iterable
from contextlib import suppress
from typing import Any, ClassVar

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.timer import Timer
from textual.widget import Widget
from textual.widgets import DataTable, Input, Label, Static, Tree

from app.core.group_manager import GroupManager
from app.core.wallet_manager import WalletFilters, WalletManager
from app.database.models import Wallet, WalletGroup
from app.database.session import session_scope
from app.ui.screens.base import BaseAppScreen
from app.ui.screens.group_modals import (
    ArchiveConfirmModal,
    GroupCreateModal,
    GroupDeleteModal,
    GroupMoveModal,
    GroupRenameModal,
)
from app.ui.screens.wallet_form import WalletFormScreen

EMPTY_WALLETS_MSG = (
    "Кошельков пока нет / No wallets yet. "
    "Добавьте первый кошелек (нажмите 'a') / Add your first wallet (press 'a')"
)


class WalletsScreen(BaseAppScreen):
    """Screen for managing wallet addresses, hierarchical groups, and metadata."""

    history_text: str = ""

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("a", "add_wallet", "Add Wallet"),
        Binding("e", "edit_wallet", "Edit Wallet"),
        Binding("d", "archive_wallet", "Archive"),
        Binding("slash", "focus_search", "Search"),
        Binding("enter", "select_wallet", "Details"),
        Binding("n", "new_group", "New Group"),
        Binding("f2", "rename_group", "Rename Group"),
        Binding("m", "move_group", "Move Group"),
        Binding("delete", "delete_group", "Delete Group"),
    ]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("id", "wallets")
        super().__init__(*args, **kwargs)
        self.selected_group_id: int | str | None = None
        self.selected_wallet_id: int | None = None
        self.search_query: str = ""
        self._search_timer: Timer | None = None
        self._wallet_row_ids: list[int] = []

    @property
    def session_factory(self):
        if hasattr(self.app, "state") and self.app.state and self.app.state.session_factory:
            return self.app.state.session_factory
        from app.config import load_config
        from app.database.session import init_db, session_factory
        return session_factory(init_db(load_config()))

    def compose_content(self) -> Iterable[Widget]:
        yield Label("👛 Wallets", classes="screen-title")
        yield Static(
            "Manage cryptocurrency addresses, hierarchical groups, metadata, notes, and tags.",
            classes="screen-desc",
        )
        yield Static(
            "Stage 2: wallet & group CRUD, nested hierarchy, tags, notes, and balance inspection.",
            classes="screen-stage",
        )

        yield Static(EMPTY_WALLETS_MSG, id="empty-state")

        with Horizontal(id="wallets-container"):
            tree: Tree[Any] = Tree("All Groups", id="group-tree")
            tree.root.expand()
            yield tree

            with Vertical(id="wallet-right-panel"):
                yield Input(
                    placeholder="Search by name, address, or tag (/ to focus)...",
                    id="wallet-search",
                )
                table: DataTable = DataTable(id="wallet-table")
                table.cursor_type = "row"
                yield table
                yield Static(
                    "Select a wallet and press Enter to view details and audit history.",
                    id="wallet-details",
                )

    def on_mount(self) -> None:
        super().on_mount()
        with suppress(NoMatches):
            table = self.query_one("#wallet-table", DataTable)
            if not table.columns:
                table.add_columns("Name", "Address", "Group", "Tags", "Networks", "Updated")
        self.refresh_data()

    def refresh_data(self) -> None:
        """Re-read groups and wallets from the database and refresh tree and table."""
        self._refresh_group_tree()
        self._refresh_wallet_table()

    def _refresh_group_tree(self) -> None:
        with suppress(NoMatches):
            tree = self.query_one("#group-tree", Tree)
            tree.clear()
            tree.root.label = "All Groups"
            tree.root.data = None

            with suppress(SQLAlchemyError, Exception), session_scope(self.session_factory) as session:
                all_groups = list(
                    session.execute(
                        select(WalletGroup).order_by(WalletGroup.name.asc())
                    ).scalars().all()
                )

                children_map: dict[int | None, list[WalletGroup]] = {}
                for g in all_groups:
                    children_map.setdefault(g.parent_id, []).append(g)

                def add_children(parent_node, pid: int | None):
                    for grp in children_map.get(pid, []):
                        node = parent_node.add(grp.name, data=grp.id)
                        node.expand()
                        add_children(node, grp.id)

                add_children(tree.root, None)
                unassigned_node = tree.root.add("Unassigned", data="unassigned")
                unassigned_node.allow_expand = False
                tree.root.expand()

    def _refresh_wallet_table(self) -> None:
        with suppress(NoMatches):
            table = self.query_one("#wallet-table", DataTable)
            if not table.columns:
                table.add_columns("Name", "Address", "Group", "Tags", "Networks", "Updated")
            table.clear()
            self._wallet_row_ids.clear()

            wallets: list[Wallet] = []
            with suppress(SQLAlchemyError, Exception), session_scope(self.session_factory) as session:
                wm = WalletManager(session)
                if self.selected_group_id == "unassigned":
                    stmt = select(Wallet).where(
                        Wallet.group_id.is_(None),
                        Wallet.archived.is_(False),
                    )
                    if self.search_query.strip():
                        q = f"%{self.search_query.strip()}%"
                        stmt = stmt.where(
                            (Wallet.name.ilike(q)) | (Wallet.address.ilike(q))
                        )
                    wallets = list(session.execute(stmt.order_by(Wallet.id.asc())).scalars().all())
                else:
                    gid = self.selected_group_id if isinstance(self.selected_group_id, int) else None
                    filters = WalletFilters(
                        group_id=gid,
                        include_subgroups=True,
                        search=self.search_query if self.search_query.strip() else None,
                        archived=False,
                    )
                    wallets = wm.list_wallets(filters)

                for w in wallets:
                    self._wallet_row_ids.append(w.id)
                    grp_name = w.group.name if w.group else "Unassigned"
                    tags_str = ", ".join(t.name for t in w.tags) if w.tags else "—"
                    nets_str = (
                        ", ".join(wn.network.name for wn in w.networks if wn.network)
                        if w.networks
                        else "—"
                    )
                    updated_dt = w.last_activity_at or w.created_at
                    updated_ts = updated_dt.strftime("%Y-%m-%d %H:%M") if updated_dt else "—"
                    table.add_row(
                        w.name or "—",
                        w.address,
                        grp_name,
                        tags_str,
                        nets_str,
                        updated_ts,
                        key=str(w.id),
                    )

            empty_state = self.query_one("#empty-state", Static)
            empty_state.display = len(wallets) == 0

    def set_group_filter(self, group_id: int | None) -> None:
        """Filter table rows by group_id (including subgroups); None displays all."""
        self.selected_group_id = group_id
        self._refresh_wallet_table()

    def show_history(self, wallet_id: int) -> None:
        """Fill #wallet-details and history_text with wallet notes, socials, and audit history."""
        self.selected_wallet_id = wallet_id
        with suppress(SQLAlchemyError, Exception), session_scope(self.session_factory) as session:
            wm = WalletManager(session)
            wallet = wm.get_wallet(wallet_id)
            if wallet is None:
                return

            history_entries = wm.history(wallet_id)
            lines = [
                f"Wallet: {wallet.name or 'Unnamed'} ({wallet.address})",
                f"Group: {wallet.group.name if wallet.group else 'Unassigned'}",
                f"Notes: {wallet.notes or 'None'}",
            ]
            if wallet.socials:
                soc_str = ", ".join(f"{s.platform}:{s.handle or s.url}" for s in wallet.socials)
                lines.append(f"Socials: {soc_str}")
            lines.append("Audit History / История изменений:")
            if not history_entries:
                lines.append("  (No audit history recorded)")
            for entry in history_entries:
                ts = entry.changed_at.strftime("%Y-%m-%d %H:%M:%S") if entry.changed_at else ""
                lines.append(f"  [{ts}] {entry.field}: {entry.old_value} -> {entry.new_value}")

            self.history_text = "\n".join(lines)
            with suppress(NoMatches):
                details = self.query_one("#wallet-details", Static)
                details.update(self.history_text)

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        data = event.node.data
        if data == "unassigned":
            self.set_group_filter("unassigned")  # type: ignore[arg-type]
        elif isinstance(data, int):
            self.set_group_filter(data)
        else:
            self.set_group_filter(None)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "wallet-search":
            if self._search_timer is not None:
                self._search_timer.stop()
            self._search_timer = self.set_timer(0.2, self._apply_search)

    def _apply_search(self) -> None:
        with suppress(NoMatches):
            inp = self.query_one("#wallet-search", Input)
            self.search_query = inp.value
            self._refresh_wallet_table()

    def _get_current_selected_wallet_id(self) -> int | None:
        with suppress(NoMatches):
            table = self.query_one("#wallet-table", DataTable)
            if table.cursor_row is not None and 0 <= table.cursor_row < len(self._wallet_row_ids):
                return self._wallet_row_ids[table.cursor_row]
        return self.selected_wallet_id

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.row_key and event.row_key.value:
            with suppress(ValueError, TypeError):
                wid = int(event.row_key.value)
                self.show_history(wid)

    def action_focus_search(self) -> None:
        with suppress(NoMatches):
            self.query_one("#wallet-search", Input).focus()

    def action_select_wallet(self) -> None:
        wid = self._get_current_selected_wallet_id()
        if wid is not None:
            self.show_history(wid)

    def action_add_wallet(self) -> None:
        def _on_closed(_res: Any = None) -> None:
            self.refresh_data()

        self.app.push_screen(WalletFormScreen(session_factory=self.session_factory), _on_closed)

    def action_edit_wallet(self) -> None:
        wid = self._get_current_selected_wallet_id()
        if wid is None:
            self.notify("Please select a wallet to edit", title="Edit Wallet")
            return

        def _on_closed(_res: Any = None) -> None:
            self.refresh_data()
            if wid:
                self.show_history(wid)

        self.app.push_screen(
            WalletFormScreen(session_factory=self.session_factory, wallet_id=wid),
            _on_closed,
        )

    def action_archive_wallet(self) -> None:
        wid = self._get_current_selected_wallet_id()
        if wid is None:
            self.notify("Please select a wallet to archive", title="Archive Wallet")
            return

        with session_scope(self.session_factory) as session:
            w = session.get(Wallet, wid)
            label = f"{w.name} ({w.address})" if (w and w.name) else (w.address if w else str(wid))

        def _on_confirmed(confirmed: bool | None) -> None:
            if confirmed:
                self.archive_selected_wallet(wid)

        self.app.push_screen(
            ArchiveConfirmModal(self.session_factory, wid, label),
            _on_confirmed,
        )

    def archive_selected_wallet(self, wallet_id: int) -> None:
        """Archive wallet and refresh UI."""
        with session_scope(self.session_factory) as session:
            wm = WalletManager(session)
            wm.archive_wallet(wallet_id, archived=True)
        self.refresh_data()

    def action_new_group(self) -> None:
        parent_id = self.selected_group_id if isinstance(self.selected_group_id, int) else None

        def _on_closed(created: bool | None) -> None:
            if created:
                self.refresh_data()

        self.app.push_screen(GroupCreateModal(self.session_factory, parent_id=parent_id), _on_closed)

    def create_group_action(self, name: str, parent_id: int | None = None) -> None:
        """Create group programmatically for tests and actions."""
        with session_scope(self.session_factory) as session:
            gm = GroupManager(session)
            gm.create_group(name=name, parent_id=parent_id)
        self.refresh_data()

    def action_rename_group(self) -> None:
        if not isinstance(self.selected_group_id, int):
            self.notify("Select a group in the tree first to rename it", title="Rename Group")
            return

        gid = self.selected_group_id
        with session_scope(self.session_factory) as session:
            grp = session.get(WalletGroup, gid)
            curr_name = grp.name if grp else ""

        def _on_closed(renamed: bool | None) -> None:
            if renamed:
                self.refresh_data()

        self.app.push_screen(GroupRenameModal(self.session_factory, gid, curr_name), _on_closed)

    def rename_group_action(self, group_id: int, new_name: str) -> None:
        """Rename group programmatically for tests and actions."""
        with session_scope(self.session_factory) as session:
            grp = session.get(WalletGroup, group_id)
            if grp:
                grp.name = new_name
        self.refresh_data()

    def action_move_group(self) -> None:
        if not isinstance(self.selected_group_id, int):
            self.notify("Select a group in the tree first to move it", title="Move Group")
            return

        gid = self.selected_group_id

        def _on_closed(moved: bool | None) -> None:
            if moved:
                self.refresh_data()

        self.app.push_screen(GroupMoveModal(self.session_factory, gid), _on_closed)

    def move_group_action(self, group_id: int, new_parent_id: int | None) -> None:
        """Move group programmatically for tests and actions."""
        with session_scope(self.session_factory) as session:
            gm = GroupManager(session)
            gm.move_group(group_id, new_parent_id)
        self.refresh_data()

    def action_delete_group(self) -> None:
        if not isinstance(self.selected_group_id, int):
            self.notify("Select a group in the tree first to delete it", title="Delete Group")
            return

        gid = self.selected_group_id
        with session_scope(self.session_factory) as session:
            grp = session.get(WalletGroup, gid)
            name = grp.name if grp else ""

        def _on_closed(deleted: bool | None) -> None:
            if deleted:
                self.selected_group_id = None
                self.refresh_data()

        self.app.push_screen(GroupDeleteModal(self.session_factory, gid, name), _on_closed)

    def delete_group_action(self, group_id: int, reassign_to: int | None = None) -> None:
        """Delete group programmatically for tests and actions."""
        with session_scope(self.session_factory) as session:
            gm = GroupManager(session)
            gm.delete_group(group_id, reassign_to=reassign_to)
        self.selected_group_id = None
        self.refresh_data()
