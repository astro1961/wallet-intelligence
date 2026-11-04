"""Network management and configuration seeding."""
from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from app.database.models import Network

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from app.config import AppConfig


def ensure_networks_from_config(session: Session, cfg: AppConfig) -> int:
    """Create missing Network rows from cfg.networks and return count of created networks.

    Matches existing networks case-insensitively by name or by (chain_type, chain_id).
    Idempotent: returns 0 if all networks in cfg already exist.
    """
    if not cfg.networks:
        return 0

    existing_networks = list(session.execute(select(Network)).scalars().all())
    existing_names = {n.name.lower() for n in existing_networks}
    existing_chain_ids = {
        (n.chain_type.lower(), n.chain_id) for n in existing_networks if n.chain_id is not None
    }

    created_count = 0
    for net_cfg in cfg.networks:
        name_key = net_cfg.name.strip().lower()
        chain_type = getattr(net_cfg, "chain_type", None) or getattr(net_cfg, "type", "evm") or "evm"
        chain_key = (
            (chain_type.strip().lower(), net_cfg.chain_id)
            if net_cfg.chain_id is not None
            else None
        )

        if name_key in existing_names or (chain_key and chain_key in existing_chain_ids):
            continue

        network = Network(
            name=net_cfg.name.strip(),
            chain_type=chain_type.strip(),
            chain_id=net_cfg.chain_id,
            rpc_url=str(net_cfg.rpc_url) if net_cfg.rpc_url else None,
            explorer_url=str(net_cfg.explorer_url) if net_cfg.explorer_url else None,
            native_token=getattr(net_cfg, "native_token", None) or "ETH",
            symbol=getattr(net_cfg, "symbol", None) or getattr(net_cfg, "native_token", None) or "ETH",
            decimals=getattr(net_cfg, "decimals", None) or 18,
            enabled=net_cfg.enabled,
            is_testnet=getattr(net_cfg, "is_testnet", False),
        )
        session.add(network)
        existing_names.add(name_key)
        if chain_key:
            existing_chain_ids.add(chain_key)
        created_count += 1

    if created_count > 0:
        session.flush()

    return created_count
