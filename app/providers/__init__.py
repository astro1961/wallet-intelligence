"""Data providers module."""
from __future__ import annotations

from app.providers.base import (
    DataProvider,
    ProviderResult,
    ProviderStatus,
    TransactionItem,
    TransactionListResult,
)
from app.providers.blockscout import BlockscoutProvider
from app.providers.defillama import DefiLlamaProvider
from app.providers.evm_rpc import EvmRpcProvider
from app.providers.factory import build_default_registry, create_provider_registry
from app.providers.registry import ProviderRegistry
from app.providers.rpc_failover import RpcFailoverProvider
from app.providers.solana import SolanaProvider

__all__ = [
    "BlockscoutProvider",
    "DataProvider",
    "DefiLlamaProvider",
    "EvmRpcProvider",
    "ProviderRegistry",
    "ProviderResult",
    "ProviderStatus",
    "RpcFailoverProvider",
    "SolanaProvider",
    "TransactionItem",
    "TransactionListResult",
    "build_default_registry",
    "create_provider_registry",
]
