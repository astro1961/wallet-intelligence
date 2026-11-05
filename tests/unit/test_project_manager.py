"""Unit tests for ProjectManager (Stage 5A)."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.project_manager import NetworkNotFoundError, ProjectManager
from app.database.models import (
    Activity,
    Base,
    Network,
    Note,
    ProjectContract,
    ProjectTask,
    ProjectWallet,
    Wallet,
)


@pytest.fixture
def engine():
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture
def session_factory(engine):
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture
def session(session_factory):
    with session_factory() as s:
        yield s


@pytest.fixture
def sample_networks(session: Session) -> dict[str, Network]:
    eth = Network(name="ethereum", chain_type="evm", chain_id=1, enabled=True)
    poly = Network(name="polygon", chain_type="evm", chain_id=137, enabled=True)
    session.add_all([eth, poly])
    session.commit()
    return {"ethereum": eth, "polygon": poly}


# -------------------------------------------------------------------------
# Catalog Tests (CRUD, duplicate names, count, list, delete cascade, whitelist)
# -------------------------------------------------------------------------


def test_create_and_get_project(session: Session):
    pm = ProjectManager(session)
    p = pm.create_project(
        name="Arbitrum Odyssey",
        description="Arbitrum ecosystem exploration",
        category="ecosystem",
        status="active",
        official_url="https://arbitrum.io",
        notes="Important testnet tasks",
    )
    assert p.id is not None
    assert p.name == "Arbitrum Odyssey"
    assert p.description == "Arbitrum ecosystem exploration"
    assert p.category == "ecosystem"
    assert p.status == "active"
    assert p.official_url == "https://arbitrum.io"
    assert p.notes == "Important testnet tasks"
    assert p.created_at is not None
    assert p.updated_at is not None

    fetched = pm.get(p.id)
    assert fetched is not None
    assert fetched.id == p.id
    assert fetched.name == "Arbitrum Odyssey"

    assert pm.get(999999) is None


def test_create_project_duplicate_name_case_insensitive(session: Session):
    pm = ProjectManager(session)
    pm.create_project("Arbitrum Odyssey")

    # Exact duplicate
    with pytest.raises(ValueError, match="already exists"):
        pm.create_project("Arbitrum Odyssey")

    # Lowercase duplicate
    with pytest.raises(ValueError, match="already exists"):
        pm.create_project("arbitrum odyssey")

    # Uppercase duplicate with spaces
    with pytest.raises(ValueError, match="already exists"):
        pm.create_project("  ARBITRUM ODYSSEY  ")

    # Empty name
    with pytest.raises(ValueError, match="empty"):
        pm.create_project("   ")


def test_count_and_list_projects(session: Session):
    pm = ProjectManager(session)
    assert pm.count() == 0
    assert pm.list_projects() == []

    pm.create_project("Project Alpha", status="active")
    p2 = pm.create_project("Project Beta", status="completed")
    pm.create_project("Project Gamma", status="active")

    assert pm.count() == 3

    all_projs = pm.list_projects()
    assert len(all_projs) == 3
    assert {p.name for p in all_projs} == {"Project Alpha", "Project Beta", "Project Gamma"}

    active_projs = pm.list_projects(status="active")
    assert len(active_projs) == 2
    assert {p.name for p in active_projs} == {"Project Alpha", "Project Gamma"}

    completed_projs = pm.list_projects(status="completed")
    assert len(completed_projs) == 1
    assert completed_projs[0].id == p2.id


def test_update_project_whitelist(session: Session):
    pm = ProjectManager(session)
    p = pm.create_project("Uniswap V3", category="defi", status="active")

    # Update allowed fields
    updated = pm.update_project(
        p.id,
        name="Uniswap Protocol",
        description="Leading AMM DEX",
        category="dex",
        status="completed",
        official_url="https://uniswap.org",
        notes="Audited contracts",
    )
    assert updated.name == "Uniswap Protocol"
    assert updated.description == "Leading AMM DEX"
    assert updated.category == "dex"
    assert updated.status == "completed"
    assert updated.official_url == "https://uniswap.org"
    assert updated.notes == "Audited contracts"

    # Rejection of unknown / non-whitelisted fields (instead of hasattr)
    with pytest.raises(ValueError, match="non-editable or unknown field"):
        pm.update_project(p.id, unknown_field="invalid")

    with pytest.raises(ValueError, match="non-editable or unknown field"):
        pm.update_project(p.id, id=42)

    with pytest.raises(ValueError, match="non-editable or unknown field"):
        pm.update_project(p.id, created_at=datetime.now(UTC))

    # Reject non-existent project
    with pytest.raises(ValueError, match="not found"):
        pm.update_project(999999, name="Nope")


def test_update_project_duplicate_name(session: Session):
    pm = ProjectManager(session)
    p1 = pm.create_project("Project One")
    p2 = pm.create_project("Project Two")

    # Updating to existing project name (case-insensitive) should fail
    with pytest.raises(ValueError, match="already exists"):
        pm.update_project(p2.id, name="project one")

    # Updating same project to same name (or case change) should succeed
    updated = pm.update_project(p1.id, name="PROJECT ONE")
    assert updated.name == "PROJECT ONE"


def test_delete_project_cascade(session: Session, sample_networks):
    pm = ProjectManager(session)
    p = pm.create_project("Test Project")

    # Add contract
    c = pm.add_contract(
        p.id,
        "ethereum",
        "0x1111111111111111111111111111111111111111",
        name="Router",
    )

    # Add wallet and link
    w = Wallet(address="0x2222222222222222222222222222222222222222", name="Trader")
    session.add(w)
    session.flush()
    pw = pm.link_wallet(p.id, w.id)

    # Add task
    t = pm.add_task(p.id, "Stake tokens", wallet_id=w.id)

    # Add note
    note = Note(project_id=p.id, content="Some project note")
    session.add(note)
    session.flush()

    assert pm.count() == 1
    assert session.get(ProjectContract, c.id) is not None
    assert session.get(ProjectWallet, pw.id) is not None
    assert session.get(ProjectTask, t.id) is not None
    assert session.get(Note, note.id) is not None

    # Delete project
    pm.delete_project(p.id)

    assert pm.get(p.id) is None
    assert pm.count() == 0
    assert session.get(ProjectContract, c.id) is None
    assert session.get(ProjectWallet, pw.id) is None
    assert session.get(ProjectTask, t.id) is None
    assert session.get(Note, note.id) is None

    # Deleting non-existent project should be safe no-op
    pm.delete_project(999999)


# -------------------------------------------------------------------------
# Contracts Tests (per-network, EIP-55 normalization, network resolution, lookup)
# -------------------------------------------------------------------------


def test_add_contract_normalization_and_validation(session: Session, sample_networks):
    pm = ProjectManager(session)
    p = pm.create_project("Uniswap")

    # Valid mixed-case checksummed EVM address
    contract = pm.add_contract(
        p.id,
        "ethereum",
        "0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D",
        name="Router V2",
    )
    assert contract.id is not None
    assert contract.project_id == p.id
    assert contract.name == "Router V2"
    assert contract.contract_address == "0x7a250d5630b4cf539739df2c5dacb4c659f2488d"

    # Invalid address raises ValueError
    with pytest.raises(ValueError, match="EVM address"):
        pm.add_contract(p.id, "ethereum", "not-an-address")

    # Bad checksum raises ValueError
    with pytest.raises(ValueError, match="checksum"):
        pm.add_contract(p.id, "ethereum", "0x7A250d5630B4cF539739dF2C5dAcb4c659F2488D")

    # Unknown network raises NetworkNotFoundError (subclass of LookupError and ValueError)
    with pytest.raises((LookupError, ValueError)):
        pm.add_contract(p.id, "solana_mainnet", "0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D")

    with pytest.raises(NetworkNotFoundError):
        pm.add_contract(p.id, "non_existent_net", "0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D")

    # Missing project raises ValueError
    with pytest.raises(ValueError, match="not found"):
        pm.add_contract(999999, "ethereum", "0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D")


def test_contracts_per_network_and_duplicate_handling(session: Session, sample_networks):
    pm = ProjectManager(session)
    p1 = pm.create_project("Project Alpha")
    p2 = pm.create_project("Project Beta")

    addr = "0x7a250d5630b4cf539739df2c5dacb4c659f2488d"

    # Add same address on ethereum for p1
    c_eth = pm.add_contract(p1.id, "ethereum", addr, name="ETH Router")
    assert c_eth.id is not None

    # Same address on polygon for p2 is allowed (per-network contract)
    c_poly = pm.add_contract(p2.id, "polygon", addr, name="Polygon Router")
    assert c_poly.id is not None

    # Duplicate on SAME network raises ValueError
    with pytest.raises(ValueError, match="already registered"):
        pm.add_contract(p1.id, "ethereum", addr)

    # List contracts for p1
    p1_contracts = pm.list_contracts(p1.id)
    assert len(p1_contracts) == 1
    assert p1_contracts[0].id == c_eth.id


def test_find_project_by_contract(session: Session, sample_networks):
    pm = ProjectManager(session)
    p = pm.create_project("Curve")
    addr = "0xd533a949740bb3306d119cc777fa900ba034cd52"

    pm.add_contract(p.id, "ethereum", addr, name="CRV Token")

    # Match on ethereum
    found = pm.find_project_by_contract(addr, "ethereum")
    assert found is not None
    assert found.id == p.id

    # Miss on polygon (same address not registered on polygon)
    assert pm.find_project_by_contract(addr, "polygon") is None

    # Miss on unknown address
    assert pm.find_project_by_contract("0x1111111111111111111111111111111111111111", "ethereum") is None

    # Miss on unknown network
    assert pm.find_project_by_contract(addr, "arbitrum") is None


# -------------------------------------------------------------------------
# Participation Tests (link_wallet, detected_wallets, tasks, report)
# -------------------------------------------------------------------------


def test_participation_detected_vs_manual_and_tasks(session: Session, sample_networks):
    pm = ProjectManager(session)
    p = pm.create_project("Aave")
    net = sample_networks["ethereum"]

    w1 = Wallet(address="0x1111111111111111111111111111111111111111", name="Wallet 1")
    w2 = Wallet(address="0x2222222222222222222222222222222222222222", name="Wallet 2")
    w3 = Wallet(address="0x3333333333333333333333333333333333333333", name="Wallet 3")
    session.add_all([w1, w2, w3])
    session.flush()

    # Simulate synced activities for w1 associated with this project (Stage 4A)
    now = datetime.now(UTC)
    act1 = Activity(
        wallet_id=w1.id,
        network_id=net.id,
        project_id=p.id,
        tx_hash="0xtx1",
        log_index=0,
        activity_type="contract_call",
        occurred_at=now,
        status="confirmed",
        source="detected",
    )
    act2 = Activity(
        wallet_id=w1.id,
        network_id=net.id,
        project_id=p.id,
        tx_hash="0xtx2",
        log_index=0,
        activity_type="contract_call",
        occurred_at=now,
        status="confirmed",
        source="detected",
    )
    session.add_all([act1, act2])
    session.flush()

    # detected_wallets derives w1 from synced activities
    det = pm.detected_wallets(p.id)
    assert len(det) == 1
    assert det[0].wallet_id == w1.id
    assert det[0].source == "detected"
    assert det[0].interactions_count == 2

    # link_wallet on w1 (which is already detected): detected wins! Does NOT duplicate
    linked_w1 = pm.link_wallet(p.id, w1.id, source="manual")
    assert linked_w1.source == "detected"
    assert linked_w1.wallet_id == w1.id
    assert linked_w1.interactions_count == 2

    # Verify no duplicate ProjectWallet rows
    all_pw_w1 = session.execute(
        select(ProjectWallet).where(
            ProjectWallet.project_id == p.id,
            ProjectWallet.wallet_id == w1.id,
        )
    ).scalars().all()
    assert len(all_pw_w1) == 1

    # link_wallet on w2 (no activities): becomes manual
    linked_w2 = pm.link_wallet(p.id, w2.id, source="manual")
    assert linked_w2.source == "manual"
    assert linked_w2.interactions_count == 0

    # add_task for w3: creates task and links w3 with source="task"
    t1 = pm.add_task(p.id, "Deposit collateral", wallet_id=w3.id, status="todo")
    assert t1.id is not None
    assert t1.status == "todo"
    assert t1.completed_at is None

    # Check w3 was linked with source="task"
    pw_w3 = session.execute(
        select(ProjectWallet).where(
            ProjectWallet.project_id == p.id,
            ProjectWallet.wallet_id == w3.id,
        )
    ).scalar_one()
    assert pw_w3.source == "task"

    # Upgrading w3 with link_wallet (source="manual"): upgraded from "task" to "manual"
    upgraded_w3 = pm.link_wallet(p.id, w3.id, source="manual")
    assert upgraded_w3.source == "manual"

    # Add second task and complete t1
    pm.add_task(p.id, "Borrow USDC", wallet_id=w1.id, status="todo")
    completed_t1 = pm.complete_task(t1.id)
    assert completed_t1.status == "done"
    assert completed_t1.completed_at is not None

    # Check complete_task on non-existent task
    with pytest.raises(ValueError, match="not found"):
        pm.complete_task(999999)

    # Generate participation report
    report = pm.participation_report(p.id)
    assert report["tasks_total"] == 2
    assert report["tasks_done"] == 1
    assert report["interactions"] == 2

    wallets_report = {w["wallet_id"]: w for w in report["wallets"]}
    assert len(wallets_report) == 3

    assert wallets_report[w1.id]["source"] == "detected"
    assert wallets_report[w1.id]["interactions"] == 2

    assert wallets_report[w2.id]["source"] == "manual"
    assert wallets_report[w2.id]["interactions"] == 0

    assert wallets_report[w3.id]["source"] == "manual"
    assert wallets_report[w3.id]["interactions"] == 0


def test_participation_report_empty_project(session: Session):
    pm = ProjectManager(session)
    p = pm.create_project("Empty Project")

    report = pm.participation_report(p.id)
    assert report == {
        "wallets": [],
        "tasks_total": 0,
        "tasks_done": 0,
        "interactions": 0,
    }
