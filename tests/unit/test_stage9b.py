"""Unit tests for Stage 9B: RpcManager (custom networks and per-network RPC endpoints)."""
from __future__ import annotations

import ast
import json
from pathlib import Path

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.rpc_manager import RpcManager
from app.database.models import Base, Network, RpcEndpoint
from app.providers.base import ProviderStatus


@pytest.fixture
def memory_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def session_factory(memory_db):
    return sessionmaker(bind=memory_db, expire_on_commit=False)


@pytest.fixture
def session(session_factory):
    with session_factory() as s:
        yield s


def test_add_network_evm_success_and_defaults(session: Session):
    mgr = RpcManager(session)
    net = mgr.add_network(
        name="Ethereum",
        chain_type="evm",
        chain_id=1,
        rpc_url="https://eth.llamarpc.com",
    )

    assert net.id is not None
    assert net.name == "Ethereum"
    assert net.chain_type == "evm"
    assert net.chain_id == 1
    assert net.rpc_url == "https://eth.llamarpc.com"
    assert net.native_token == "ETH"
    assert net.symbol == "ETH"
    assert net.decimals == 18
    assert net.enabled is True
    assert net.is_testnet is False


def test_add_network_solana_success_and_defaults(session: Session):
    mgr = RpcManager(session)
    net = mgr.add_network(
        name="Solana Mainnet",
        chain_type="solana",
        chain_id=None,
    )

    assert net.id is not None
    assert net.name == "Solana Mainnet"
    assert net.chain_type == "solana"
    assert net.chain_id is None
    assert net.native_token == "SOL"
    assert net.symbol == "SOL"
    assert net.decimals == 9


def test_add_network_invalid_chain_type(session: Session):
    mgr = RpcManager(session)
    with pytest.raises(ValueError, match="chain_type"):
        mgr.add_network("Bitcoin", chain_type="utxo", chain_id=1)

    with pytest.raises(ValueError):
        mgr.add_network("Tron", chain_type="tron")


def test_add_network_evm_requires_chain_id(session: Session):
    mgr = RpcManager(session)
    with pytest.raises(ValueError, match="chain_id"):
        mgr.add_network("Polygon", chain_type="evm", chain_id=None)


def test_add_network_duplicate_name_case_insensitive(session: Session):
    mgr = RpcManager(session)
    mgr.add_network("Arbitrum One", chain_type="evm", chain_id=42161)

    with pytest.raises(ValueError, match="already exists"):
        mgr.add_network("arbitrum one", chain_type="evm", chain_id=42162)

    with pytest.raises(ValueError, match="already exists"):
        mgr.add_network("  ARBITRUM ONE  ", chain_type="evm", chain_id=42163)


def test_add_network_duplicate_chain_type_and_chain_id(session: Session):
    mgr = RpcManager(session)
    mgr.add_network("Optimism", chain_type="evm", chain_id=10)

    # Different name, but same (chain_type, chain_id)
    with pytest.raises(ValueError, match="already exists"):
        mgr.add_network("OP Mainnet", chain_type="evm", chain_id=10)


def test_add_network_different_chain_types_same_chain_id(session: Session):
    mgr = RpcManager(session)
    evm_net = mgr.add_network("Net EVM", chain_type="evm", chain_id=101)
    sol_net = mgr.add_network("Net Solana", chain_type="solana", chain_id=101)
    assert evm_net.id != sol_net.id


def test_edit_network_success(session: Session):
    mgr = RpcManager(session)
    net = mgr.add_network("Polygon Old", chain_type="evm", chain_id=137)

    updated = mgr.edit_network(
        net,
        name="Polygon PoS",
        native_token="POL",
        symbol="POL",
        rpc_url="https://polygon-rpc.com",
    )
    assert updated.name == "Polygon PoS"
    assert updated.symbol == "POL"
    assert updated.rpc_url == "https://polygon-rpc.com"

    # Reload from session
    reloaded = session.get(Network, net.id)
    assert reloaded is not None
    assert reloaded.name == "Polygon PoS"


def test_edit_network_duplicate_validations(session: Session):
    mgr = RpcManager(session)
    net1 = mgr.add_network("Net1", chain_type="evm", chain_id=1001)
    net2 = mgr.add_network("Net2", chain_type="evm", chain_id=1002)

    # Changing to existing name of another network
    with pytest.raises(ValueError, match="already exists"):
        mgr.edit_network(net2, name="net1")

    # Changing to existing (chain_type, chain_id) of another network
    with pytest.raises(ValueError, match="already exists"):
        mgr.edit_network(net2, chain_id=1001)

    # Editing same network with its own name should succeed
    mgr.edit_network(net1, name="Net1")

    # EVM with None chain_id must fail
    with pytest.raises(ValueError, match="chain_id"):
        mgr.edit_network(net1, chain_id=None)


def test_add_rpc_endpoint_priority_order(session: Session):
    mgr = RpcManager(session)
    net = mgr.add_network("Arbitrum", chain_type="evm", chain_id=42161)

    ep_p3 = mgr.add_rpc_endpoint(net, "https://arb-p3.io", priority=3)
    ep_p1 = mgr.add_rpc_endpoint(net, "https://arb-p1.io", priority=1)
    ep_p2 = mgr.add_rpc_endpoint(net, "https://arb-p2.io", priority=2)

    endpoints = mgr.list_rpc_endpoints(net)
    assert len(endpoints) == 3
    assert [ep.priority for ep in endpoints] == [1, 2, 3]
    assert [ep.id for ep in endpoints] == [ep_p1.id, ep_p2.id, ep_p3.id]


def test_add_rpc_endpoint_no_duplicate_url(session: Session):
    mgr = RpcManager(session)
    net = mgr.add_network("Ethereum", chain_type="evm", chain_id=1)

    ep1 = mgr.add_rpc_endpoint(net, "https://eth1.com", priority=1)
    ep2 = mgr.add_rpc_endpoint(net, "https://eth1.com", priority=2)

    assert ep1.id == ep2.id

    endpoints = mgr.list_rpc_endpoints(net)
    assert len(endpoints) == 1
    assert endpoints[0].url == "https://eth1.com"


def test_set_primary_yields_exactly_one_primary(session: Session):
    mgr = RpcManager(session)
    net = mgr.add_network("Base", chain_type="evm", chain_id=8453)

    ep1 = mgr.add_rpc_endpoint(net, "https://base-rpc1.com", priority=1, is_primary=True)
    ep2 = mgr.add_rpc_endpoint(net, "https://base-rpc2.com", priority=2, is_primary=False)
    ep3 = mgr.add_rpc_endpoint(net, "https://base-rpc3.com", priority=3, is_primary=False)

    # Initially ep1 is primary
    eps = mgr.list_rpc_endpoints(net)
    primaries = [ep for ep in eps if ep.is_primary]
    assert len(primaries) == 1
    assert primaries[0].id == ep1.id

    # Switch primary to ep2
    res2 = mgr.set_primary(net, ep2.id)
    assert res2.is_primary is True

    # Verify directly via DB query that only ep2 is primary
    all_eps = session.execute(
        select(RpcEndpoint).where(RpcEndpoint.network_id == net.id)
    ).scalars().all()
    primary_ids = [ep.id for ep in all_eps if ep.is_primary]
    assert primary_ids == [ep2.id]
    assert net.rpc_url == ep2.url

    # Switch primary to ep3 (higher priority number, priority doesn't need to be 1)
    res3 = mgr.set_primary(net, ep3.id)
    assert res3.is_primary is True

    all_eps_after = session.execute(
        select(RpcEndpoint).where(RpcEndpoint.network_id == net.id)
    ).scalars().all()
    assert [ep.id for ep in all_eps_after if ep.is_primary] == [ep3.id]
    assert net.rpc_url == ep3.url

    # Invalid endpoint_id raises ValueError
    with pytest.raises(ValueError, match="not found"):
        mgr.set_primary(net, 999999)


def test_check_chain_id_match(session: Session):
    mgr = RpcManager(session)
    net = mgr.add_network("Ethereum", chain_type="evm", chain_id=1, rpc_url="https://eth.rpc")

    def handler(request: httpx.Request) -> httpx.Response:
        data = json.loads(request.content)
        assert data["method"] == "eth_chainId"
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": "0x1"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = mgr.check_chain_id(net, client=client)

    assert result.status == ProviderStatus.OK
    assert result.data == 1
    assert result.error is None


def test_check_chain_id_mismatch(session: Session):
    mgr = RpcManager(session)
    net = mgr.add_network("Ethereum", chain_type="evm", chain_id=1, rpc_url="https://eth.rpc")

    def handler(request: httpx.Request) -> httpx.Response:
        data = json.loads(request.content)
        assert data["method"] == "eth_chainId"
        # Return 137 (Polygon) hex 0x89
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": "0x89"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = mgr.check_chain_id(net, client=client)

    assert result.status == ProviderStatus.ERROR
    assert result.data == 137
    assert "mismatch" in result.error.lower()


def test_check_chain_id_never_raises_on_errors(session: Session):
    mgr = RpcManager(session)
    net = mgr.add_network("Ethereum", chain_type="evm", chain_id=1, rpc_url="https://eth.rpc")

    # 1. Transport error
    def transport_err_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused")

    client1 = httpx.Client(transport=httpx.MockTransport(transport_err_handler))
    res1 = mgr.check_chain_id(net, client=client1)
    assert res1.status == ProviderStatus.ERROR
    assert "ConnectError" in res1.error or "Connection refused" in res1.error

    # 2. HTTP 500 error
    def server_err_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="Internal Server Error")

    client2 = httpx.Client(transport=httpx.MockTransport(server_err_handler))
    res2 = mgr.check_chain_id(net, client=client2)
    assert res2.status == ProviderStatus.ERROR
    assert "500" in res2.error

    # 3. JSON-RPC error response
    def rpc_err_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "error": {"code": -32600, "message": "Invalid request"}})

    client3 = httpx.Client(transport=httpx.MockTransport(rpc_err_handler))
    res3 = mgr.check_chain_id(net, client=client3)
    assert res3.status == ProviderStatus.ERROR
    assert "Invalid request" in res3.error


def test_check_connection_success_and_error(session: Session):
    mgr = RpcManager(session)
    net = mgr.add_network("BSC", chain_type="evm", chain_id=56)
    ep = mgr.add_rpc_endpoint(net, "https://bsc.rpc", priority=1, is_primary=True)

    # Success case
    def ok_handler(request: httpx.Request) -> httpx.Response:
        data = json.loads(request.content)
        assert data["method"] == "eth_blockNumber"
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": "0x1b4"})  # 436

    client_ok = httpx.Client(transport=httpx.MockTransport(ok_handler))
    res_ok = mgr.check_connection(net, client=client_ok)
    assert res_ok.status == ProviderStatus.OK
    assert res_ok.data == 436
    assert ep.is_healthy is True

    # Error case (e.g. 503)
    def err_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="Service Unavailable")

    client_err = httpx.Client(transport=httpx.MockTransport(err_handler))
    res_err = mgr.check_connection(net, client=client_err)
    assert res_err.status == ProviderStatus.ERROR
    assert ep.is_healthy is False


def test_no_float_hygiene(session: Session):
    mgr = RpcManager(session)
    with pytest.raises((TypeError, ValueError)):
        mgr.add_network("FloatNet", chain_id=1.0)  # type: ignore

    with pytest.raises((TypeError, ValueError)):
        mgr.add_network("FloatDecNet", chain_id=1, decimals=18.0)  # type: ignore

    net = mgr.add_network("IntNet", chain_id=10)
    with pytest.raises((TypeError, ValueError)):
        mgr.add_rpc_endpoint(net, "https://rpc.io", priority=1.5)  # type: ignore

    # AST check: no float in app/core/rpc_manager.py
    src = Path("app/core/rpc_manager.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, float):
            pytest.fail(f"Found float constant {node.value} in app/core/rpc_manager.py")
        if isinstance(node, ast.Name) and node.id == "float":
            pytest.fail("Found 'float' identifier in app/core/rpc_manager.py")


def test_no_ui_imports_hygiene():
    src = Path("app/core/rpc_manager.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                for forbidden in ("textual", "rich", "app.ui"):
                    if alias.name.startswith(forbidden):
                        pytest.fail(f"Forbidden import in core: {alias.name}")
        elif isinstance(node, ast.ImportFrom) and node.module:
            for forbidden in ("textual", "rich", "app.ui"):
                if node.module.startswith(forbidden):
                    pytest.fail(f"Forbidden import in core: {node.module}")


def test_resolve_network_by_name_and_id(session: Session):
    mgr = RpcManager(session)
    net = mgr.add_network("Polygon", chain_type="evm", chain_id=137)

    # By id
    found_by_id = mgr._resolve_network(net.id)
    assert found_by_id.id == net.id

    # By name case-insensitive
    found_by_name = mgr._resolve_network("polygon")
    assert found_by_name.id == net.id

    # Non-existent id
    with pytest.raises(ValueError, match="not found"):
        mgr._resolve_network(999999)

    # Non-existent name
    with pytest.raises(ValueError, match="not found"):
        mgr._resolve_network("NoSuchNetwork")

    # Invalid type
    with pytest.raises(TypeError):
        mgr._resolve_network([123])  # type: ignore


def test_primary_endpoint_preferred_over_network_rpc(session: Session):
    mgr = RpcManager(session)
    net = mgr.add_network("Fantom", chain_type="evm", chain_id=250, rpc_url="https://fallback.fantom.rpc")
    mgr.add_rpc_endpoint(net, "https://primary.fantom.rpc", priority=1, is_primary=True)

    requested_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": "0xfa"})  # 250

    client = httpx.Client(transport=httpx.MockTransport(handler))
    res = mgr.check_chain_id(net, client=client)

    assert res.status == ProviderStatus.OK
    assert requested_urls == ["https://primary.fantom.rpc/"] or requested_urls == ["https://primary.fantom.rpc"]


def test_check_chain_id_and_connection_no_rpc_url_available(session: Session):
    mgr = RpcManager(session)
    net = mgr.add_network("EmptyNet", chain_type="evm", chain_id=999)

    res_chain = mgr.check_chain_id(net)
    assert res_chain.status == ProviderStatus.ERROR
    assert "No RPC endpoint" in res_chain.error

    res_conn = mgr.check_connection(net)
    assert res_conn.status == ProviderStatus.ERROR
    assert "No RPC endpoint" in res_conn.error


def test_check_connection_block_zero(session: Session):
    mgr = RpcManager(session)
    net = mgr.add_network("GenesisNet", chain_type="evm", chain_id=1, rpc_url="https://genesis.rpc")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": "0x0"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    res = mgr.check_connection(net, client=client)
    assert res.status == ProviderStatus.OK
    assert res.data == 0


def test_add_rpc_endpoint_with_is_primary_clears_previous(session: Session):
    mgr = RpcManager(session)
    net = mgr.add_network("Scroll", chain_type="evm", chain_id=534352)

    ep1 = mgr.add_rpc_endpoint(net, "https://scroll1.rpc", priority=1, is_primary=True)
    assert ep1.is_primary is True

    ep2 = mgr.add_rpc_endpoint(net, "https://scroll2.rpc", priority=2, is_primary=True)
    assert ep2.is_primary is True

    # ep1 must be cleared
    session.refresh(ep1)
    assert ep1.is_primary is False

    # Calling add_rpc_endpoint again with existing url and is_primary=True keeps it primary
    ep1_again = mgr.add_rpc_endpoint(net, "https://scroll1.rpc", is_primary=True)
    assert ep1_again.id == ep1.id
    assert ep1_again.is_primary is True
    session.refresh(ep2)
    assert ep2.is_primary is False
