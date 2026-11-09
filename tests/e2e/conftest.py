"""Pytest fixtures для E2E-тестов (Textual headless).

Изоляция: каждая фикстура даёт чистую SQLite-БД в tmp_path и выставляет
WIT_DB_PATH, чтобы миграции накатывались с нуля.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest


@pytest.fixture
def clean_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Чистая тестовая БД на прогон; удаляется до старта."""
    db_path = tmp_path / "test.db"
    if db_path.exists():
        db_path.unlink()
    monkeypatch.setenv("WIT_DB_PATH", str(db_path))
    yield db_path
    if db_path.exists():
        db_path.unlink()


@pytest.fixture
def app_env(clean_db: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Дополнительные env-настройки для приложения в тестах."""
    monkeypatch.setenv("WIT_REFRESH_INTERVAL", "3600")  # без фонового автообновления
    monkeypatch.delenv("WIT_CONFIG", raising=False)
    # Гарантируем, что тесты не используют рабочий config.yaml с боевой БД.
    monkeypatch.setenv("WIT_DB_PATH", str(clean_db))
    return clean_db


@pytest.fixture(autouse=True)
def _no_real_secrets() -> Iterator[None]:
    """Ensure no real provider keys leak into tests."""
    original = {k: v for k, v in os.environ.items() if k.endswith("_API_KEY")}
    for key in original:
        os.environ.pop(key, None)
    yield
    os.environ.update(original)
