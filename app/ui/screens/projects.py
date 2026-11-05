"""Projects and testnets catalog screen."""
from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any, ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Button, DataTable, Input, Label, Select, Static
from textual.widgets.data_table import RowDoesNotExist

from app.core.project_manager import ProjectManager
from app.database.session import session_scope
from app.ui.screens.base import BaseAppScreen
from app.utils.formatting import shorten_address

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker

logger = logging.getLogger(__name__)

EMPTY_PROJECTS_MSG = "No projects yet — press a to add one."


class ProjectCreateModal(ModalScreen[tuple[str, str | None, str] | None]):
    """Modal dialog for creating a new project."""

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "cancel", "Cancel"),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal-dialog"):
            yield Label("🚀 Add Project", classes="modal-title")
            yield Label("", id="project-form-error", classes="field-error")
            yield Label("Project Name:", classes="form-label")
            yield Input(id="project-name-input", placeholder="e.g. Uniswap or LayerZero")
            yield Label("Category (optional):", classes="form-label")
            yield Input(id="project-category-input", placeholder="e.g. defi, layer2, nft")
            yield Label("Status:", classes="form-label")
            yield Select(
                [("Active", "active"), ("Completed", "completed"), ("Archived", "archived")],
                value="active",
                id="project-status-select",
            )
            with Horizontal(classes="modal-buttons"):
                yield Button("Create", variant="primary", id="create-project-btn")
                yield Button("Cancel", variant="default", id="cancel-project-btn")

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "create-project-btn":
            name = self.query_one("#project-name-input", Input).value.strip()
            if not name:
                self.query_one("#project-form-error", Label).update("Project name cannot be empty.")
                return
            category = self.query_one("#project-category-input", Input).value.strip() or None
            status_val = self.query_one("#project-status-select", Select).value
            status = str(status_val) if status_val != Select.BLANK else "active"
            self.dismiss((name, category, status))
        elif event.button.id == "cancel-project-btn":
            self.dismiss(None)


class ProjectsScreen(BaseAppScreen):
    """Screen for tracking crypto projects, testnet participations, and checklists."""

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("a", "add_project", "Add Project"),
    ]

    def __init__(
        self,
        *args: Any,
        session_factory: sessionmaker[Session] | None = None,
        **kwargs: Any,
    ) -> None:
        kwargs.setdefault("id", "projects")
        super().__init__(*args, **kwargs)
        self._session_factory = session_factory
        self.status_filter: str | None = None
        self.category_filter: str | None = None
        self.selected_project_id: int | None = None
        self._projects_rows: list[str] = []
        self._participation_text: str = ""
        self._loaded: bool = False
        self._ignore_next_highlight_on_filter_reset: bool = False

    def _get_session_factory(self) -> sessionmaker[Session] | None:
        if self._session_factory is not None:
            return self._session_factory
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
        """Compose table, filter bar, and participation panel."""
        yield Label("🚀 Projects & Testnets", classes="screen-title")
        yield Static(
            "Directory of crypto projects, testnets, smart contracts, and task checklists.",
            classes="screen-desc",
        )
        yield Static(
            "Stage 5: Project catalog, per-network contracts, and wallet participation tracker.",
            classes="screen-stage",
        )

        with Horizontal(id="projects-filter-row", classes="filters-bar"):
            yield Label("Filters:", classes="filter-title")
            yield Label(f"[Status: {self.status_filter or 'All'}]", id="filter-status", classes="filter-badge")
            yield Label(f"[Category: {self.category_filter or 'All'}]", id="filter-category", classes="filter-badge")

        table = DataTable(id="projects-table")
        table.cursor_type = "row"
        yield table

        yield Static(
            EMPTY_PROJECTS_MSG,
            id="empty-state",
        )

        with Vertical(id="participation-box", classes="panel-box"):
            yield Label("Participation", classes="section-subtitle")
            yield Static(self.participation_text, id="participation-panel")

    def on_mount(self) -> None:
        super().on_mount()
        self._ensure_table_columns()
        self.refresh_data()

    def _ensure_table_columns(self) -> None:
        try:
            table = self.query_one("#projects-table", DataTable)
            if not table.columns:
                table.add_column("Name", key="name")
                table.add_column("Category", key="category")
                table.add_column("Status", key="status")
                table.add_column("Contracts", key="contracts")
                table.add_column("Wallets", key="wallets")
                table.add_column("Tasks done/total", key="tasks")
        except NoMatches:
            logger.debug("projects-table not present in DOM during column setup")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Error setting up table columns: %s", exc)

    def refresh_data(self) -> None:
        """(Re)load catalog from DB."""
        self._loaded = True
        session_fact = self._get_session_factory()
        if session_fact is None:
            self._projects_rows = []
            self._update_views([])
            return

        projects_data: list[tuple[Any, int, dict[str, Any]]] = []
        rows: list[str] = []

        try:
            with session_scope(session_fact) as session:
                pm = ProjectManager(session)
                projects = pm.list_projects(
                    status=self.status_filter,
                    category=self.category_filter,
                    newest_first=True,
                )
                for p in projects:
                    contracts = pm.list_contracts(p.id)
                    rep = pm.participation_report(p.id)
                    contracts_cnt = len(contracts)
                    wallets_cnt = len(rep.get("wallets", []))
                    tasks_done = rep.get("tasks_done", 0)
                    tasks_total = rep.get("tasks_total", 0)

                    cat_str = p.category or "—"
                    row_str = (
                        f"{p.name} · {cat_str} · {p.status} · "
                        f"{contracts_cnt} · {wallets_cnt} · {tasks_done}/{tasks_total}"
                    )
                    rows.append(row_str)
                    projects_data.append((p, contracts_cnt, rep))

                self._projects_rows = rows
        except Exception as exc:  # noqa: BLE001
            logger.warning("Error refreshing projects data: %s", exc)
            self._projects_rows = []
            projects_data = []

        self._update_views(projects_data)

        visible_ids = {p.id for p, _, _ in projects_data}
        if self.selected_project_id is not None:
            if self.selected_project_id in visible_ids:
                self.show_participation(self.selected_project_id)
            else:
                self.reset_participation()
                self._ignore_next_highlight_on_filter_reset = bool(visible_ids)
        else:
            self.reset_participation()

    def reset_participation(self) -> None:
        """Reset participation panel to neutral empty state."""
        self.selected_project_id = None
        self._participation_text = ""
        for target_id in ("#participation-panel", "#participation-text"):
            try:
                self.query_one(target_id, Static).update(self._participation_text)
            except NoMatches:
                logger.debug("Widget %s not found in DOM", target_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Error updating %s widget: %s", target_id, exc)

    def _update_views(self, projects_data: list[tuple[Any, int, dict[str, Any]]]) -> None:
        try:
            st_lbl = self.query_one("#filter-status", Label)
            st_lbl.update(f"[Status: {self.status_filter or 'All'}]")
        except NoMatches:
            logger.debug("#filter-status not in DOM")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Error updating #filter-status: %s", exc)

        try:
            cat_lbl = self.query_one("#filter-category", Label)
            cat_lbl.update(f"[Category: {self.category_filter or 'All'}]")
        except NoMatches:
            logger.debug("#filter-category not in DOM")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Error updating #filter-category: %s", exc)

        has_items = len(projects_data) > 0
        try:
            empty_state = self.query_one("#empty-state", Static)
            empty_state.display = not has_items
        except NoMatches:
            logger.debug("#empty-state not in DOM")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Error updating #empty-state: %s", exc)

        try:
            table = self.query_one("#projects-table", DataTable)
            table.display = has_items
            table.clear()
            for p, contracts_cnt, rep in projects_data:
                table.add_row(
                    p.name,
                    p.category or "—",
                    p.status,
                    str(contracts_cnt),
                    str(len(rep.get("wallets", []))),
                    f"{rep.get('tasks_done', 0)}/{rep.get('tasks_total', 0)}",
                    key=str(p.id),
                )
        except NoMatches:
            logger.debug("#projects-table not in DOM")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Error updating #projects-table: %s", exc)

    @property
    def projects_text(self) -> str:
        """Rendered catalog as text."""
        if not self._loaded and self._get_session_factory() is not None:
            self.refresh_data()
        if not self._projects_rows:
            return EMPTY_PROJECTS_MSG
        return "\n".join(self._projects_rows)

    @property
    def participation_text(self) -> str:
        """Rendered participation report."""
        return self._participation_text

    def set_status_filter(self, status: str | None) -> None:
        """Filter projects by status or restore all if None."""
        self.status_filter = status
        self.refresh_data()

    def set_category_filter(self, category: str | None) -> None:
        """Filter projects by category or restore all if None."""
        self.category_filter = category
        self.refresh_data()

    def show_participation(self, project_id: int) -> None:
        """Fill participation_text with wallet details and counters for the given project."""
        self.selected_project_id = project_id
        session_fact = self._get_session_factory()
        if session_fact is None:
            self._participation_text = ""
            return

        try:
            with session_scope(session_fact) as session:
                pm = ProjectManager(session)
                project = pm.get(project_id)
                if project is None:
                    self._participation_text = ""
                    return

                report = pm.participation_report(project_id)
                wallets_count = len(report.get("wallets", []))
                tasks_done = report.get("tasks_done", 0)
                tasks_total = report.get("tasks_total", 0)
                interactions = report.get("interactions", 0)

                lines: list[str] = [
                    f"Project: {project.name} ({project.status})",
                    f"Wallets: {wallets_count}  Tasks: {tasks_done}/{tasks_total}  Interactions: {interactions}",
                ]

                for w_info in report.get("wallets", []):
                    w_id = w_info.get("wallet_id")
                    wallet = pm.get_wallet(w_id)
                    w_name = (
                        wallet.name
                        if (wallet and wallet.name)
                        else (wallet.address if (wallet and wallet.address) else "—")
                    )
                    w_addr = shorten_address(wallet.address) if (wallet and wallet.address) else "—"
                    src = w_info.get("source", "detected")
                    cnt = w_info.get("interactions", 0)
                    lines.append(f"- {w_name} ({w_addr}) · source: {src} · interactions: {cnt}")

                self._participation_text = "\n".join(lines)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Error fetching participation for project %s: %s", project_id, exc)
            self._participation_text = ""

        for target_id in ("#participation-panel", "#participation-text"):
            try:
                self.query_one(target_id, Static).update(self._participation_text)
            except NoMatches:
                logger.debug("Widget %s not found in DOM", target_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Error updating %s widget: %s", target_id, exc)

        # Move table cursor to the project's row (Option A)
        try:
            table = self.query_one("#projects-table", DataTable)
            row_key_str = str(project_id)
            if row_key_str in table.rows:
                row_idx = table.get_row_index(row_key_str)
                if table.cursor_row != row_idx:
                    table.move_cursor(row=row_idx)
            else:
                logger.debug("Project %s row not in table (filtered out)", project_id)
        except NoMatches:
            logger.debug("projects-table not present in DOM during show_participation")
        except RowDoesNotExist as exc:
            logger.debug("Row %s does not exist in table: %s", project_id, exc)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Error moving table cursor for project %s: %s", project_id, exc)

    def create_project(
        self,
        name: str,
        category: str | None = None,
        status: str = "active",
    ) -> int:
        """Insert a Project row through ProjectManager and return its id."""
        session_fact = self._get_session_factory()
        if session_fact is None:
            self._notify_error("Database session unavailable")
            return -1

        try:
            with session_scope(session_fact) as session:
                pm = ProjectManager(session)
                project = pm.create_project(name=name, category=category, status=status)
                new_id = project.id
        except ValueError as exc:
            logger.warning("Project creation error: %s", exc)
            self._notify_error(str(exc), title="Duplicate Project")
            return -1
        except Exception as exc:
            logger.exception("Unexpected error creating project '%s'", name)
            self._notify_error(f"Error: {exc}", title="Project Creation Failed")
            return -1

        self.refresh_data()
        return new_id

    def _notify_error(self, message: str, title: str = "Error") -> None:
        """Surface error as a notification without crashing."""
        try:
            self.notify(message, title=title, severity="error")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to display notification: %s", exc)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Handle user selecting a row in the catalog table."""
        if event.row_key and event.row_key.value:
            try:
                p_id = int(event.row_key.value)
                self.show_participation(p_id)
            except (ValueError, TypeError) as exc:
                logger.warning("Invalid project row key: %s", exc)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        """Update participation view when cursor moves over a row."""
        if event.cursor_row != event.data_table.cursor_row:
            logger.debug(
                "Skipping stale RowHighlighted event: event row %s != table cursor row %s",
                event.cursor_row,
                event.data_table.cursor_row,
            )
            return

        if self._ignore_next_highlight_on_filter_reset:
            self._ignore_next_highlight_on_filter_reset = False
            return

        if event.row_key and event.row_key.value:
            try:
                p_id = int(event.row_key.value)
                self.show_participation(p_id)
            except (ValueError, TypeError) as exc:
                logger.warning("Invalid project row key: %s", exc)

    def action_add_project(self) -> None:
        """Open Add Project modal dialog."""

        def _on_modal_close(result: tuple[str, str | None, str] | None) -> None:
            if result:
                name, cat, status = result
                self.create_project(name=name, category=cat, status=status)

        try:
            self.app.push_screen(ProjectCreateModal(), _on_modal_close)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not open ProjectCreateModal: %s", exc)

    def action_add_wallet(self) -> None:
        """Alias for hotkey 'a' dispatch from application."""
        self.action_add_project()
