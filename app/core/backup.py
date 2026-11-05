"""SQLite database backup, restore, and integrity verification."""
from __future__ import annotations

import hashlib
import logging
import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from urllib.request import pathname2url

from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)


@contextmanager
def _get_connection(engine: Any) -> Generator[sqlite3.Connection, None, None]:
    """Yield an underlying sqlite3.Connection from various engine/connection representations."""
    if hasattr(engine, "get_bind"):
        engine = engine.get_bind()

    if isinstance(engine, sqlite3.Connection):
        yield engine
    elif isinstance(engine, (str, Path)):
        path_str = str(engine)
        if path_str.startswith("sqlite:///"):
            path_str = path_str.removeprefix("sqlite:///")
        conn = sqlite3.connect(path_str)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()
    elif hasattr(engine, "connect"):
        # SQLAlchemy Engine
        with engine.connect() as sa_conn:
            dbapi = getattr(sa_conn.connection, "driver_connection", None)
            if dbapi is None:
                dbapi = getattr(sa_conn.connection, "connection", sa_conn.connection)
            yield dbapi
            sa_conn.commit()
    elif hasattr(engine, "connection"):
        # SQLAlchemy Connection
        inner = engine.connection
        dbapi = getattr(inner, "driver_connection", None)
        if dbapi is None:
            dbapi = getattr(inner, "connection", inner)
        yield dbapi
        if hasattr(engine, "commit"):
            engine.commit()
    elif hasattr(engine, "raw_connection"):
        raw = engine.raw_connection()
        try:
            dbapi = getattr(raw, "driver_connection", None)
            if dbapi is None:
                dbapi = getattr(raw, "connection", raw)
            yield dbapi
            raw.commit()
        finally:
            raw.close()
    else:
        raise TypeError(f"Unsupported database or engine type: {type(engine)!r}")


def backup_database(engine: Any, dest_path: str | Path) -> dict[str, Any]:
    """Create a consistent snapshot of the live SQLite database at dest_path via the SQLite Backup API.

    Returns:
        dict: {"sha256": hex, "size_bytes": int, "table_count": int, "path": str}
    """
    dest_path_str = str(dest_path)
    dest_file = Path(dest_path).resolve()
    dest_file.parent.mkdir(parents=True, exist_ok=True)
    if dest_file.exists():
        dest_file.unlink()

    dest_conn = sqlite3.connect(str(dest_file))
    try:
        with _get_connection(engine) as live_conn:
            live_conn.backup(dest_conn)
        dest_conn.commit()
        cursor = dest_conn.execute(
            "SELECT count(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
        row = cursor.fetchone()
        table_count = int(row[0]) if row else 0
        cursor.close()
    finally:
        dest_conn.close()

    sha256_hash = hashlib.sha256()
    with open(dest_file, "rb") as f:
        while chunk := f.read(65536):
            sha256_hash.update(chunk)

    sha256_hex = sha256_hash.hexdigest()
    size_bytes = dest_file.stat().st_size

    return {
        "sha256": sha256_hex,
        "size_bytes": size_bytes,
        "table_count": table_count,
        "path": dest_path_str,
    }


def verify_backup_file(path: str | Path) -> bool:
    """Return True iff path is a readable SQLite DB whose PRAGMA integrity_check is 'ok'."""
    try:
        p = Path(path)
        if not p.is_file():
            return False
        # Valid SQLite 3 database header is at least 100 bytes
        if p.stat().st_size < 100:
            return False
        # Check SQLite 3 16-byte magic header
        with open(p, "rb") as f:
            header = f.read(16)
            if header != b"SQLite format 3\x00":
                return False

        url_path = pathname2url(str(p.resolve()))
        conn = sqlite3.connect(f"file:{url_path}?mode=ro", uri=True)
        try:
            cursor = conn.execute("PRAGMA integrity_check")
            rows = cursor.fetchall()
            cursor.close()
            return len(rows) == 1 and str(rows[0][0]).strip().lower() == "ok"
        finally:
            conn.close()
    except (sqlite3.Error, OSError) as exc:
        logger.warning("Backup file verification failed for %s: %s", path, exc)
        return False


def restore_database(engine: Any, src_path: str | Path) -> None:
    """Restore database from backup file, replacing the live database so subsequent reads see the backed-up state.

    Raises:
        ValueError: If src_path is non-existent, not a SQLite DB, or corrupted.
    """
    if not verify_backup_file(src_path):
        raise ValueError(f"Invalid or corrupt backup file: {src_path}")

    src_file = Path(src_path).resolve()
    url_path = pathname2url(str(src_file))
    src_conn = sqlite3.connect(f"file:{url_path}?mode=ro", uri=True)
    try:
        with _get_connection(engine) as live_conn:
            src_conn.backup(live_conn)
            live_conn.commit()
            try:
                live_conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except sqlite3.Error as exc:
                logger.debug("WAL checkpoint truncate skipped/failed: %s", exc)
    finally:
        src_conn.close()

    if hasattr(engine, "expire_all"):
        engine.expire_all()

    if hasattr(engine, "dispose") and hasattr(engine, "url"):
        db_name = engine.url.database
        if db_name and db_name != ":memory:" and not db_name.startswith(":memory:"):
            engine.dispose()


def verify_database(engine: Any) -> bool:
    """Run PRAGMA integrity_check on the database and return True only on 'ok'."""
    try:
        with _get_connection(engine) as conn:
            cursor = conn.execute("PRAGMA integrity_check")
            rows = cursor.fetchall()
            cursor.close()
            return len(rows) == 1 and str(rows[0][0]).strip().lower() == "ok"
    except (sqlite3.Error, SQLAlchemyError, OSError) as exc:
        logger.warning("Database verification failed: %s", exc)
        return False
