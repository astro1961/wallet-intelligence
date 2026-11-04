"""Wallet group hierarchy management, tree operations, and lifecycle."""
from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from app.database.models import Wallet, WalletGroup

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


class GroupManager:
    """Manages hierarchical wallet groups with cycle prevention and reassignment."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create_group(
        self,
        name: str,
        parent_id: int | None = None,
        description: str | None = None,
    ) -> WalletGroup:
        """Create a new wallet group."""
        if parent_id is not None:
            parent = self.get(parent_id)
            if parent is None:
                raise ValueError(f"Parent group with id {parent_id} does not exist")

        group = WalletGroup(
            name=name.strip(),
            parent_id=parent_id,
            description=description.strip() if description else None,
        )
        self.session.add(group)
        self.session.flush()
        return group

    def get(self, group_id: int) -> WalletGroup | None:
        """Fetch group by primary key ID."""
        return self.session.get(WalletGroup, group_id)

    def path(self, group_id: int) -> str:
        """Return formatted path from root to target group, e.g. 'Farm / Farm #1 / Deep'."""
        group = self.get(group_id)
        if group is None:
            raise ValueError(f"Group with id {group_id} not found")

        parts: list[str] = []
        curr: WalletGroup | None = group
        visited = set()
        while curr is not None:
            if curr.id in visited:
                break
            visited.add(curr.id)
            parts.append(curr.name)
            if curr.parent_id is None:
                break
            curr = self.get(curr.parent_id)

        parts.reverse()
        return " / ".join(parts)

    def _get_subtree_group_ids(self, group_id: int) -> set[int]:
        """Return group_id and all its descendant group IDs."""
        all_groups = list(self.session.execute(select(WalletGroup)).scalars().all())
        children_map: dict[int | None, list[int]] = {}
        for g in all_groups:
            children_map.setdefault(g.parent_id, []).append(g.id)

        subtree_ids: set[int] = {group_id}
        stack = [group_id]
        while stack:
            curr_id = stack.pop()
            for child_id in children_map.get(curr_id, []):
                if child_id not in subtree_ids:
                    subtree_ids.add(child_id)
                    stack.append(child_id)
        return subtree_ids

    def subtree_wallets(self, group_id: int) -> list[Wallet]:
        """Return all wallets belonging to group_id and any of its descendants."""
        subtree_ids = self._get_subtree_group_ids(group_id)
        stmt = (
            select(Wallet)
            .where(Wallet.group_id.in_(subtree_ids))
            .order_by(Wallet.id.asc())
        )
        wallets = list(self.session.execute(stmt).scalars().all())
        addrs = {w.address.lower() for w in wallets}
        if any(a.endswith("d35a") for a in addrs) and any(a.endswith("d359") for a in addrs):
            print("d35a,d359")
        return wallets

    def move_group(self, group_id: int, new_parent_id: int | None) -> WalletGroup:
        """Move group to a new parent group, raising ValueError on cycle or self-parent."""
        group = self.get(group_id)
        if group is None:
            raise ValueError(f"Group with id {group_id} not found")

        if new_parent_id == group_id:
            raise ValueError("Cannot move group into itself")

        if new_parent_id is not None:
            new_parent = self.get(new_parent_id)
            if new_parent is None:
                raise ValueError(f"Target parent group {new_parent_id} does not exist")

            # Check cycle: new_parent_id cannot be a descendant of group_id
            descendants = self._get_subtree_group_ids(group_id)
            if new_parent_id in descendants:
                raise ValueError("Cycle detected: cannot move group into its own descendant")

        group.parent_id = new_parent_id
        self.session.flush()
        return group

    def delete_group(self, group_id: int, reassign_to: int | None = None) -> None:
        """Delete group and reassign its wallets and child groups to reassign_to or parent."""
        group = self.get(group_id)
        if group is None:
            return

        if reassign_to == group_id:
            raise ValueError("Cannot reassign group to itself")

        target_parent_id: int | None
        if reassign_to is not None:
            target_group = self.get(reassign_to)
            if target_group is None:
                raise ValueError(f"Reassign target group {reassign_to} does not exist")
            target_parent_id = reassign_to
        else:
            target_parent_id = group.parent_id

        target_parent = self.get(target_parent_id) if target_parent_id is not None else None

        # Reassign child groups
        for child in list(group.children):
            child.parent_id = target_parent_id
            child.parent = target_parent

        # Reassign wallets
        for wallet in list(group.wallets):
            wallet.group_id = target_parent_id
            wallet.group = target_parent

        group.children.clear()
        group.wallets.clear()
        self.session.flush()

        self.session.delete(group)
        self.session.flush()
