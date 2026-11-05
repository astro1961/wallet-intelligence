"""RPC endpoint and network management."""
from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import httpx
from sqlalchemy import func, select

from app.database.models import Network, RpcEndpoint, utc_now
from app.providers.base import ProviderResult, ProviderStatus

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

_ALLOWED_CHAIN_TYPES: frozenset[str] = frozenset({"evm", "solana"})
_ALLOWED_EDIT_FIELDS: frozenset[str] = frozenset({
    "name",
    "chain_type",
    "chain_id",
    "rpc_url",
    "explorer_url",
    "native_token",
    "symbol",
    "decimals",
    "is_testnet",
    "enabled",
})


class RpcManager:
    """Session-based manager for custom networks and their RPC endpoints."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def _resolve_network(self, network: Network | int | str) -> Network:
        """Resolve Network instance from Network object, id, or name."""
        if isinstance(network, Network):
            if network in self.session:
                return network
            if network.id is not None:
                net = self.session.get(Network, network.id)
                if net is not None:
                    return net
            return network

        if isinstance(network, int) and not isinstance(network, bool):
            net = self.session.get(Network, network)
            if net is None:
                raise ValueError(f"Network with id {network} not found")
            return net

        if isinstance(network, str):
            name_clean = network.strip()
            stmt = select(Network).where(func.lower(Network.name) == name_clean.lower())
            net = self.session.execute(stmt).scalar_one_or_none()
            if net is None:
                raise ValueError(f"Network '{network}' not found")
            return net

        raise TypeError(f"Expected Network, int, or str, got {type(network).__name__}")

    def _get_rpc_url(self, network: Network) -> str | None:
        """Find the active RPC URL for a network: primary endpoint, network.rpc_url, or first endpoint."""
        stmt = (
            select(RpcEndpoint)
            .where(
                RpcEndpoint.network_id == network.id,
                RpcEndpoint.is_primary.is_(True),
            )
        )
        primary = self.session.execute(stmt).scalars().first()
        if primary and primary.url:
            return primary.url

        if network.rpc_url:
            return network.rpc_url

        endpoints = self.list_rpc_endpoints(network)
        if endpoints:
            return endpoints[0].url

        return None

    def _record_health(self, network: Network, url: str, healthy: bool) -> None:
        """Update is_healthy and last_checked_at on matching endpoint."""
        endpoint = self.session.execute(
            select(RpcEndpoint).where(
                RpcEndpoint.network_id == network.id,
                RpcEndpoint.url == url,
            )
        ).scalar_one_or_none()
        if endpoint is not None:
            endpoint.is_healthy = healthy
            endpoint.last_checked_at = utc_now()
            self.session.flush()

    def add_network(
        self,
        name: str,
        chain_type: str = "evm",
        chain_id: int | None = None,
        rpc_url: str | None = None,
        explorer_url: str | None = None,
        native_token: str = "ETH",
        symbol: str | None = None,
        decimals: int = 18,
        is_testnet: bool = False,
        enabled: bool = True,
    ) -> Network:
        """Add a custom blockchain network.

        Validates:
        - chain_type in closed set ('evm', 'solana')
        - duplicate name (case-insensitive) raises ValueError
        - duplicate (chain_type, chain_id) raises ValueError
        - chain_id required for evm, optional for solana
        - sane defaults for decimals/symbol/native_token
        """
        if not name or not isinstance(name, str) or not name.strip():
            raise ValueError("Network name must be a non-empty string")
        name_clean = name.strip()

        if not chain_type or not isinstance(chain_type, str):
            raise ValueError("chain_type must be a string")
        ct_clean = chain_type.strip().lower()
        if ct_clean not in _ALLOWED_CHAIN_TYPES:
            raise ValueError(f"Invalid chain_type '{chain_type}'. Must be 'evm' or 'solana'")

        if ct_clean == "evm" and chain_id is None:
            raise ValueError("chain_id is required for evm networks")

        if chain_id is not None:
            if not isinstance(chain_id, int) or isinstance(chain_id, bool):
                raise TypeError("chain_id must be an integer")
            if chain_id <= 0:
                raise ValueError("chain_id must be a positive integer")

        if not isinstance(decimals, int) or isinstance(decimals, bool):
            raise TypeError("decimals must be an integer")
        if decimals < 0:
            raise ValueError("decimals must be a non-negative integer")

        # Duplicate name check (case-insensitive)
        existing_name = self.session.execute(
            select(Network).where(func.lower(Network.name) == name_clean.lower())
        ).scalar_one_or_none()
        if existing_name is not None:
            raise ValueError(f"Network with name '{name_clean}' already exists")

        # Duplicate (chain_type, chain_id) check
        if chain_id is not None:
            existing_chain = self.session.execute(
                select(Network).where(
                    func.lower(Network.chain_type) == ct_clean,
                    Network.chain_id == chain_id,
                )
            ).scalar_one_or_none()
            if existing_chain is not None:
                raise ValueError(
                    f"Network with chain_type '{ct_clean}' and chain_id {chain_id} already exists"
                )

        # Sane defaults for decimals / symbol / native_token
        if ct_clean == "solana":
            tok = "SOL" if (native_token == "ETH" or not native_token) else native_token
            sym = symbol or tok
            dec = decimals if decimals != 18 else 9
        else:
            tok = native_token or "ETH"
            sym = symbol or tok
            dec = decimals if decimals is not None else 18

        network = Network(
            name=name_clean,
            chain_type=ct_clean,
            chain_id=chain_id,
            rpc_url=rpc_url.strip() if rpc_url else None,
            explorer_url=explorer_url.strip() if explorer_url else None,
            native_token=tok,
            symbol=sym,
            decimals=dec,
            is_testnet=is_testnet,
            enabled=enabled,
        )
        self.session.add(network)
        self.session.flush()
        return network

    def edit_network(self, network: Network | int | str, **fields: Any) -> Network:
        """Edit fields on an existing network."""
        net = self._resolve_network(network)

        for key in fields:
            if key not in _ALLOWED_EDIT_FIELDS:
                raise ValueError(f"Invalid field: {key}")

        if "name" in fields:
            new_name = fields["name"]
            if not new_name or not isinstance(new_name, str) or not new_name.strip():
                raise ValueError("Network name cannot be empty")
            new_name = new_name.strip()
            existing = self.session.execute(
                select(Network).where(
                    func.lower(Network.name) == new_name.lower(),
                    Network.id != net.id,
                )
            ).scalar_one_or_none()
            if existing is not None:
                raise ValueError(f"Network with name '{new_name}' already exists")
            net.name = new_name

        if "chain_type" in fields:
            new_ct = fields["chain_type"]
            if not new_ct or not isinstance(new_ct, str):
                raise ValueError("chain_type must be a string")
            new_ct = new_ct.strip().lower()
            if new_ct not in _ALLOWED_CHAIN_TYPES:
                raise ValueError(f"Invalid chain_type '{new_ct}'. Must be 'evm' or 'solana'")
            net.chain_type = new_ct

        if "chain_id" in fields:
            new_cid = fields["chain_id"]
            if net.chain_type == "evm" and new_cid is None:
                raise ValueError("chain_id is required for evm networks")
            if new_cid is not None:
                if not isinstance(new_cid, int) or isinstance(new_cid, bool):
                    raise TypeError("chain_id must be an integer")
                if new_cid <= 0:
                    raise ValueError("chain_id must be a positive integer")
                existing = self.session.execute(
                    select(Network).where(
                        func.lower(Network.chain_type) == net.chain_type.lower(),
                        Network.chain_id == new_cid,
                        Network.id != net.id,
                    )
                ).scalar_one_or_none()
                if existing is not None:
                    raise ValueError(
                        f"Network with chain_type '{net.chain_type}' and chain_id {new_cid} already exists"
                    )
            net.chain_id = new_cid
        elif "chain_type" in fields and net.chain_type == "evm" and net.chain_id is None:
            raise ValueError("chain_id is required for evm networks")

        if "decimals" in fields:
            new_dec = fields["decimals"]
            if not isinstance(new_dec, int) or isinstance(new_dec, bool):
                raise TypeError("decimals must be an integer")
            if new_dec < 0:
                raise ValueError("decimals must be a non-negative integer")
            net.decimals = new_dec

        for key in ("rpc_url", "explorer_url", "native_token", "symbol", "is_testnet", "enabled"):
            if key in fields:
                val = fields[key]
                if key in ("rpc_url", "explorer_url") and val is not None:
                    val = str(val).strip()
                setattr(net, key, val)

        self.session.flush()
        return net

    def add_rpc_endpoint(
        self,
        network: Network | int | str,
        url: str,
        priority: int = 1,
        is_primary: bool = False,
        is_backup: bool = False,
    ) -> RpcEndpoint:
        """Add an RPC endpoint to a network with given priority.

        A URL already present for the network is not duplicated.
        """
        net = self._resolve_network(network)
        if not url or not isinstance(url, str) or not url.strip():
            raise ValueError("Endpoint URL cannot be empty")
        url_clean = url.strip()

        if not isinstance(priority, int) or isinstance(priority, bool):
            raise TypeError("priority must be an integer")

        stmt = select(RpcEndpoint).where(
            RpcEndpoint.network_id == net.id,
            RpcEndpoint.url == url_clean,
        )
        existing = self.session.execute(stmt).scalar_one_or_none()
        if existing is not None:
            if is_primary:
                self.set_primary(net, existing.id)
            return existing

        if is_primary:
            all_eps = self.session.execute(
                select(RpcEndpoint).where(RpcEndpoint.network_id == net.id)
            ).scalars().all()
            for ep in all_eps:
                ep.is_primary = False
            net.rpc_url = url_clean

        endpoint = RpcEndpoint(
            network_id=net.id,
            url=url_clean,
            priority=priority,
            is_primary=is_primary,
            is_backup=is_backup,
            is_healthy=True,
        )
        self.session.add(endpoint)
        if net.rpc_url is None:
            net.rpc_url = url_clean
        self.session.flush()
        return endpoint

    def set_primary(self, network: Network | int | str, endpoint_id: int) -> RpcEndpoint:
        """Set exactly one endpoint as primary, clearing previous primary."""
        net = self._resolve_network(network)
        target = self.session.get(RpcEndpoint, endpoint_id)
        if target is None or target.network_id != net.id:
            raise ValueError(f"Endpoint with id {endpoint_id} not found for network '{net.name}'")

        all_eps = self.session.execute(
            select(RpcEndpoint).where(RpcEndpoint.network_id == net.id)
        ).scalars().all()
        for ep in all_eps:
            ep.is_primary = False

        target.is_primary = True
        net.rpc_url = target.url
        self.session.flush()
        return target

    def list_rpc_endpoints(self, network: Network | int | str) -> list[RpcEndpoint]:
        """Return endpoints for network ordered by priority ascending."""
        net = self._resolve_network(network)
        stmt = (
            select(RpcEndpoint)
            .where(RpcEndpoint.network_id == net.id)
            .order_by(RpcEndpoint.priority.asc(), RpcEndpoint.id.asc())
        )
        return list(self.session.execute(stmt).scalars().all())

    def check_chain_id(
        self, network: Network | int | str, client: httpx.Client | None = None
    ) -> ProviderResult:
        """Verify chain_id via eth_chainId JSON-RPC call. Never raises exceptions."""
        try:
            net = self._resolve_network(network)
            url = self._get_rpc_url(net)
            if not url:
                return ProviderResult(
                    status=ProviderStatus.ERROR,
                    error=f"No RPC endpoint available for network '{getattr(net, 'name', network)}'",
                    data=None,
                    source="rpc_manager",
                )

            payload: dict[str, Any] = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "eth_chainId",
                "params": [],
            }

            if client is not None:
                resp = client.post(url, json=payload)
            else:
                with httpx.Client(timeout=10) as temp_client:
                    resp = temp_client.post(url, json=payload)

            if resp.status_code != 200:
                return ProviderResult(
                    status=ProviderStatus.ERROR,
                    error=f"HTTP {resp.status_code}",
                    data=None,
                    source="rpc_manager",
                )

            try:
                data = resp.json()
            except (json.JSONDecodeError, ValueError) as exc:
                return ProviderResult(
                    status=ProviderStatus.ERROR,
                    error=f"Invalid JSON response: {exc}",
                    data=None,
                    source="rpc_manager",
                )

            if not isinstance(data, dict):
                return ProviderResult(
                    status=ProviderStatus.ERROR,
                    error="Malformed JSON response",
                    data=None,
                    source="rpc_manager",
                )

            if "error" in data:
                err = data["error"]
                msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
                return ProviderResult(
                    status=ProviderStatus.ERROR,
                    error=f"RPC error: {msg}",
                    data=None,
                    source="rpc_manager",
                )

            if "result" not in data or data["result"] is None:
                return ProviderResult(
                    status=ProviderStatus.ERROR,
                    error="Missing result in RPC response",
                    data=None,
                    source="rpc_manager",
                )

            raw_result = data["result"]
            if isinstance(raw_result, str):
                parsed_chain_id = int(raw_result, 16)
            elif isinstance(raw_result, int) and not isinstance(raw_result, bool):
                parsed_chain_id = raw_result
            else:
                return ProviderResult(
                    status=ProviderStatus.ERROR,
                    error=f"Invalid chain_id type: {type(raw_result).__name__}",
                    data=None,
                    source="rpc_manager",
                )

            if net.chain_id is not None and parsed_chain_id == net.chain_id:
                return ProviderResult(
                    status=ProviderStatus.OK,
                    data=parsed_chain_id,
                    source="rpc_manager",
                )

            return ProviderResult(
                status=ProviderStatus.ERROR,
                error=f"Chain ID mismatch: expected {net.chain_id}, got {parsed_chain_id}",
                data=parsed_chain_id,
                source="rpc_manager",
            )
        except (httpx.HTTPError, json.JSONDecodeError, ValueError, TypeError, KeyError) as exc:
            return ProviderResult(
                status=ProviderStatus.ERROR,
                error=str(exc),
                data=None,
                source="rpc_manager",
            )
        except Exception as exc:  # noqa: BLE001
            return ProviderResult(
                status=ProviderStatus.ERROR,
                error=str(exc),
                data=None,
                source="rpc_manager",
            )

    def check_connection(
        self, network: Network | int | str, client: httpx.Client | None = None
    ) -> ProviderResult:
        """Check endpoint reachability via eth_blockNumber JSON-RPC call. Never raises exceptions."""
        try:
            net = self._resolve_network(network)
            url = self._get_rpc_url(net)
            if not url:
                return ProviderResult(
                    status=ProviderStatus.ERROR,
                    error=f"No RPC endpoint available for network '{getattr(net, 'name', network)}'",
                    data=None,
                    source="rpc_manager",
                )

            payload: dict[str, Any] = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "eth_blockNumber",
                "params": [],
            }

            if client is not None:
                resp = client.post(url, json=payload)
            else:
                with httpx.Client(timeout=10) as temp_client:
                    resp = temp_client.post(url, json=payload)

            if resp.status_code != 200:
                self._record_health(net, url, healthy=False)
                return ProviderResult(
                    status=ProviderStatus.ERROR,
                    error=f"HTTP {resp.status_code}",
                    data=None,
                    source="rpc_manager",
                )

            try:
                data = resp.json()
            except (json.JSONDecodeError, ValueError) as exc:
                self._record_health(net, url, healthy=False)
                return ProviderResult(
                    status=ProviderStatus.ERROR,
                    error=f"Invalid JSON response: {exc}",
                    data=None,
                    source="rpc_manager",
                )

            if not isinstance(data, dict):
                self._record_health(net, url, healthy=False)
                return ProviderResult(
                    status=ProviderStatus.ERROR,
                    error="Malformed JSON response",
                    data=None,
                    source="rpc_manager",
                )

            if "error" in data:
                self._record_health(net, url, healthy=False)
                err = data["error"]
                msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
                return ProviderResult(
                    status=ProviderStatus.ERROR,
                    error=f"RPC error: {msg}",
                    data=None,
                    source="rpc_manager",
                )

            if "result" not in data or data["result"] is None:
                self._record_health(net, url, healthy=False)
                return ProviderResult(
                    status=ProviderStatus.ERROR,
                    error="Missing result in RPC response",
                    data=None,
                    source="rpc_manager",
                )

            raw_result = data["result"]
            if isinstance(raw_result, str):
                block_num = int(raw_result, 16)
            elif isinstance(raw_result, int) and not isinstance(raw_result, bool):
                block_num = raw_result
            else:
                self._record_health(net, url, healthy=False)
                return ProviderResult(
                    status=ProviderStatus.ERROR,
                    error=f"Invalid blockNumber type: {type(raw_result).__name__}",
                    data=None,
                    source="rpc_manager",
                )

            self._record_health(net, url, healthy=True)
            return ProviderResult(
                status=ProviderStatus.OK,
                data=block_num,
                source="rpc_manager",
            )
        except (httpx.HTTPError, json.JSONDecodeError, ValueError, TypeError, KeyError) as exc:
            if "net" in locals() and "url" in locals() and url and isinstance(net, Network):
                self._record_health(net, url, healthy=False)
            return ProviderResult(
                status=ProviderStatus.ERROR,
                error=str(exc),
                data=None,
                source="rpc_manager",
            )
        except Exception as exc:  # noqa: BLE001
            if "net" in locals() and "url" in locals() and url and isinstance(net, Network):
                self._record_health(net, url, healthy=False)
            return ProviderResult(
                status=ProviderStatus.ERROR,
                error=str(exc),
                data=None,
                source="rpc_manager",
            )
