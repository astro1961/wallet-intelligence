"""Provider factory and configuration wiring."""
from __future__ import annotations

import logging
import os

from app.config import AppConfig, load_config
from app.providers.base import DataProvider
from app.providers.blockscout import BlockscoutProvider
from app.providers.defillama import DefiLlamaProvider
from app.providers.etherscan import EtherscanProvider
from app.providers.evm_rpc import EvmRpcProvider
from app.providers.registry import ProviderRegistry

logger = logging.getLogger(__name__)


def create_provider_registry(cfg: AppConfig | None = None) -> ProviderRegistry:
    """Build ProviderRegistry from application configuration.

    Reads API keys safely from environment variables specified in config.
    Missing keys disable the respective provider with a warning rather than raising.
    """
    if cfg is None:
        cfg = load_config()

    providers: list[DataProvider] = []

    # 1. Blockscout Provider
    bs_cfg = cfg.providers.get("blockscout")
    if bs_cfg and bs_cfg.enabled:
        api_key: str | None = None
        if bs_cfg.api_key_env:
            api_key = os.getenv(bs_cfg.api_key_env)
            if not api_key:
                logger.warning(
                    "Blockscout provider disabled: environment variable '%s' not set",
                    bs_cfg.api_key_env,
                )

        if not bs_cfg.api_key_env or api_key:
            base_url = bs_cfg.base_url or "https://api.blockscout.com"
            providers.append(
                BlockscoutProvider(
                    api_key=api_key,
                    base_url=base_url,
                    chain_id=1,
                )
            )

    # 2. Etherscan Provider (failover)
    es_cfg = cfg.providers.get("etherscan")
    if es_cfg and es_cfg.enabled:
        es_key_env = es_cfg.api_key_env or "ETHERSCAN_API_KEY"
        es_api_key = os.getenv(es_key_env)
        if not es_api_key:
            logger.warning(
                "Etherscan provider disabled: environment variable '%s' not set",
                es_key_env,
            )
        else:
            es_base_url = es_cfg.base_url or "https://api.etherscan.io/v2/api"
            providers.append(
                EtherscanProvider(
                    api_key=es_api_key,
                    base_url=es_base_url,
                    default_chain_id=1,
                )
            )

    # 3. EVM JSON-RPC Provider
    # Look for first EVM network with an RPC URL configured
    rpc_url: str | None = None
    for net in cfg.networks:
        if net.enabled and net.rpc_url and (getattr(net, "type", "evm") or "evm") == "evm":
            rpc_url = str(net.rpc_url)
            break

    if not rpc_url:
        rpc_cfg = cfg.providers.get("evm_rpc")
        if rpc_cfg and rpc_cfg.enabled and rpc_cfg.base_url:
            rpc_url = rpc_cfg.base_url

    if rpc_url:
        providers.append(EvmRpcProvider(rpc_url=rpc_url))

    # 3. DeFiLlama Provider
    dl_cfg = cfg.providers.get("defillama")
    if dl_cfg and dl_cfg.enabled:
        base_url = dl_cfg.base_url or "https://coins.llama.fi"
        providers.append(DefiLlamaProvider(base_url=base_url))

    return ProviderRegistry(providers)


# Alias
build_default_registry = create_provider_registry
