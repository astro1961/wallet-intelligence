"""Modal dialogs for group management (create, rename, move, delete) and wallet actions."""
from __future__ import annotations

import logging
from typing import ClassVar

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, RadioButton, RadioSet, Select

from app.core.group_manager import GroupManager
from app.core.wallet_manager import WalletManager
from app.database.models import WalletGroup
from app.database.session import session_scope

logger = logging.getLogger(__name__)


class GroupCreateModal(ModalScreen[bool]):
    """Modal to create a new wallet group."""

    BINDINGS: ClassVar[list[Binding]] = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, session_factory, parent_id: int | None = None, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.session_factory = session_factory
        self.parent_id = parent_id

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal-dialog"):
            yield Label("📁 Create New Group", classes="modal-title")
            yield Label("", id="group-form-error", classes="field-error")
            yield Label("Group Name:", classes="form-label")
            yield Input(id="new-group-name", placeholder="e.g. Airdrops or Farming")
            with Vertical(classes="modal-buttons"):
                yield Button("Create", variant="primary", id="create-group-btn")
                yield Button("Cancel", variant="default", id="cancel-group-btn")

    def action_cancel(self) -> None:
        self.dismiss(False)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "create-group-btn":
            name = self.query_one("#new-group-name", Input).value.strip()
            if not name:
                self.query_one("#group-form-error", Label).update("Group name cannot be empty.")
                return
            try:
                with session_scope(self.session_factory) as session:
                    gm = GroupManager(session)
                    gm.create_group(name=name, parent_id=self.parent_id)
                self.dismiss(True)
            except (SQLAlchemyError, ValueError) as e:
                self.query_one("#group-form-error", Label).update(str(e))
        elif event.button.id == "cancel-group-btn":
            self.dismiss(False)


class GroupRenameModal(ModalScreen[bool]):
    """Modal to rename an existing wallet group."""

    BINDINGS: ClassVar[list[Binding]] = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, session_factory, group_id: int, current_name: str, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.session_factory = session_factory
        self.group_id = group_id
        self.current_name = current_name

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal-dialog"):
            yield Label(f"✏️ Rename Group: {self.current_name}", classes="modal-title")
            yield Label("", id="rename-form-error", classes="field-error")
            yield Label("New Name:", classes="form-label")
            yield Input(id="rename-group-name", value=self.current_name)
            with Vertical(classes="modal-buttons"):
                yield Button("Rename", variant="primary", id="rename-group-btn")
                yield Button("Cancel", variant="default", id="cancel-rename-btn")

    def action_cancel(self) -> None:
        self.dismiss(False)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "rename-group-btn":
            name = self.query_one("#rename-group-name", Input).value.strip()
            if not name:
                self.query_one("#rename-form-error", Label).update("Group name cannot be empty.")
                return
            try:
                with session_scope(self.session_factory) as session:
                    grp = session.get(WalletGroup, self.group_id)
                    if grp:
                        grp.name = name
                self.dismiss(True)
            except (SQLAlchemyError, ValueError) as e:
                self.query_one("#rename-form-error", Label).update(str(e))
        elif event.button.id == "cancel-rename-btn":
            self.dismiss(False)


class GroupMoveModal(ModalScreen[bool]):
    """Modal to move a group under another parent or to root."""

    BINDINGS: ClassVar[list[Binding]] = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, session_factory, group_id: int, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.session_factory = session_factory
        self.group_id = group_id

    def compose(self) -> ComposeResult:
        options = [("Root (No parent)", -1)]
        with session_scope(self.session_factory) as session:
            groups = list(session.execute(select(WalletGroup).where(WalletGroup.id != self.group_id)).scalars().all())
            for g in groups:
                options.append((g.name, g.id))

        with Vertical(classes="modal-dialog"):
            yield Label("📦 Move Group", classes="modal-title")
            yield Label("", id="move-form-error", classes="field-error")
            yield Label("Select Target Parent:", classes="form-label")
            yield Select(options, id="move-parent-select", allow_blank=False)
            with Vertical(classes="modal-buttons"):
                yield Button("Move", variant="primary", id="move-group-btn")
                yield Button("Cancel", variant="default", id="cancel-move-btn")

    def action_cancel(self) -> None:
        self.dismiss(False)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "move-group-btn":
            val = self.query_one("#move-parent-select", Select).value
            target_id = None if val in (-1, Select.BLANK) else int(val)
            try:
                with session_scope(self.session_factory) as session:
                    gm = GroupManager(session)
                    gm.move_group(self.group_id, target_id)
                self.dismiss(True)
            except (SQLAlchemyError, ValueError) as e:
                self.query_one("#move-form-error", Label).update(str(e))
        elif event.button.id == "cancel-move-btn":
            self.dismiss(False)


class GroupDeleteModal(ModalScreen[bool]):
    """Modal to delete a group, offering reassignment of wallets to parent or Unassigned."""

    BINDINGS: ClassVar[list[Binding]] = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, session_factory, group_id: int, group_name: str, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.session_factory = session_factory
        self.group_id = group_id
        self.group_name = group_name

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal-dialog"):
            yield Label(f"🗑️ Delete Group: {self.group_name}", classes="modal-title")
            yield Label(
                "Wallets inside this group will NOT be deleted. Where should they be moved?",
                classes="form-label",
            )
            with RadioSet(id="delete-reassign-choice"):
                yield RadioButton("Move wallets to Parent Group", id="opt-parent", value=True)
                yield RadioButton("Move wallets to Unassigned", id="opt-unassigned")
            yield Label("", id="delete-form-error", classes="field-error")
            with Vertical(classes="modal-buttons"):
                yield Button("Delete Group", variant="error", id="delete-confirm-btn")
                yield Button("Cancel", variant="default", id="cancel-delete-btn")

    def action_cancel(self) -> None:
        self.dismiss(False)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "delete-confirm-btn":
            radio_set = self.query_one("#delete-reassign-choice", RadioSet)
            move_to_unassigned = radio_set.pressed_button and radio_set.pressed_button.id == "opt-unassigned"
            try:
                with session_scope(self.session_factory) as session:
                    gm = GroupManager(session)
                    grp = gm.get(self.group_id)
                    if grp:
                        if move_to_unassigned:
                            for w in list(grp.wallets):
                                w.group_id = None
                                w.group = None
                            for c in list(grp.children):
                                c.parent_id = None
                                c.parent = None
                            grp.wallets.clear()
                            grp.children.clear()
                            session.flush()
                            session.delete(grp)
                            session.flush()
                        else:
                            gm.delete_group(self.group_id, reassign_to=None)
                self.dismiss(True)
            except (SQLAlchemyError, ValueError) as e:
                self.query_one("#delete-form-error", Label).update(str(e))
        elif event.button.id == "cancel-delete-btn":
            self.dismiss(False)


class ArchiveConfirmModal(ModalScreen[bool]):
    """Modal to confirm archiving a wallet."""

    BINDINGS: ClassVar[list[Binding]] = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, session_factory, wallet_id: int, wallet_name_or_addr: str, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.session_factory = session_factory
        self.wallet_id = wallet_id
        self.wallet_name_or_addr = wallet_name_or_addr

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal-dialog"):
            yield Label("📦 Archive Wallet", classes="modal-title")
            yield Label(f"Are you sure you want to archive wallet '{self.wallet_name_or_addr}'?", classes="form-label")
            yield Label("Archived wallets are hidden from the active list but retained in the database.", classes="screen-stage")
            with Vertical(classes="modal-buttons"):
                yield Button("Archive", variant="error", id="archive-confirm-btn")
                yield Button("Cancel", variant="default", id="archive-cancel-btn")

    def action_cancel(self) -> None:
        self.dismiss(False)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "archive-confirm-btn":
            try:
                with session_scope(self.session_factory) as session:
                    wm = WalletManager(session)
                    wm.archive_wallet(self.wallet_id, archived=True)
                self.dismiss(True)
            except (SQLAlchemyError, ValueError):
                self.dismiss(False)
        elif event.button.id == "archive-cancel-btn":
            self.dismiss(False)
