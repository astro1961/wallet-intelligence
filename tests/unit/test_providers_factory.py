"""Unit tests for provider registry factory and configuration wiring."""
from __future__ import annotations

from app.config import AppConfig, NetworkConfig, ProviderSection
from app.providers.blockscout import BlockscoutProvider
from app.providers.etherscan import EtherscanProvider
from app.providers.factory import create_provider_registry


def test_factory_with_blockscout_key(monkeypatch):
    monkeypatch.setenv("TEST_BS_KEY", "real-bs-key")
    cfg = AppConfig(
        providers={
            "blockscout": ProviderSection(
                enabled=True,
                api_key_env="TEST_BS_KEY",
                base_url="https://api.blockscout.com",
            ),
            "defillama": ProviderSection(
                enabled=True,
                base_url="https://coins.llama.fi",
            ),
        },
        networks=[
            NetworkConfig(name="Ethereum", type="evm", chain_id=1, rpc_url="https://rpc.example"),
        ],
    )

    reg = create_provider_registry(cfg)
    names = [p.name for p in reg.providers]
    assert "blockscout" in names
    assert "evm_rpc" in names
    assert "defillama" in names

    bs = reg.get_provider("blockscout")
    assert isinstance(bs, BlockscoutProvider)
    assert bs.api_key == "real-bs-key"


def test_factory_missing_key_disables_with_warning(monkeypatch):
    monkeypatch.delenv("MISSING_BS_KEY", raising=False)
    cfg = AppConfig(
        providers={
            "blockscout": ProviderSection(
                enabled=True,
                api_key_env="MISSING_BS_KEY",
                base_url="https://api.blockscout.com",
            ),
            "defillama": ProviderSection(
                enabled=True,
                base_url="https://coins.llama.fi",
            ),
        },
        networks=[],
    )

    warnings: list[str] = []
    from app.providers.factory import logger as factory_logger

    def record_warning(msg: str, *args: object) -> None:
        warnings.append(msg % args if args else msg)

    monkeypatch.setattr(factory_logger, "warning", record_warning)
    reg = create_provider_registry(cfg)

    names = [p.name for p in reg.providers]
    assert "blockscout" not in names
    assert "defillama" in names
    assert any("MISSING_BS_KEY" in w for w in warnings)


def test_factory_disabled_provider_is_skipped():
    cfg = AppConfig(
        providers={
            "blockscout": ProviderSection(enabled=False),
            "defillama": ProviderSection(enabled=False),
        },
        networks=[],
    )

    reg = create_provider_registry(cfg)
    assert len(reg.providers) == 0


def test_factory_with_etherscan_key_after_blockscout(monkeypatch):
    monkeypatch.setenv("TEST_BS_KEY", "real-bs-key")
    monkeypatch.setenv("TEST_ES_KEY", "real-es-key")
    cfg = AppConfig(
        providers={
            "blockscout": ProviderSection(
                enabled=True,
                api_key_env="TEST_BS_KEY",
                base_url="https://api.blockscout.com",
            ),
            "etherscan": ProviderSection(
                enabled=True,
                api_key_env="TEST_ES_KEY",
                base_url="https://api.etherscan.io/v2/api",
            ),
            "defillama": ProviderSection(
                enabled=True,
                base_url="https://coins.llama.fi",
            ),
        },
        networks=[],
    )

    reg = create_provider_registry(cfg)
    names = [p.name for p in reg.providers]
    assert "blockscout" in names
    assert "etherscan" in names
    assert names.index("blockscout") < names.index("etherscan")

    es = reg.get_provider("etherscan")
    assert isinstance(es, EtherscanProvider)
    assert es.api_key == "real-es-key"


def test_factory_missing_etherscan_key_disables_with_warning(monkeypatch):
    monkeypatch.delenv("MISSING_ES_KEY", raising=False)
    cfg = AppConfig(
        providers={
            "etherscan": ProviderSection(
                enabled=True,
                api_key_env="MISSING_ES_KEY",
                base_url="https://api.etherscan.io/v2/api",
            ),
        },
        networks=[],
    )

    warnings: list[str] = []
    from app.providers.factory import logger as factory_logger

    def record_warning(msg: str, *args: object) -> None:
        warnings.append(msg % args if args else msg)

    monkeypatch.setattr(factory_logger, "warning", record_warning)
    reg = create_provider_registry(cfg)

    names = [p.name for p in reg.providers]
    assert "etherscan" not in names
    assert any("MISSING_ES_KEY" in w for w in warnings)
