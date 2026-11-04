"""Database engine, session management, and initialization."""
from __future__ import annotations

import os
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.config import AppConfig, load_config
from app.database.models import Base

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def create_engine_for(cfg: AppConfig) -> Engine:
    """Create a SQLAlchemy Engine with foreign key enforcement and connection settings."""
    db_path = cfg.database.path
    url = f"sqlite:///{db_path}"

    engine = create_engine(
        url,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


def init_db(cfg: AppConfig | None = None) -> Engine:
    """Initialize SQLite database, directories, and schema (idempotent)."""
    global _engine, _session_factory

    if cfg is None:
        cfg = load_config()

    os.environ["WIT_DB_PATH"] = cfg.database.path

    db_file = Path(cfg.database.path)
    if db_file.parent and str(db_file.parent) != ".":
        db_file.parent.mkdir(parents=True, exist_ok=True)

    _engine = create_engine_for(cfg)
    _session_factory = sessionmaker(bind=_engine, expire_on_commit=False)

    # Prefer programmatic alembic migration, fallback to Base.metadata.create_all
    migrated = False
    alembic_ini_path = Path("alembic.ini")
    if alembic_ini_path.is_file():
        try:
            from alembic import command
            from alembic.config import Config

            alembic_cfg = Config(str(alembic_ini_path))
            alembic_cfg.set_main_option("sqlalchemy.url", f"sqlite:///{cfg.database.path}")
            command.upgrade(alembic_cfg, "head")
            migrated = True
        except (ImportError, OSError, Exception):  # noqa: BLE001
            migrated = False

    if not migrated:
        Base.metadata.create_all(_engine)

    return _engine


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """Context manager for database sessions: commit on success, rollback on error, always close."""
    if _session_factory is None:
        init_db()

    assert _session_factory is not None
    session = _session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
