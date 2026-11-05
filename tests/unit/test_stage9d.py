"""Unit tests for Stage 9D: database backup, restore, and integrity verification."""
from __future__ import annotations

import ast
import hashlib
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.backup import (
    backup_database,
    restore_database,
    verify_backup_file,
    verify_database,
)
from app.database.models import Wallet


def _compute_file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


@pytest.fixture
def temp_db_file(tmp_path: Path) -> Path:
    db_path = tmp_path / "live.db"
    eng = create_engine(f"sqlite:///{db_path}")
    with eng.begin() as conn:
        conn.execute(text("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT)"))
        conn.execute(text("INSERT INTO items (name) VALUES ('item_1'), ('item_2')"))
        conn.execute(text("CREATE TABLE metadata (key TEXT PRIMARY KEY, val TEXT)"))
        conn.execute(text("INSERT INTO metadata (key, val) VALUES ('v', '1.0.0')"))
    eng.dispose()
    return db_path


def test_backup_database_creates_snapshot_with_matching_sha256(temp_db_file: Path, tmp_path: Path):
    dest = tmp_path / "backup_sub" / "snapshot.db"
    eng = create_engine(f"sqlite:///{temp_db_file}")

    result = backup_database(eng, dest)
    eng.dispose()

    assert isinstance(result, dict)
    assert set(result.keys()) == {"sha256", "size_bytes", "table_count", "path"}
    assert result["path"] == str(dest)
    assert result["table_count"] == 2
    assert result["size_bytes"] == dest.stat().st_size
    assert isinstance(result["size_bytes"], int)
    assert isinstance(result["table_count"], int)

    expected_sha256 = _compute_file_sha256(dest)
    assert result["sha256"] == expected_sha256

    # Verify backup contains valid data
    dest_eng = create_engine(f"sqlite:///{dest}")
    with dest_eng.connect() as conn:
        rows = conn.execute(text("SELECT name FROM items ORDER BY id")).fetchall()
        assert [r[0] for r in rows] == ["item_1", "item_2"]
    dest_eng.dispose()


def test_backup_database_with_string_path_and_overwrite(temp_db_file: Path, tmp_path: Path):
    dest_str = str(tmp_path / "existing.db")
    Path(dest_str).write_bytes(b"previous_content_not_even_sqlite")

    eng = create_engine(f"sqlite:///{temp_db_file}")
    res = backup_database(eng, dest_str)
    eng.dispose()

    assert res["path"] == dest_str
    assert res["sha256"] == _compute_file_sha256(Path(dest_str))
    assert verify_backup_file(dest_str) is True


def test_backup_database_from_connection_and_session(tmp_path: Path):
    eng = create_engine("sqlite:///:memory:", poolclass=StaticPool)
    with eng.begin() as conn:
        conn.execute(text("CREATE TABLE tokens (id INT, symbol TEXT)"))
        conn.execute(text("INSERT INTO tokens VALUES (1, 'ETH'), (2, 'SOL')"))

    dest1 = tmp_path / "from_conn.db"
    with eng.connect() as conn:
        res1 = backup_database(conn, dest1)
    assert res1["table_count"] == 1
    assert verify_backup_file(dest1) is True

    dest2 = tmp_path / "from_session.db"
    with Session(bind=eng) as session:
        res2 = backup_database(session, dest2)
    assert res2["table_count"] == 1
    assert verify_backup_file(dest2) is True


def test_restore_database_reverts_to_backup_state(temp_db_file: Path, tmp_path: Path):
    dest_backup = tmp_path / "saved.db"
    eng = create_engine(f"sqlite:///{temp_db_file}")

    # Snapshot state: items has 2 rows, metadata has 1 row
    backup_database(eng, dest_backup)

    # Mutate live DB: add 3rd item, add extra table
    with eng.begin() as conn:
        conn.execute(text("INSERT INTO items (name) VALUES ('item_3')"))
        conn.execute(text("CREATE TABLE new_table (x INT)"))
        conn.execute(text("INSERT INTO new_table VALUES (999)"))

    # Check live DB is mutated
    with eng.connect() as conn:
        item_count = conn.execute(text("SELECT count(*) FROM items")).scalar()
        assert item_count == 3
        tables = [
            r[0]
            for r in conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            ).fetchall()
        ]
        assert "new_table" in tables

    # Restore from backup
    restore_database(eng, dest_backup)

    # Reads must see restored state
    with eng.connect() as conn:
        items = conn.execute(text("SELECT name FROM items ORDER BY id")).fetchall()
        assert [r[0] for r in items] == ["item_1", "item_2"]
        tables_after = [
            r[0]
            for r in conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            ).fetchall()
        ]
        assert "new_table" not in tables_after

    eng.dispose()


def test_restore_database_rejects_corrupt_and_non_sqlite_files(temp_db_file: Path, tmp_path: Path):
    eng = create_engine(f"sqlite:///{temp_db_file}")

    # 1. Non-existent file
    with pytest.raises(ValueError, match="Invalid or corrupt"):
        restore_database(eng, tmp_path / "missing.db")

    # 2. Empty file (0 bytes)
    empty_file = tmp_path / "empty.db"
    empty_file.touch()
    with pytest.raises(ValueError, match="Invalid or corrupt"):
        restore_database(eng, empty_file)

    # 3. Plain text file
    text_file = tmp_path / "not_sqlite.txt"
    text_file.write_text("Hello, this is not a database.")
    with pytest.raises(ValueError, match="Invalid or corrupt"):
        restore_database(eng, text_file)

    # 4. Corrupted SQLite file (valid header but garbled b-tree)
    corrupt_file = tmp_path / "corrupt.db"
    corrupt_file.write_bytes(b"SQLite format 3\x00" + b"\x00" * 84 + b"\xff" * 200)
    with pytest.raises(ValueError, match="Invalid or corrupt"):
        restore_database(eng, corrupt_file)

    # Live DB remains untouched
    with eng.connect() as conn:
        items = conn.execute(text("SELECT name FROM items ORDER BY id")).fetchall()
        assert len(items) == 2

    eng.dispose()


def test_restore_database_with_wal_mode(tmp_path: Path):
    db_path = tmp_path / "wal_live.db"
    eng = create_engine(f"sqlite:///{db_path}")

    with eng.begin() as conn:
        conn.execute(text("PRAGMA journal_mode=WAL"))
        conn.execute(text("CREATE TABLE txs (hash TEXT PRIMARY KEY, amount INT)"))
        conn.execute(text("INSERT INTO txs VALUES ('0x1', 100)"))

    bak_path = tmp_path / "wal_snap.db"
    backup_database(eng, bak_path)

    # Mutate in WAL mode
    with eng.begin() as conn:
        conn.execute(text("INSERT INTO txs VALUES ('0x2', 200)"))

    # Restore
    restore_database(eng, bak_path)

    with eng.connect() as conn:
        hashes = [
            r[0]
            for r in conn.execute(text("SELECT hash FROM txs ORDER BY amount")).fetchall()
        ]
        assert hashes == ["0x1"]

    eng.dispose()


def test_verify_database_integrity_check(temp_db_file: Path, tmp_path: Path):
    eng = create_engine(f"sqlite:///{temp_db_file}")
    assert verify_database(eng) is True

    # Test with connection
    with eng.connect() as conn:
        assert verify_database(conn) is True

    eng.dispose()

    # Corrupt the file on disk
    corrupt_db = tmp_path / "corrupt_live.db"
    corrupt_db.write_bytes(b"SQLite format 3\x00" + b"\x00" * 84 + b"\xff" * 300)
    corrupt_eng = create_engine(f"sqlite:///{corrupt_db}")
    assert verify_database(corrupt_eng) is False
    corrupt_eng.dispose()


def test_verify_backup_file_valid_and_invalid(temp_db_file: Path, tmp_path: Path):
    # Valid DB
    assert verify_backup_file(temp_db_file) is True

    # Non-existent
    assert verify_backup_file(tmp_path / "nonexistent.db") is False

    # Directory
    assert verify_backup_file(tmp_path) is False

    # Empty
    empty_file = tmp_path / "zero.db"
    empty_file.touch()
    assert verify_backup_file(empty_file) is False

    # Text file
    txt_file = tmp_path / "sample.txt"
    txt_file.write_text("not a db")
    assert verify_backup_file(txt_file) is False

    # Corrupt SQLite header/body
    bad_db = tmp_path / "bad.db"
    bad_db.write_bytes(b"SQLite format 3\x00" + b"\x00" * 84 + b"\xaa" * 128)
    assert verify_backup_file(bad_db) is False


def test_full_migrated_db_backup_and_restore(migrated_db: Path, tmp_path: Path):
    eng = create_engine(f"sqlite:///{migrated_db}")
    bak = tmp_path / "full_app.bak"

    res = backup_database(eng, bak)
    assert res["table_count"] == 24
    assert res["sha256"] == _compute_file_sha256(bak)
    assert verify_backup_file(bak) is True

    # Mutate migrated DB
    with Session(bind=eng) as s:
        w = Wallet(address="0x" + "a" * 40, chain_type="evm", name="MigratedWallet")
        s.add(w)
        s.commit()

    with Session(bind=eng) as s:
        assert len(s.execute(select(Wallet)).scalars().all()) == 1

    restore_database(eng, bak)

    with Session(bind=eng) as s:
        assert len(s.execute(select(Wallet)).scalars().all()) == 0

    eng.dispose()


def test_no_float_hygiene():
    src = Path("app/core/backup.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, float):
            pytest.fail(f"Found float constant {node.value} in app/core/backup.py")
        if isinstance(node, ast.Name) and node.id == "float":
            pytest.fail("Found 'float' identifier in app/core/backup.py")


def test_no_ui_imports_hygiene():
    src = Path("app/core/backup.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                for forbidden in ("textual", "rich", "app.ui"):
                    if alias.name.startswith(forbidden):
                        pytest.fail(f"Forbidden import in core: {alias.name}")
        elif isinstance(node, ast.ImportFrom) and node.module:
            for forbidden in ("textual", "rich", "app.ui"):
                if node.module.startswith(forbidden):
                    pytest.fail(f"Forbidden import in core: {node.module}")


def test_no_silent_except_pass():
    src = Path("app/core/backup.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.ExceptHandler)
            and len(node.body) == 1
            and isinstance(node.body[0], ast.Pass)
        ):
            pytest.fail("Found silent 'except: pass' in app/core/backup.py")


def test_no_env_or_secret_access():
    src = Path("app/core/backup.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if "dotenv" in alias.name:
                    pytest.fail(f"Backup module must not import dotenv: {alias.name}")
        elif isinstance(node, ast.ImportFrom) and node.module:
            if "dotenv" in node.module:
                pytest.fail(f"Backup module must not import dotenv: {node.module}")
        elif (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "os"
            and node.attr == "environ"
        ):
            pytest.fail("Backup module must not access os.environ")
    assert ".env" not in src, "Backup module must not reference .env"
