"""Wallet form modal dialog for creating and editing wallet entries."""
from __future__ import annotations

from contextlib import suppress
from typing import Any, ClassVar

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Select, TextArea

from app.core.wallet_manager import WalletManager
from app.database.models import Wallet, WalletGroup
from app.database.session import session_scope
from app.utils.validators import normalize_evm_address


class WalletFormScreen(ModalScreen[int | None]):
    """Modal screen for adding and editing wallets with EIP-55 address validation."""

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "cancel", "Cancel"),
        Binding("ctrl+s", "save", "Save"),
    ]

    def __init__(
        self,
        session_factory=None,
        wallet_id: int | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._session_factory = session_factory
        self.wallet_id = wallet_id

    @property
    def session_factory(self):
        if self._session_factory is not None:
            return self._session_factory
        if hasattr(self.app, "state") and self.app.state and self.app.state.session_factory:
            return self.app.state.session_factory
        from app.config import load_config
        from app.database.session import init_db, session_factory
        return session_factory(init_db(load_config()))

    def compose(self) -> ComposeResult:
        title = "Edit Wallet" if self.wallet_id else "Add Wallet"
        with Vertical(classes="modal-dialog"):
            yield Label(f"👛 {title}", classes="modal-title")
            yield Label("", id="form-error", classes="field-error")

            yield Label("Address (EIP-55 EVM):", classes="form-label")
            yield Input(id="wallet-address", placeholder="0x...")

            yield Label("Name:", classes="form-label")
            yield Input(id="wallet-name", placeholder="e.g. Treasury or Alpha")

            yield Label("Group:", classes="form-label")
            options = self._load_group_options()
            yield Select(options, id="wallet-group", allow_blank=False)

            yield Label("Tags (comma-separated):", classes="form-label")
            yield Input(id="wallet-tags", placeholder="defi, staking, airdrop")

            yield Label("Notes:", classes="form-label")
            yield TextArea(id="wallet-notes")

            yield Label(
                "Socials (kind=url per line, e.g. twitter=https://x.com/abc):",
                classes="form-label",
            )
            yield TextArea(id="wallet-socials")

            with Vertical(classes="modal-buttons"):
                yield Button("Save (Ctrl+S)", variant="primary", id="save-btn")
                yield Button("Cancel (Esc)", variant="default", id="cancel-btn")

    def _load_group_options(self) -> list[tuple[str, int | str]]:
        options: list[tuple[str, int | str]] = [("None (Unassigned)", -1)]
        with suppress(SQLAlchemyError, Exception), session_scope(self.session_factory) as session:
            groups = list(session.execute(select(WalletGroup).order_by(WalletGroup.name.asc())).scalars().all())
            for g in groups:
                options.append((g.name, g.id))
        return options

    def on_mount(self) -> None:
        if self.wallet_id:
            with suppress(SQLAlchemyError, Exception), session_scope(self.session_factory) as session:
                w = session.get(Wallet, self.wallet_id)
                if w:
                    self.query_one("#wallet-address", Input).value = w.address or ""
                    self.query_one("#wallet-name", Input).value = w.name or ""
                    grp_val = w.group_id if w.group_id is not None else -1
                    self.query_one("#wallet-group", Select).value = grp_val
                    tags_str = ", ".join(t.name for t in w.tags)
                    self.query_one("#wallet-tags", Input).value = tags_str
                    self.query_one("#wallet-notes", TextArea).text = w.notes or ""
                    soc_lines = []
                    for s in w.socials:
                        url_or_handle = s.url or s.handle
                        soc_lines.append(f"{s.platform}={url_or_handle}")
                    self.query_one("#wallet-socials", TextArea).text = "\n".join(soc_lines)

    def _show_error(self, message: str) -> None:
        error_lbl = self.query_one("#form-error", Label)
        error_lbl.update(message)

    def save_wallet(self, data: dict[str, Any]) -> int:
        """Create or update wallet via WalletManager; returns wallet id."""
        address = str(data.get("address", "")).strip()
        chain_type = str(data.get("chain_type", "evm")).strip()
        name = data.get("name")
        group_id = data.get("group_id")
        notes = data.get("notes")
        tags = data.get("tags", ())
        socials = data.get("socials")

        if chain_type == "evm":
            address = normalize_evm_address(address)

        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]

        if isinstance(socials, str):
            soc_dict: dict[str, str] = {}
            for line in socials.splitlines():
                line = line.strip()
                if "=" in line:
                    k, v = line.split("=", 1)
                    soc_dict[k.strip()] = v.strip()
                elif line:
                    soc_dict[line] = line
            socials = soc_dict

        with session_scope(self.session_factory) as session:
            wm = WalletManager(session)
            if self.wallet_id:
                fields: dict[str, Any] = {}
                if address:
                    fields["address"] = address
                if name is not None:
                    fields["name"] = name
                fields["group_id"] = group_id
                if notes is not None:
                    fields["notes"] = notes
                fields["tags"] = tags
                if socials is not None:
                    fields["socials"] = socials
                wallet = wm.update_wallet(self.wallet_id, **fields)
                return wallet.id
            else:
                wallet = wm.create_wallet(
                    address=address,
                    name=name,
                    chain_type=chain_type,
                    group_id=group_id,
                    tags=tags,
                    notes=notes,
                    socials=socials,
                )
                return wallet.id

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_save(self) -> None:
        addr = self.query_one("#wallet-address", Input).value.strip()
        if not addr:
            self._show_error("Address is required.")
            return

        name = self.query_one("#wallet-name", Input).value.strip() or None
        grp_val = self.query_one("#wallet-group", Select).value
        group_id: int | None = None
        if grp_val is not None and grp_val != -1 and grp_val != Select.BLANK:
            try:
                group_id = int(grp_val)
            except (ValueError, TypeError):
                group_id = None

        tags_val = self.query_one("#wallet-tags", Input).value.strip()
        notes_val = self.query_one("#wallet-notes", TextArea).text.strip() or None
        socials_val = self.query_one("#wallet-socials", TextArea).text.strip() or None

        payload: dict[str, Any] = {
            "address": addr,
            "name": name,
            "chain_type": "evm",
            "group_id": group_id,
            "tags": tags_val,
            "notes": notes_val,
            "socials": socials_val,
        }

        try:
            wallet_id = self.save_wallet(payload)
            self.dismiss(wallet_id)
        except ValueError as err:
            self._show_error(str(err))
        except (SQLAlchemyError, RuntimeError) as ex:
            self._show_error(f"Error saving wallet: {ex}")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save-btn":
            self.action_save()
        elif event.button.id == "cancel-btn":
            self.action_cancel()
