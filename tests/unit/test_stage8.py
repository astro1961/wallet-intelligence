"""Unit tests for Stage 8: GraphManager and GraphScreen."""
from __future__ import annotations

import json
from datetime import UTC, datetime

import networkx as nx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from textual.widgets import DataTable, Label

from app.application import WalletTrackerApp
from app.core.graph_manager import GraphManager
from app.database.models import (
    Base,
    Network,
    Transaction,
    Wallet,
    WalletRelation,
)
from app.ui.screens.graph import GraphScreen
from app.utils.validators import normalize_evm_address


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


@pytest.fixture
def seed_wallets(session: Session) -> dict[str, Wallet]:
    w1 = Wallet(
        address="0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed",
        name="Alice",
    )
    w2 = Wallet(
        address="0xfB6916095ca1df60bB79Ce92cE3Ea74c37c5d359",
        name="Bob",
    )
    w3 = Wallet(
        address="0xdbF03B407c01E7cD3CBea99509d93f8DDDC8C6FB",
        name="Charlie",
    )
    session.add_all([w1, w2, w3])
    session.commit()
    return {"alice": w1, "bob": w2, "charlie": w3}


def test_add_relation_normalisation_and_creation(session: Session, seed_wallets):
    gm = GraphManager(session)
    alice = seed_wallets["alice"]
    bob = seed_wallets["bob"]

    # Pass lowercase strings
    rel = gm.add_relation(
        alice.address.lower(),
        bob.address.lower(),
        relation_type="colleague",
        confidence="confirmed",
        notes="Known coworker",
    )
    assert rel.id is not None
    assert rel.relation_type == "colleague"
    assert rel.confidence == "confirmed"
    assert rel.notes == "Known coworker"
    assert rel.from_wallet_id == alice.id
    assert rel.to_wallet_id == bob.id


def test_add_relation_self_loop_rejected(session: Session, seed_wallets):
    gm = GraphManager(session)
    alice = seed_wallets["alice"]

    # Identical wallet object self-loop
    with pytest.raises(ValueError, match="Self-loop"):
        gm.add_relation(alice, alice, relation_type="transfer")

    # Lowercase vs checksummed address self-loop
    with pytest.raises(ValueError, match="Self-loop"):
        gm.add_relation(
            alice.address.lower(),
            alice.address.upper().replace("0X", "0x"),
            relation_type="transfer",
        )


def test_add_relation_invalid_confidence(session: Session, seed_wallets):
    gm = GraphManager(session)
    alice = seed_wallets["alice"]
    bob = seed_wallets["bob"]

    with pytest.raises(ValueError, match="Invalid confidence"):
        gm.add_relation(alice, bob, relation_type="transfer", confidence="speculative")


def test_add_relation_idempotent_dedup(session: Session, seed_wallets):
    gm = GraphManager(session)
    alice = seed_wallets["alice"]
    bob = seed_wallets["bob"]

    rel1 = gm.add_relation(alice, bob, relation_type="transfer", confidence="inferred")
    rel2 = gm.add_relation(alice, bob, relation_type="transfer", confidence="inferred")

    assert rel1.id == rel2.id

    # Verify only one row exists in database
    all_rels = session.query(WalletRelation).all()
    assert len(all_rels) == 1


def test_infer_from_transactions(session: Session, seed_wallets):
    alice = seed_wallets["alice"]
    bob = seed_wallets["bob"]
    charlie = seed_wallets["charlie"]

    net = Network(name="Ethereum", chain_type="evm", chain_id=1, native_token="ETH")
    session.add(net)
    session.flush()

    # Tx 1: Alice -> Bob (tracked pair)
    tx1 = Transaction(
        wallet_id=alice.id,
        network_id=net.id,
        tx_hash="0xaaa1",
        from_address=alice.address,
        to_address=bob.address,
        occurred_at=datetime.now(UTC),
    )
    # Tx 2: Bob -> Alice (same counterparty pair in reverse direction)
    tx2 = Transaction(
        wallet_id=bob.id,
        network_id=net.id,
        tx_hash="0xaaa2",
        from_address=bob.address,
        to_address=alice.address,
        occurred_at=datetime.now(UTC),
    )
    # Tx 3: Alice -> Alice (self-loop, should be ignored)
    tx3 = Transaction(
        wallet_id=alice.id,
        network_id=net.id,
        tx_hash="0xaaa3",
        from_address=alice.address,
        to_address=alice.address,
        occurred_at=datetime.now(UTC),
    )
    # Tx 4: Charlie -> external untracked address (should be ignored)
    tx4 = Transaction(
        wallet_id=charlie.id,
        network_id=net.id,
        tx_hash="0xaaa4",
        from_address=charlie.address,
        to_address="0x000000000000000000000000000000000000dEaD",
        occurred_at=datetime.now(UTC),
    )
    # Tx 5: Charlie -> Bob (tracked pair)
    tx5 = Transaction(
        wallet_id=charlie.id,
        network_id=net.id,
        tx_hash="0xaaa5",
        from_address=charlie.address,
        to_address=bob.address,
        occurred_at=datetime.now(UTC),
    )
    session.add_all([tx1, tx2, tx3, tx4, tx5])
    session.commit()

    gm = GraphManager(session)
    count = gm.infer_from_transactions()
    # Distinct counterparty pairs are {Alice, Bob} and {Charlie, Bob}
    assert count == 2

    # Verify idempotency: running again should create 0 relations
    repeat_count = gm.infer_from_transactions()
    assert repeat_count == 0

    rels = session.query(WalletRelation).all()
    assert len(rels) == 2
    for r in rels:
        assert r.relation_type == "transaction"
        assert r.confidence == "inferred"


def test_neighbors(session: Session, seed_wallets):
    gm = GraphManager(session)
    alice = seed_wallets["alice"]
    bob = seed_wallets["bob"]
    charlie = seed_wallets["charlie"]

    gm.add_relation(alice, bob, relation_type="colleague", confidence="confirmed")
    gm.add_relation(charlie, alice, relation_type="transaction", confidence="inferred")

    alice_norm = normalize_evm_address(alice.address)
    bob_norm = normalize_evm_address(bob.address)
    charlie_norm = normalize_evm_address(charlie.address)

    # Neighbors of Alice: Bob and Charlie
    alice_neighbors = gm.neighbors(alice)
    assert len(alice_neighbors) == 2
    by_addr = {n["address"]: n for n in alice_neighbors}

    assert bob_norm in by_addr
    assert by_addr[bob_norm]["name"] == "Bob"
    assert by_addr[bob_norm]["relation_type"] == "colleague"
    assert by_addr[bob_norm]["confidence"] == "confirmed"

    assert charlie_norm in by_addr
    assert by_addr[charlie_norm]["name"] == "Charlie"
    assert by_addr[charlie_norm]["relation_type"] == "transaction"
    assert by_addr[charlie_norm]["confidence"] == "inferred"

    # Neighbors of Bob: Alice
    bob_neighbors = gm.neighbors(bob.address.lower())
    assert len(bob_neighbors) == 1
    assert bob_neighbors[0]["address"] == alice_norm
    assert bob_neighbors[0]["name"] == "Alice"

    # Untracked or isolated wallet
    assert gm.neighbors("0x000000000000000000000000000000000000dEaD") == []


def test_build_graph(session: Session, seed_wallets):
    gm = GraphManager(session)
    alice = seed_wallets["alice"]
    bob = seed_wallets["bob"]
    charlie = seed_wallets["charlie"]

    gm.add_relation(alice, bob, relation_type="colleague", confidence="confirmed")
    gm.add_relation(bob, charlie, relation_type="transaction", confidence="inferred")

    G = gm.build_graph()

    # Must be undirected Graph, not DiGraph
    assert isinstance(G, nx.Graph)
    assert not isinstance(G, nx.DiGraph)

    alice_norm = normalize_evm_address(alice.address)
    bob_norm = normalize_evm_address(bob.address)
    charlie_norm = normalize_evm_address(charlie.address)

    assert G.number_of_nodes() == 3
    assert G.number_of_edges() == 2

    # Check node attributes
    assert G.nodes[alice_norm]["name"] == "Alice"
    assert G.nodes[bob_norm]["name"] == "Bob"
    assert G.nodes[charlie_norm]["name"] == "Charlie"

    # Check edge attributes
    e1 = G.edges[alice_norm, bob_norm]
    assert e1["relation_type"] == "colleague"
    assert e1["confidence"] == "confirmed"

    e2 = G.edges[bob_norm, charlie_norm]
    assert e2["relation_type"] == "transaction"
    assert e2["confidence"] == "inferred"


def test_export_json(session: Session, seed_wallets):
    gm = GraphManager(session)
    alice = seed_wallets["alice"]
    bob = seed_wallets["bob"]

    gm.add_relation(alice, bob, relation_type="colleague", confidence="confirmed")

    data = gm.export_json()
    assert "nodes" in data
    assert "edges" in data

    # Verify JSON serializability
    json_str = json.dumps(data)
    assert json_str is not None

    alice_norm = normalize_evm_address(alice.address)
    bob_norm = normalize_evm_address(bob.address)

    node_ids = {n["id"] for n in data["nodes"]}
    assert alice_norm in node_ids
    assert bob_norm in node_ids

    assert len(data["edges"]) == 1
    edge = data["edges"][0]
    assert edge["source"] == alice_norm
    assert edge["target"] == bob_norm
    assert edge["relation_type"] == "colleague"
    assert edge["confidence"] == "confirmed"


async def test_graph_screen_renders_neighbors_and_stats(session_factory, seed_wallets):
    with session_factory() as s:
        gm = GraphManager(s)
        alice = seed_wallets["alice"]
        bob = seed_wallets["bob"]
        charlie = seed_wallets["charlie"]
        gm.add_relation(alice, bob, relation_type="colleague", confidence="confirmed")
        gm.add_relation(bob, charlie, relation_type="transaction", confidence="inferred")
        s.commit()

    app = WalletTrackerApp()
    assert app.state is not None
    app.state.session_factory = session_factory

    async with app.run_test(size=(120, 35)) as pilot:
        # Navigate to Graph screen (key "7")
        await pilot.press("7")
        await pilot.pause()

        assert app.screen.id == "graph"
        assert isinstance(app.screen, GraphScreen)

        # Check stats widgets
        comp_lbl = app.screen.query_one("#graph-components", Label)
        assert "1" in str(comp_lbl.render())  # Alice-Bob-Charlie is 1 connected component

        density_lbl = app.screen.query_one("#graph-density", Label)
        # 3 nodes, 2 edges -> density = 2 * 2 / (3 * 2) = 2/3 ~= 0.6667
        assert "0.66" in str(density_lbl.render()) or "Density" in str(density_lbl.render())

        # Select Alice
        app.screen.select_wallet(alice.address)
        await pilot.pause()

        table = app.screen.query_one("#neighbors-table", DataTable)
        assert table.row_count == 1
        # Bob is Alice's neighbor
        row = table.get_row_at(0)
        assert "Bob" in row or normalize_evm_address(bob.address) in row


def test_add_relation_invalid_address(session: Session, seed_wallets):
    gm = GraphManager(session)
    alice = seed_wallets["alice"]

    with pytest.raises(ValueError):
        gm.add_relation("not-an-evm-address", alice, relation_type="transfer")


def test_add_relation_empty_relation_type(session: Session, seed_wallets):
    gm = GraphManager(session)
    alice = seed_wallets["alice"]
    bob = seed_wallets["bob"]

    with pytest.raises(ValueError, match="relation_type"):
        gm.add_relation(alice, bob, relation_type="  ")


def test_build_graph_and_export_empty(session: Session):
    gm = GraphManager(session)
    G = gm.build_graph()
    assert isinstance(G, nx.Graph)
    assert G.number_of_nodes() == 0
    assert G.number_of_edges() == 0

    data = gm.export_json()
    assert data == {"nodes": [], "edges": []}


async def test_graph_screen_empty_state(session_factory):
    app = WalletTrackerApp()
    assert app.state is not None
    app.state.session_factory = session_factory

    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.press("7")
        await pilot.pause()

        assert app.screen.id == "graph"
        empty_lbl = app.screen.query_one("#empty-state")
        assert empty_lbl.display is True
        table = app.screen.query_one("#neighbors-table", DataTable)
        assert table.display is False

