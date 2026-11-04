"""Repository layer for Wallet and Group entities."""
from __future__ import annotations

from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.database.models import Wallet, WalletGroup


class WalletRepository:
    """Repository handling CRUD and queries for Wallet records."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, wallet: Wallet | None = None, **kwargs: Any) -> Wallet:
        """Add and persist a new wallet."""
        if wallet is None:
            wallet = Wallet(**kwargs)
        self.session.add(wallet)
        self.session.flush()
        return wallet

    def get(self, wallet_id: int) -> Wallet | None:
        """Retrieve a wallet by primary key ID."""
        return self.session.get(Wallet, wallet_id)

    def get_by_address(self, address: str, chain_type: str = "evm") -> Wallet | None:
        """Retrieve a wallet by address and chain type (case-insensitive for EVM)."""
        search_addr = address.lower() if chain_type == "evm" else address
        stmt = select(Wallet).where(
            Wallet.address == search_addr,
            Wallet.chain_type == chain_type,
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def list(
        self,
        group_id: int | None = None,
        archived: bool | None = None,
        search: str | None = None,
    ) -> list[Wallet]:
        """Query wallets by group, archive status, and search string."""
        stmt = select(Wallet)
        if group_id is not None:
            stmt = stmt.where(Wallet.group_id == group_id)
        if archived is not None:
            stmt = stmt.where(Wallet.archived == archived)
        if search:
            search_pattern = f"%{search.lower()}%"
            stmt = stmt.where(
                or_(
                    Wallet.address.ilike(search_pattern),
                    Wallet.name.ilike(search_pattern),
                )
            )
        stmt = stmt.order_by(Wallet.created_at.desc())
        return list(self.session.execute(stmt).scalars().all())

    def update(self, wallet_id: int, **kwargs: Any) -> Wallet | None:
        """Update fields of an existing wallet."""
        wallet = self.get(wallet_id)
        if wallet is None:
            return None

        for k, v in kwargs.items():
            if hasattr(wallet, k):
                if k == "address" and wallet.chain_type == "evm" and isinstance(v, str):
                    wallet.address_raw = v
                    wallet.address = v.lower()
                else:
                    setattr(wallet, k, v)

        self.session.flush()
        return wallet

    def archive(self, wallet_id: int, archived: bool = True) -> Wallet | None:
        """Mark a wallet as archived or unarchived."""
        return self.update(wallet_id, archived=archived)


class GroupRepository:
    """Repository handling tree operations and lifecycle for WalletGroup entities."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self,
        name: str,
        parent_id: int | None = None,
        description: str | None = None,
    ) -> WalletGroup:
        """Create a new wallet group."""
        group = WalletGroup(name=name, parent_id=parent_id, description=description)
        self.session.add(group)
        self.session.flush()
        return group

    def get(self, group_id: int) -> WalletGroup | None:
        """Retrieve a group by its primary key ID."""
        return self.session.get(WalletGroup, group_id)

    def rename(self, group_id: int, new_name: str) -> WalletGroup | None:
        """Rename an existing wallet group."""
        group = self.get(group_id)
        if group is None:
            return None
        group.name = new_name
        self.session.flush()
        return group

    def move(self, group_id: int, new_parent_id: int | None) -> WalletGroup | None:
        """Move a group to a new parent, preventing circular references."""
        group = self.get(group_id)
        if group is None:
            return None

        if new_parent_id is not None:
            if new_parent_id == group_id:
                raise ValueError("Cycle detected: cannot set parent to group itself")

            # Check that new_parent_id is not a descendant of group_id
            curr_id: int | None = new_parent_id
            visited: set[int] = set()
            while curr_id is not None:
                if curr_id in visited:
                    raise ValueError(f"Cycle detected in parent chain at group {curr_id}")
                visited.add(curr_id)

                if curr_id == group_id:
                    raise ValueError(
                        f"Cycle detected: group {group_id} is an ancestor of target {new_parent_id}"
                    )
                ancestor = self.get(curr_id)
                curr_id = ancestor.parent_id if ancestor else None

        group.parent_id = new_parent_id
        self.session.flush()
        return group

    def delete_reassigning_wallets(
        self,
        group_id: int,
        target_group_id: int | None = None,
    ) -> None:
        """Delete a group, reassigning its wallets and children to a target group (or parent)."""
        group = self.get(group_id)
        if group is None:
            return

        reassign_to = target_group_id if target_group_id is not None else group.parent_id

        # Reassign wallets belonging to this group
        stmt_wallets = select(Wallet).where(Wallet.group_id == group_id)
        for w in self.session.execute(stmt_wallets).scalars():
            w.group_id = reassign_to

        # Reassign child groups
        stmt_children = select(WalletGroup).where(WalletGroup.parent_id == group_id)
        for child in self.session.execute(stmt_children).scalars():
            child.parent_id = reassign_to

        self.session.delete(group)
        self.session.flush()
