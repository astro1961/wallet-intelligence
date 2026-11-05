"""Project management, catalog, per-network contracts, and participation tracking."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select

from app.database.models import (
    Activity,
    Network,
    Project,
    ProjectContract,
    ProjectTask,
    ProjectWallet,
    Wallet,
    utc_now,
)
from app.utils.validators import normalize_evm_address

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

_EDITABLE_PROJECT_FIELDS: frozenset[str] = frozenset({
    "name",
    "description",
    "category",
    "status",
    "official_url",
    "notes",
})


class NetworkNotFoundError(KeyError, ValueError):
    """Raised when a network name or identifier cannot be resolved."""


class ProjectManager:
    """Manages project catalog, per-network contracts, tasks, and wallet participation."""

    def __init__(self, session: Session) -> None:
        self.session = session

    # ---------------------------------------------------------------------
    # Catalog
    # ---------------------------------------------------------------------

    def create_project(
        self,
        name: str,
        description: str | None = None,
        category: str | None = None,
        status: str = "active",
        official_url: str | None = None,
        notes: str | None = None,
    ) -> Project:
        """Create a new project in the catalog with case-insensitive name uniqueness."""
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Project name cannot be empty")

        clean_name = name.strip()
        existing = self.session.execute(
            select(Project).where(func.lower(Project.name) == clean_name.lower())
        ).scalar_one_or_none()
        if existing is not None:
            raise ValueError(f"Project with name '{name}' already exists")

        project = Project(
            name=clean_name,
            description=description.strip() if description else None,
            category=category.strip() if category else None,
            status=status.strip() if status else "active",
            official_url=official_url.strip() if official_url else None,
            notes=notes.strip() if notes else None,
        )
        self.session.add(project)
        self.session.flush()
        return project

    def update_project(self, project_id: int, **fields: Any) -> Project:
        """Update project attributes using an explicit field whitelist."""
        project = self.get(project_id)
        if project is None:
            raise ValueError(f"Project with id {project_id} not found")

        for key in fields:
            if key not in _EDITABLE_PROJECT_FIELDS:
                raise ValueError(f"Cannot update non-editable or unknown field '{key}' on Project")

        if "name" in fields:
            new_name = fields["name"]
            if not isinstance(new_name, str) or not new_name.strip():
                raise ValueError("Project name cannot be empty")
            clean_name = new_name.strip()
            existing = self.session.execute(
                select(Project).where(
                    func.lower(Project.name) == clean_name.lower(),
                    Project.id != project_id,
                )
            ).scalar_one_or_none()
            if existing is not None:
                raise ValueError(f"Project with name '{new_name}' already exists")
            project.name = clean_name

        for key, value in fields.items():
            if key == "name":
                continue
            if isinstance(value, str):
                setattr(project, key, value.strip())
            else:
                setattr(project, key, value)

        project.updated_at = utc_now()
        self.session.flush()
        return project

    def get(self, project_id: int) -> Project | None:
        """Fetch project by its primary key ID."""
        return self.session.get(Project, project_id)

    def list_projects(self, status: str | None = None) -> list[Project]:
        """List all projects or filter by status."""
        stmt = select(Project)
        if status is not None:
            stmt = stmt.where(func.lower(Project.status) == status.strip().lower())
        stmt = stmt.order_by(Project.id.asc())
        return list(self.session.execute(stmt).scalars().all())

    def count(self) -> int:
        """Return total count of projects."""
        return self.session.execute(select(func.count(Project.id))).scalar_one()

    def delete_project(self, project_id: int) -> None:
        """Delete project and cascade associated contracts, wallets, tasks, and notes."""
        project = self.get(project_id)
        if project is None:
            return

        for contract in list(project.contracts):
            self.session.delete(contract)
        for pw in list(project.project_wallets):
            self.session.delete(pw)
        for task in list(project.tasks):
            self.session.delete(task)
        for note in list(project.notes_list):
            self.session.delete(note)

        self.session.delete(project)
        self.session.flush()

    # ---------------------------------------------------------------------
    # Contracts
    # ---------------------------------------------------------------------

    def _resolve_network(self, network: Network | int | str) -> Network:
        """Resolve Network model by instance, id, or case-insensitive name."""
        if isinstance(network, Network):
            return network
        if isinstance(network, int):
            net = self.session.get(Network, network)
            if net is not None:
                return net
            raise NetworkNotFoundError(f"Network with id {network} not found")
        if isinstance(network, str):
            clean_name = network.strip()
            net = self.session.execute(
                select(Network).where(func.lower(Network.name) == clean_name.lower())
            ).scalar_one_or_none()
            if net is not None:
                return net
            if clean_name.isdigit():
                net = self.session.execute(
                    select(Network).where(Network.chain_id == int(clean_name))
                ).scalar_one_or_none()
                if net is not None:
                    return net
            raise NetworkNotFoundError(f"Unknown network '{network}'")

        raise NetworkNotFoundError(f"Invalid network identifier type: {type(network).__name__}")

    def add_contract(
        self,
        project_id: int,
        network: str,
        contract_address: str,
        name: str | None = None,
    ) -> ProjectContract:
        """Add contract to project on network with EIP-55 normalization and network resolution."""
        project = self.get(project_id)
        if project is None:
            raise ValueError(f"Project with id {project_id} not found")

        norm_addr = normalize_evm_address(contract_address)
        net = self._resolve_network(network)

        existing = self.session.execute(
            select(ProjectContract).where(
                ProjectContract.network_id == net.id,
                func.lower(ProjectContract.contract_address) == norm_addr.lower(),
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise ValueError(
                f"Contract '{norm_addr}' already registered on network '{net.name}'"
            )

        contract = ProjectContract(
            project_id=project.id,
            network_id=net.id,
            contract_address=norm_addr,
            name=name.strip() if name else None,
        )
        self.session.add(contract)
        self.session.flush()
        return contract

    def list_contracts(self, project_id: int) -> list[ProjectContract]:
        """List all contracts associated with a project."""
        stmt = (
            select(ProjectContract)
            .where(ProjectContract.project_id == project_id)
            .order_by(ProjectContract.id.asc())
        )
        return list(self.session.execute(stmt).scalars().all())

    def find_project_by_contract(self, address: str, network: str) -> Project | None:
        """Find project by contract address and network, returning None if not found."""
        if not isinstance(address, str) or not address.strip():
            return None

        try:
            net = self._resolve_network(network)
        except NetworkNotFoundError:
            return None

        addr_clean = address.strip().lower()
        contract = self.session.execute(
            select(ProjectContract).where(
                ProjectContract.network_id == net.id,
                func.lower(ProjectContract.contract_address) == addr_clean,
            )
        ).scalar_one_or_none()

        if contract is None:
            return None

        return contract.project or self.get(contract.project_id)

    # ---------------------------------------------------------------------
    # Participation
    # ---------------------------------------------------------------------

    def _sync_detected(self, project_id: int, wallet_id: int | None = None) -> None:
        """Synchronize detected wallet participation from activities table."""
        stmt = (
            select(
                Activity.wallet_id,
                func.count(Activity.id).label("cnt"),
                func.min(Activity.occurred_at).label("first_at"),
                func.max(Activity.occurred_at).label("last_at"),
            )
            .where(Activity.project_id == project_id)
            .group_by(Activity.wallet_id)
        )
        if wallet_id is not None:
            stmt = stmt.where(Activity.wallet_id == wallet_id)

        rows = self.session.execute(stmt).all()
        detected_wallet_ids = set()
        for w_id, cnt, first_at, last_at in rows:
            detected_wallet_ids.add(w_id)
            pw = self.session.execute(
                select(ProjectWallet).where(
                    ProjectWallet.project_id == project_id,
                    ProjectWallet.wallet_id == w_id,
                )
            ).scalar_one_or_none()
            if pw is None:
                pw = ProjectWallet(
                    project_id=project_id,
                    wallet_id=w_id,
                    source="detected",
                    interactions_count=cnt or 0,
                    first_interaction_at=first_at,
                    last_interaction_at=last_at,
                )
                self.session.add(pw)
            else:
                pw.source = "detected"
                pw.interactions_count = cnt or 0
                pw.first_interaction_at = first_at
                pw.last_interaction_at = last_at

        if wallet_id is None:
            all_pws = self.session.execute(
                select(ProjectWallet).where(ProjectWallet.project_id == project_id)
            ).scalars().all()
            for pw in all_pws:
                if pw.wallet_id not in detected_wallet_ids:
                    pw.interactions_count = 0

        self.session.flush()

    def link_wallet(
        self,
        project_id: int,
        wallet_id: int,
        source: str = "manual",
    ) -> ProjectWallet:
        """Link wallet to project without duplicating detected rows.

        Source becomes manual only if it was not already detected; detected wins.
        """
        project = self.get(project_id)
        if project is None:
            raise ValueError(f"Project with id {project_id} not found")

        wallet = self.session.get(Wallet, wallet_id)
        if wallet is None:
            raise ValueError(f"Wallet with id {wallet_id} not found")

        self._sync_detected(project_id, wallet_id=wallet_id)

        pw = self.session.execute(
            select(ProjectWallet).where(
                ProjectWallet.project_id == project_id,
                ProjectWallet.wallet_id == wallet_id,
            )
        ).scalar_one_or_none()

        if pw is not None:
            if pw.source != "detected":
                pw.source = source
        else:
            pw = ProjectWallet(
                project_id=project_id,
                wallet_id=wallet_id,
                source=source,
                interactions_count=0,
            )
            self.session.add(pw)

        self.session.flush()
        return pw

    def detected_wallets(self, project_id: int) -> list[ProjectWallet]:
        """Return all wallets detected from synced activities for this project."""
        project = self.get(project_id)
        if project is None:
            raise ValueError(f"Project with id {project_id} not found")

        self._sync_detected(project_id)

        stmt = (
            select(ProjectWallet)
            .where(
                ProjectWallet.project_id == project_id,
                ProjectWallet.source == "detected",
            )
            .order_by(ProjectWallet.wallet_id.asc())
        )
        return list(self.session.execute(stmt).scalars().all())

    def add_task(
        self,
        project_id: int,
        title: str,
        wallet_id: int | None = None,
        status: str = "todo",
    ) -> ProjectTask:
        """Add user task for project, optionally associating with a wallet."""
        project = self.get(project_id)
        if project is None:
            raise ValueError(f"Project with id {project_id} not found")

        if not isinstance(title, str) or not title.strip():
            raise ValueError("Task title cannot be empty")

        if wallet_id is not None:
            wallet = self.session.get(Wallet, wallet_id)
            if wallet is None:
                raise ValueError(f"Wallet with id {wallet_id} not found")

            # Link wallet with source='task' if not already tracked
            self._sync_detected(project_id, wallet_id=wallet_id)
            pw = self.session.execute(
                select(ProjectWallet).where(
                    ProjectWallet.project_id == project_id,
                    ProjectWallet.wallet_id == wallet_id,
                )
            ).scalar_one_or_none()
            if pw is None:
                pw = ProjectWallet(
                    project_id=project_id,
                    wallet_id=wallet_id,
                    source="task",
                    interactions_count=0,
                )
                self.session.add(pw)
                self.session.flush()

        task = ProjectTask(
            project_id=project.id,
            wallet_id=wallet_id,
            title=title.strip(),
            status=status.strip() if status else "todo",
            completed_at=utc_now() if status == "done" else None,
        )
        self.session.add(task)
        self.session.flush()
        return task

    def complete_task(self, task_id: int) -> ProjectTask:
        """Mark project task as done and record completion timestamp."""
        task = self.session.get(ProjectTask, task_id)
        if task is None:
            raise ValueError(f"Task with id {task_id} not found")

        task.status = "done"
        task.completed_at = utc_now()
        self.session.flush()
        return task

    def participation_report(self, project_id: int) -> dict[str, Any]:
        """Generate participation report with wallets, tasks counters, and interactions."""
        project = self.get(project_id)
        if project is None:
            raise ValueError(f"Project with id {project_id} not found")

        self._sync_detected(project_id)

        pws = list(
            self.session.execute(
                select(ProjectWallet)
                .where(ProjectWallet.project_id == project_id)
                .order_by(ProjectWallet.wallet_id.asc())
            ).scalars().all()
        )

        total_interactions = self.session.execute(
            select(func.count(Activity.id)).where(Activity.project_id == project_id)
        ).scalar_one() or 0

        tasks_total = self.session.execute(
            select(func.count(ProjectTask.id)).where(ProjectTask.project_id == project_id)
        ).scalar_one() or 0

        tasks_done = self.session.execute(
            select(func.count(ProjectTask.id)).where(
                ProjectTask.project_id == project_id,
                ProjectTask.status == "done",
            )
        ).scalar_one() or 0

        return {
            "wallets": [
                {
                    "wallet_id": pw.wallet_id,
                    "source": pw.source,
                    "interactions": pw.interactions_count,
                }
                for pw in pws
            ],
            "tasks_total": tasks_total,
            "tasks_done": tasks_done,
            "interactions": total_interactions,
        }
