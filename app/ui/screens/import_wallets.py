"""Batch wallet import screen with format detection, preview, and background workers."""
from __future__ import annotations

from collections.abc import Iterable
from contextlib import suppress
from pathlib import Path
from typing import Any

from sqlalchemy import select
from textual import work
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.widget import Widget
from textual.widgets import Button, DataTable, Input, Label, Select, Static, TextArea

from app.core.import_manager import ImportManager, ImportPreview, ImportReport
from app.database.models import WalletGroup
from app.database.session import session_scope
from app.ui.screens.base import BaseAppScreen


class ImportScreen(BaseAppScreen):
    """Screen for importing wallet addresses in batches from CSV, TXT, and JSON files."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("id", "import")
        super().__init__(*args, **kwargs)
        self.raw_text: str = ""
        self.current_preview: ImportPreview | None = None
        self.last_report: ImportReport | None = None

    @property
    def session_factory(self):
        if hasattr(self.app, "state") and self.app.state and self.app.state.session_factory:
            return self.app.state.session_factory
        from app.config import load_config
        from app.database.session import init_db, session_factory
        return session_factory(init_db(load_config()))

    def compose_content(self) -> Iterable[Widget]:
        yield Label("📥 Import Wallets", classes="screen-title")
        yield Static(
            "Batch import wallet addresses from CSV, TXT, and JSON files with deduplication.",
            classes="screen-desc",
        )
        yield Static(
            "Stage 2: file format auto-detection, address validation, deduplication, and background workers.",
            classes="screen-stage",
        )

        with Vertical(id="import-container"):
            with Horizontal(id="import-file-bar"):
                yield Input(placeholder="Path to import file (optional)...", id="file-path")
                yield Button("Load File", id="load-file-btn")

            yield TextArea(id="import-text")

            with Horizontal(id="import-options-bar"):
                yield Select(
                    [("Format: Auto", "auto"), ("Format: CSV", "csv"), ("Format: TXT", "txt"), ("Format: JSON", "json")],
                    value="auto",
                    id="format-select",
                    allow_blank=False,
                )
                yield Select(
                    [("Default Group: None", -1)],
                    value=-1,
                    id="default-group",
                    allow_blank=False,
                )
                yield Select(
                    [("Mode: Add Only", "add_only"), ("Mode: Update Existing", "update")],
                    value="add_only",
                    id="mode-select",
                    allow_blank=False,
                )

            with Horizontal(id="import-buttons-bar"):
                yield Button("Preview", variant="primary", id="preview-btn")
                yield Button("Apply", variant="success", id="apply-btn")

            yield Label("0 new / 0 duplicates / 0 errors", id="counts-line")
            yield Label("", id="report-line")

            table = DataTable(id="preview-table")
            table.cursor_type = "row"
            yield table

    def on_mount(self) -> None:
        super().on_mount()
        with suppress(NoMatches):
            table = self.query_one("#preview-table", DataTable)
            if not table.columns:
                table.add_columns("Status", "Address", "Name", "Group", "Network", "Tags", "Error")
            if self.raw_text:
                self.query_one("#import-text", TextArea).text = self.raw_text
        self._refresh_group_options()

    def _refresh_group_options(self) -> None:
        with suppress(NoMatches, Exception), session_scope(self.session_factory) as session:
            groups = list(session.execute(select(WalletGroup).order_by(WalletGroup.name.asc())).scalars().all())
            options: list[tuple[str, int | str]] = [("Default Group: None", -1)]
            for g in groups:
                options.append((g.name, g.id))
            self.query_one("#default-group", Select).set_options(options)

    def set_text(self, text: str) -> None:
        """Set import text directly into raw_text and text area."""
        self.raw_text = text
        with suppress(NoMatches):
            self.query_one("#import-text", TextArea).text = text

    @work(thread=True)
    def _preview_worker(self, text: str, fmt: str | None, group_id: int | None) -> ImportPreview:
        """Run preview in a background thread worker for large inputs."""
        with session_scope(self.session_factory) as session:
            im = ImportManager(session)
            return im.preview(text, fmt=fmt, default_group_id=group_id)

    async def do_preview(self) -> None:
        """Build ImportPreview without writing to the database and update preview table."""
        text = self.raw_text
        with suppress(NoMatches):
            area_text = self.query_one("#import-text", TextArea).text
            if area_text:
                text = area_text

        fmt: str | None = None
        with suppress(NoMatches):
            f_select = self.query_one("#format-select", Select)
            if f_select and f_select.value not in ("auto", Select.BLANK):
                fmt = str(f_select.value)

        group_id: int | None = None
        with suppress(NoMatches):
            g_select = self.query_one("#default-group", Select)
            if g_select and g_select.value not in (-1, "none", Select.BLANK):
                with suppress(ValueError, TypeError):
                    group_id = int(g_select.value)

        line_count = len(text.splitlines())
        if line_count >= 2000:
            preview_btn = None
            old_label = "Preview"
            with suppress(NoMatches):
                preview_btn = self.query_one("#preview-btn", Button)
                old_label = str(preview_btn.label)
                preview_btn.label = "⠋ Previewing..."
                preview_btn.disabled = True

            try:
                worker = self._preview_worker(text, fmt, group_id)
                self.current_preview = await worker.wait()
            finally:
                if preview_btn is not None:
                    preview_btn.label = old_label
                    preview_btn.disabled = False
        else:
            with session_scope(self.session_factory) as session:
                im = ImportManager(session)
                self.current_preview = im.preview(text, fmt=fmt, default_group_id=group_id)

        self._render_preview()

    def _render_preview(self) -> None:
        if self.current_preview is None:
            return

        with suppress(NoMatches):
            counts_lbl = self.query_one("#counts-line", Label)
            counts_lbl.update(
                f"{self.current_preview.new_count} new / "
                f"{self.current_preview.duplicate_count} duplicates / "
                f"{self.current_preview.error_count} errors"
            )

            table = self.query_one("#preview-table", DataTable)
            if not table.columns:
                table.add_columns("Status", "Address", "Name", "Group", "Network", "Tags", "Error")
            table.clear()
            for row in self.current_preview.rows:
                table.add_row(
                    row.status,
                    row.address,
                    row.name or "—",
                    row.group or "—",
                    row.network or "—",
                    ", ".join(row.tags) if row.tags else "—",
                    row.error or "—",
                )

    async def do_apply(self) -> None:
        """Apply current preview to database according to chosen mode and update report."""
        if self.current_preview is None:
            await self.do_preview()
        if self.current_preview is None:
            return

        mode = "add_only"
        with suppress(NoMatches):
            mode_select = self.query_one("#mode-select", Select)
            if mode_select and mode_select.value not in (Select.BLANK, None):
                mode = str(mode_select.value)

        with session_scope(self.session_factory) as session:
            im = ImportManager(session)
            report = im.apply(self.current_preview, mode=mode)
            self.last_report = report

        with suppress(NoMatches):
            report_text = f"Added: {report.added} / Updated: {report.updated} / Skipped: {report.skipped} / Errors: {len(report.errors)}"
            if report.errors:
                first_err = report.errors[0].error or "Unknown error"
                report_text += f" (Sample: {first_err})"
            self.query_one("#report-line", Label).update(report_text)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "preview-btn":
            self.run_worker(self.do_preview())
        elif event.button.id == "apply-btn":
            self.run_worker(self.do_apply())
        elif event.button.id == "load-file-btn":
            path_input = self.query_one("#file-path", Input).value.strip()
            if path_input:
                file_p = Path(path_input)
                if file_p.is_file():
                    try:
                        content = file_p.read_text(encoding="utf-8")
                        self.set_text(content)
                        self.notify(f"Loaded {len(content)} bytes from {file_p.name}", title="File Loaded")
                    except OSError as e:
                        self.notify(f"Failed to read file: {e}", title="Error", severity="error")
                else:
                    self.notify(f"File not found: {path_input}", title="File Not Found", severity="error")
