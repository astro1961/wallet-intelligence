"""Alembic environment configuration."""
from __future__ import annotations

from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, event, pool

from app.config import load_config
from app.database.models import Base

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Set DB URL dynamically from config (honouring existing main_option and WIT_DB_PATH)
existing_url = config.get_main_option("sqlalchemy.url")
if existing_url:
    db_path = existing_url.replace("sqlite:///", "")
    db_file = Path(db_path)
    if db_file.parent and str(db_file.parent) != ".":
        db_file.parent.mkdir(parents=True, exist_ok=True)
else:
    app_cfg = load_config()
    db_file = Path(app_cfg.database.path)
    if db_file.parent and str(db_file.parent) != ".":
        db_file.parent.mkdir(parents=True, exist_ok=True)
    db_url = f"sqlite:///{app_cfg.database.path}"
    config.set_main_option("sqlalchemy.url", db_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(connectable, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
