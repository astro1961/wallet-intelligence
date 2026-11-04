"""Main entry point for Wallet Intelligence Tracker."""
from __future__ import annotations

import argparse
import os
import sys

from app.config import load_config
from app.database.session import init_db
from app.utils.logging import setup_logging


def main(argv: list[str] | None = None) -> None:
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
    init_db(cfg)
    logger.info("Database initialized successfully at: %s", cfg.database.path)

    # Lazy-load Textual UI (Stage 1B)
    try:
        from app.application import WalletIntelligenceApp  # type: ignore

        app = WalletIntelligenceApp(config=cfg)
        app.run()
    except (ImportError, ModuleNotFoundError):
        print("Wallet Intelligence Tracker - Stage 1A initialized successfully.")
        print(f"Database ready at: {cfg.database.path}")
        print("TUI interface (Stage 1B) is not yet implemented. Exiting.")
        sys.exit(0)


if __name__ == "__main__":
    main()
