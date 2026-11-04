"""Configuration models and loader for Wallet Intelligence Tracker."""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, model_validator

logger = logging.getLogger(__name__)


class ConfigBaseModel(BaseModel):
    """Base model that allows extra attributes without failing."""

    model_config = ConfigDict(extra="allow")


class AppSection(ConfigBaseModel):
    name: str = "Wallet Intelligence Tracker"
    refresh_interval_seconds: int = 300
    timezone: str = "UTC"


class DatabaseSection(ConfigBaseModel):
    path: str = "data/wallet_tracker.db"


class ProviderSection(ConfigBaseModel):
    enabled: bool = True
    api_key_env: str | None = None
    base_url: str | None = None


class NetworkConfig(ConfigBaseModel):
    name: str
    type: str = "evm"
    chain_id: int | None = None
    enabled: bool = True
    rpc_url: str | None = None
    explorer_url: str | None = None


class AppConfig(ConfigBaseModel):
    app: AppSection = Field(default_factory=AppSection)
    database: DatabaseSection = Field(default_factory=DatabaseSection)
    providers: dict[str, ProviderSection] = Field(default_factory=dict)
    networks: list[NetworkConfig] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def capture_unknown_keys(cls, data: Any) -> Any:
        if isinstance(data, dict):
            known_keys = {"app", "database", "providers", "networks", "extra"}
            extra = dict(data.get("extra", {}))
            for k, v in data.items():
                if k not in known_keys:
                    extra[k] = v
            data["extra"] = extra
        return data


def load_config(path: str | Path | None = None) -> AppConfig:
    """Load configuration from YAML file and apply environment variable overrides."""
    load_dotenv()

    config_path: Path
    if path is not None:
        config_path = Path(path)
    elif os.environ.get("WIT_CONFIG"):
        config_path = Path(os.environ["WIT_CONFIG"])
    else:
        config_path = Path("config.yaml")

    raw_data: dict[str, Any] = {}
    if config_path.is_file():
        with open(config_path, "r", encoding="utf-8") as f:
            loaded = yaml.safe_load(f)
            if isinstance(loaded, dict):
                raw_data = loaded

    # Apply environment variable overrides
    if "WIT_DB_PATH" in os.environ:
        if "database" not in raw_data or not isinstance(raw_data["database"], dict):
            raw_data["database"] = {}
        raw_data["database"]["path"] = os.environ["WIT_DB_PATH"]

    if "WIT_REFRESH_INTERVAL" in os.environ:
        if "app" not in raw_data or not isinstance(raw_data["app"], dict):
            raw_data["app"] = {}
        val_str = os.environ["WIT_REFRESH_INTERVAL"]
        try:
            raw_data["app"]["refresh_interval_seconds"] = int(val_str)
        except ValueError as exc:
            logger.warning(
                "Invalid WIT_REFRESH_INTERVAL '%s': %s. Keeping default.",
                val_str,
                exc,
            )

    return AppConfig(**raw_data)
