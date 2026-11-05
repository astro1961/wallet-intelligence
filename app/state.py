"""Application global and reactive runtime state."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import Engine
from sqlalchemy.orm import sessionmaker

from app.config import AppConfig


@dataclass
class AppState:
    """Runtime state container for the Wallet Intelligence Tracker application."""

    config: AppConfig | None = None
    engine: Engine | None = None
    session_factory: sessionmaker | None = None
    sync_state: Literal["idle", "syncing", "paused"] = "idle"
    last_update: datetime | None = None
    filters: dict[str, Any] = field(default_factory=dict)
    active_screen: str = "dashboard"
    providers: Any | None = None  # ProviderRegistry injected by the app or by tests
