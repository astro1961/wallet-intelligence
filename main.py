"""Main entry point for Wallet Intelligence Tracker."""
from __future__ import annotations

import argparse
import os
import sys

from app.application import WalletTrackerApp
from app.config import load_config
from app.core.network_manager import ensure_networks_from_config
from app.database.session import init_db, session_factory, session_scope
from app.utils.logging import setup_logging


def main(argv: list[str] | None = None) -> int:
    """Parse CLI options, configure logging, initialize database, and launch app."""
    parser = argparse.ArgumentParser(
        prog="wallet-intelligence",
        description="Wallet Intelligence Tracker - Local crypto wallet and on-chain intelligence manager.",
    )
    parser.add_argument("--config", type=str, default=None, help="Path to config.yaml")
    parser.add_argument("--db", type=str, default=None, help="Path to SQLite database file")
    parser.add_argument(
        "--log-level",
        type=str,
        default=os.environ.get("LOG_LEVEL", "INFO"),
        help="Logging level (DEBUG, INFO, WARNING, ERROR)",
    )
    parser.add_argument(
        "--version",
        action="version",
        version="Wallet Intelligence Tracker 0.1.0",
    )

    args = parser.parse_args(argv)

    # Setup logging
    logger = setup_logging(level=args.log_level)
    logger.info("Initializing Wallet Intelligence Tracker...")

    # Load configuration
    cfg = load_config(args.config)
    if args.db:
        cfg.database.path = args.db

    # Initialize database
    engine = init_db(cfg)
    logger.info("Database initialized successfully at: %s", cfg.database.path)

    # Seed networks from config
    with session_scope(session_factory(engine)) as session:
        ensure_networks_from_config(session, cfg)

    # Launch Textual TUI
    app = WalletTrackerApp(config=cfg)
    result = app.run()
    return int(result or 0)


if __name__ == "__main__":
    sys.exit(main())
