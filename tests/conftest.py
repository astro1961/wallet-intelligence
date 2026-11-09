"""Pytest fixtures for unit and integration tests."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

import app.database.session as session_mod


@pytest.fixture(scope="session")
def schema_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build one migrated database file per session via alembic upgrade head."""
    template_dir = tmp_path_factory.mktemp("schema_template")
    template_path = template_dir / "template.db"
    alembic_cfg = Config("alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", f"sqlite:///{template_path}")
    command.upgrade(alembic_cfg, "head")
    return template_path


@pytest.fixture(scope="session", autouse=True)
def setup_schema_template(schema_template: Path) -> None:
    """Register the template with the session module and environment."""
    session_mod.set_schema_template(schema_template)
    os.environ["WIT_DB_TEMPLATE"] = str(schema_template)
    yield
    session_mod.set_schema_template(None)
    os.environ.pop("WIT_DB_TEMPLATE", None)


@pytest.fixture
def migrated_db(schema_template: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Provide a fresh isolated copy of the migrated database for a single test."""
    db_file = tmp_path / "test.db"
    shutil.copyfile(schema_template, db_file)
    monkeypatch.setenv("WIT_DB_PATH", str(db_file))
    return db_file


# Экраны Activities/Projects/DeFi/Networks/Graph/Import/Settings отключены —
# оставлены только Dashboard и Wallets. Тесты этих экранов пропускаются.
_DISABLED_SCREEN_TEST_FILES = {
    "test_stage4b.py",
    "test_stage5b.py",
    "test_stage5c.py",
    "test_stage6.py",
    "test_stage7a.py",
    "test_stage8.py",
    "test_ui_import.py",
    "test_data_screens.py",
    "test_import.py",
}


def pytest_collection_modifyitems(config: pytest.Config, items: list) -> None:
    """Skip tests that cover disabled screens."""
    for item in items:
        if any(name in str(item.path) for name in _DISABLED_SCREEN_TEST_FILES):
            item.add_marker(
                pytest.mark.skip(reason="Screen disabled: only Dashboard/Wallets remain")
            )
