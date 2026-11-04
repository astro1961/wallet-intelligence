"""Unit tests for configuration loading and validation."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from app.config import (
    AppConfig,
    AppSection,
    DatabaseSection,
    NetworkConfig,
    ProviderSection,
    load_config,
)


def test_config_models_defaults():
    app_sec = AppSection(name="Test Tracker")
    assert app_sec.name == "Test Tracker"
    assert app_sec.refresh_interval_seconds == 300
    assert app_sec.timezone == "UTC"

    db_sec = DatabaseSection()
    assert db_sec.path == "data/wallet_tracker.db"

    prov_sec = ProviderSection()
    assert prov_sec.enabled is True
    assert prov_sec.api_key_env is None

    net_cfg = NetworkConfig(name="Ethereum", chain_id=1)
    assert net_cfg.name == "Ethereum"
    assert net_cfg.type == "evm"
    assert net_cfg.chain_id == 1
    assert net_cfg.enabled is True


def test_load_config_default_file():
    cfg = load_config()
    assert isinstance(cfg, AppConfig)
    assert "Wallet Intelligence" in cfg.app.name
    assert cfg.database.path == "data/wallet_tracker.db"
    assert len(cfg.networks) >= 7
    assert "etherscan" in cfg.providers
    assert cfg.providers["etherscan"].api_key_env == "ETHERSCAN_API_KEY"


def test_load_config_env_overrides(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    custom_db = tmp_path / "custom.db"
    monkeypatch.setenv("WIT_DB_PATH", str(custom_db))
    monkeypatch.setenv("WIT_REFRESH_INTERVAL", "600")

    cfg = load_config()
    assert cfg.database.path == str(custom_db)
    assert cfg.app.refresh_interval_seconds == 600


def test_load_config_custom_path_and_wit_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    custom_yaml = tmp_path / "custom_config.yaml"
    custom_yaml.write_text(
        yaml.safe_dump(
            {
                "app": {"name": "Custom Tracker", "refresh_interval_seconds": 120},
                "database": {"path": "custom/db.sqlite"},
                "unknown_key": "some_value",
            }
        ),
        encoding="utf-8",
    )

    # Via direct path argument
    cfg1 = load_config(custom_yaml)
    assert cfg1.app.name == "Custom Tracker"
    assert cfg1.app.refresh_interval_seconds == 120
    assert cfg1.database.path == "custom/db.sqlite"
    assert cfg1.extra.get("unknown_key") == "some_value"

    # Via WIT_CONFIG env var
    monkeypatch.setenv("WIT_CONFIG", str(custom_yaml))
    cfg2 = load_config()
    assert cfg2.app.name == "Custom Tracker"


def test_unknown_keys_do_not_crash():
    raw_data = {
        "app": {"name": "Test", "extra_subfield": 123},
        "database": {"path": "test.db", "another_unknown": "abc"},
        "future_section": {"enabled": True},
    }
    cfg = AppConfig(**raw_data)
    assert cfg.app.name == "Test"
    assert cfg.extra.get("future_section") == {"enabled": True}
