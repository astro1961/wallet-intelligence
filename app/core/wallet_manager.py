"""Wallet management, metadata updates with audit logging, search, and filtering."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlalchemy import or_, select

from app.core.group_manager import GroupManager
from app.database.models import (
    Wallet,
    WalletAuditLog,
    WalletNetwork,
    WalletSocial,
    WalletTag,
    WalletTagLink,
    utc_now,
)
from app.utils.validators import normalize_evm_address

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from sqlalchemy.orm import Session

_EDITABLE_WALLET_FIELDS: frozenset[str] = frozenset({
    "name",
    "address",
    "group_id",
    "notes",
    "chain_type",
    "archived",
    "first_activity_at",
    "last_activity_at",
    "tags",
    "socials",
})


@dataclass
class WalletFilters:
    """Filter criteria for querying wallets."""

    group_id: int | None = None
    tag: str | None = None
    network_id: int | None = None
    archived: bool | None = False
    include_subgroups: bool = True
    search: str | None = None


class WalletManager:
    """Manages wallet lifecycle, tags, socials, audit history, search, and filtering."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create_wallet(
        self,
        address: str,
        name: str | None = None,
        chain_type: str = "evm",
        group_id: int | None = None,
        tags: Iterable[str] = (),
        notes: str | None = None,
        socials: Mapping[str, str] | None = None,
    ) -> Wallet:
        """Create a new wallet with optional group, tags, notes, and socials."""
        if chain_type == "evm":
            norm_addr = normalize_evm_address(address)
        else:
            norm_addr = address.strip()

        wallet = Wallet(
            address=norm_addr,
            address_raw=address,
            chain_type=chain_type,
            name=name.strip() if name else None,
            group_id=group_id,
            notes=notes.strip() if notes else None,
        )
        self.session.add(wallet)
        self.session.flush()

        # Add tags
        for tag_name in tags:
            tag_name_clean = tag_name.strip()
            if not tag_name_clean:
                continue
            tag = self.session.execute(
                select(WalletTag).where(WalletTag.name == tag_name_clean)
            ).scalar_one_or_none()
            if tag is None:
                tag = WalletTag(name=tag_name_clean)
                self.session.add(tag)
                self.session.flush()

            link = WalletTagLink(wallet_id=wallet.id, tag_id=tag.id)
            self.session.add(link)

        # Add socials
        if socials:
            for platform, url_or_handle in socials.items():
                val_str = str(url_or_handle).strip()
                handle = val_str.rstrip("/").split("/")[-1] or val_str
                social = WalletSocial(
                    wallet_id=wallet.id,
                    platform=platform.strip(),
                    handle=handle,
                    url=val_str if "://" in val_str else None,
                )
                self.session.add(social)

        self.session.flush()
        return wallet

    def get_wallet(self, wallet_id: int) -> Wallet | None:
        """Fetch wallet by its primary key ID."""
        return self.session.get(Wallet, wallet_id)

    def update_wallet(self, wallet_id: int, **fields: Any) -> Wallet:
        """Update wallet attributes with whitelist check and audit logging."""
        wallet = self.get_wallet(wallet_id)
        if wallet is None:
            raise ValueError(f"Wallet with id {wallet_id} not found")

        for k in fields:
            if k not in _EDITABLE_WALLET_FIELDS:
                raise ValueError(f"Cannot update non-editable or unknown field '{k}' on Wallet")

        now = utc_now()

        for k, new_val in fields.items():
            if k == "tags":
                old_tag_names = sorted(t.name for t in wallet.tags)
                new_tag_names = sorted(str(t).strip() for t in new_val if str(t).strip())
                if old_tag_names != new_tag_names:
                    # Clear existing tag links
                    for link in list(wallet.tag_links):
                        self.session.delete(link)
                    self.session.flush()

                    for tag_name in new_tag_names:
                        tag = self.session.execute(
                            select(WalletTag).where(WalletTag.name == tag_name)
                        ).scalar_one_or_none()
                        if tag is None:
                            tag = WalletTag(name=tag_name)
                            self.session.add(tag)
                            self.session.flush()
                        self.session.add(WalletTagLink(wallet_id=wallet.id, tag_id=tag.id))

                    log = WalletAuditLog(
                        wallet_id=wallet.id,
                        field="tags",
                        old_value=",".join(old_tag_names) if old_tag_names else None,
                        new_value=",".join(new_tag_names) if new_tag_names else None,
                        changed_at=now,
                    )
                    self.session.add(log)
            elif k == "socials":
                for s in list(wallet.socials):
                    self.session.delete(s)
                self.session.flush()
                if isinstance(new_val, dict):
                    for platform, val_str in new_val.items():
                        v = str(val_str).strip()
                        handle = v.rstrip("/").split("/")[-1] or v
                        self.session.add(
                            WalletSocial(
                                wallet_id=wallet.id,
                                platform=platform.strip(),
                                handle=handle,
                                url=v if "://" in v else None,
                            )
                        )
            else:
                old_val = getattr(wallet, k)
                if k == "address" and wallet.chain_type == "evm":
                    new_val = normalize_evm_address(new_val)

                if old_val != new_val:
                    setattr(wallet, k, new_val)
                    log = WalletAuditLog(
                        wallet_id=wallet.id,
                        field=k,
                        old_value=str(old_val) if old_val is not None else None,
                        new_value=str(new_val) if new_val is not None else None,
                        changed_at=now,
                    )
                    self.session.add(log)

        self.session.flush()
        return wallet

    def archive_wallet(self, wallet_id: int, archived: bool = True) -> Wallet:
        """Set wallet archived status and record audit log."""
        return self.update_wallet(wallet_id, archived=archived)

    def list_wallets(self, filters: WalletFilters | None = None) -> list[Wallet]:
        """List wallets matching optional WalletFilters criteria."""
        stmt = select(Wallet)

        if filters is not None:
            if filters.archived is not None:
                stmt = stmt.where(Wallet.archived == filters.archived)

            if filters.group_id is not None:
                if filters.include_subgroups:
                    gm = GroupManager(self.session)
                    subtree_ids = gm._get_subtree_group_ids(filters.group_id)
                    stmt = stmt.where(Wallet.group_id.in_(subtree_ids))
                else:
                    stmt = stmt.where(Wallet.group_id == filters.group_id)

            if filters.tag is not None and filters.tag.strip():
                tag_query = filters.tag.strip()
                stmt = stmt.where(
                    Wallet.id.in_(
                        select(WalletTagLink.wallet_id)
                        .join(WalletTag)
                        .where(WalletTag.name.ilike(tag_query))
                    )
                )

            if filters.network_id is not None:
                stmt = stmt.where(
                    Wallet.id.in_(
                        select(WalletNetwork.wallet_id).where(
                            WalletNetwork.network_id == filters.network_id
                        )
                    )
                )

            if filters.search is not None and filters.search.strip():
                pattern = f"%{filters.search.strip()}%"
                stmt = stmt.where(
                    or_(
                        Wallet.name.ilike(pattern),
                        Wallet.address.ilike(pattern),
                        Wallet.id.in_(
                            select(WalletTagLink.wallet_id)
                            .join(WalletTag)
                            .where(WalletTag.name.ilike(pattern))
                        ),
                    )
                )

        stmt = stmt.order_by(Wallet.id.asc())
        return list(self.session.execute(stmt).scalars().all())

    def search(self, query: str) -> list[Wallet]:
        """Search wallets by name, address, or tag name."""
        filters = WalletFilters(search=query, archived=None)
        return self.list_wallets(filters)

    def history(self, wallet_id: int) -> list[WalletAuditLog]:
        """Return audit trail for wallet, newest last."""
        stmt = (
            select(WalletAuditLog)
            .where(WalletAuditLog.wallet_id == wallet_id)
            .order_by(WalletAuditLog.changed_at.asc(), WalletAuditLog.id.asc())
        )
        return list(self.session.execute(stmt).scalars().all())
