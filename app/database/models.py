"""SQLAlchemy 2.0 declarative models for Wallet Intelligence Tracker."""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, validates


def utc_now() -> datetime:
    """Return current timezone-aware UTC datetime."""
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Base class for all database models."""


class WalletGroup(Base):
    """Hierarchical group of wallets with unlimited nesting."""

    __tablename__ = "wallet_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    parent_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("wallet_groups.id", ondelete="SET NULL"),
        nullable=True,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    parent: Mapped[WalletGroup | None] = relationship(
        "WalletGroup",
        remote_side=[id],
        back_populates="children",
    )
    children: Mapped[list[WalletGroup]] = relationship(
        "WalletGroup",
        back_populates="parent",
    )
    wallets: Mapped[list[Wallet]] = relationship("Wallet", back_populates="group")


class Wallet(Base):
    """Public wallet address with metadata and group association."""

    __tablename__ = "wallets"
    __table_args__ = (
        UniqueConstraint("address", "chain_type", name="uq_wallet_address_chain_type"),
        Index("ix_wallets_address", "address"),
        Index("ix_wallets_group_id", "group_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    address: Mapped[str] = mapped_column(String(128), nullable=False)
    address_raw: Mapped[str | None] = mapped_column(String(128), nullable=True)
    chain_type: Mapped[str] = mapped_column(String(32), default="evm", nullable=False)
    name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    group_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("wallet_groups.id", ondelete="SET NULL"),
        nullable=True,
    )
    archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    first_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __init__(self, **kwargs: Any) -> None:
        self.chain_type = kwargs.get("chain_type", "evm")
        raw = kwargs.get("address_raw")
        super().__init__(**kwargs)
        if raw is not None:
            self.address_raw = raw

    @validates("address")
    def validate_address(self, key: str, value: str | None) -> str | None:
        if not isinstance(value, str):
            return value
        self.address_raw = value
        chain = getattr(self, "chain_type", None) or "evm"
        if chain == "evm":
            return value.lower()
        return value

    group: Mapped[WalletGroup | None] = relationship("WalletGroup", back_populates="wallets")
    networks: Mapped[list[WalletNetwork]] = relationship("WalletNetwork", back_populates="wallet")
    tag_links: Mapped[list[WalletTagLink]] = relationship("WalletTagLink", back_populates="wallet")
    tags: Mapped[list[WalletTag]] = relationship(
        "WalletTag",
        secondary="wallet_tag_links",
        viewonly=True,
    )
    socials: Mapped[list[WalletSocial]] = relationship("WalletSocial", back_populates="wallet")
    audit_logs: Mapped[list[WalletAuditLog]] = relationship(
        "WalletAuditLog",
        back_populates="wallet",
        cascade="all, delete-orphan",
        order_by="WalletAuditLog.id",
    )
    activities: Mapped[list[Activity]] = relationship("Activity", back_populates="wallet")
    transactions: Mapped[list[Transaction]] = relationship("Transaction", back_populates="wallet")
    balance_snapshots: Mapped[list[BalanceSnapshot]] = relationship("BalanceSnapshot", back_populates="wallet")
    defi_positions: Mapped[list[DeFiPosition]] = relationship("DeFiPosition", back_populates="wallet")
    project_wallets: Mapped[list[ProjectWallet]] = relationship("ProjectWallet", back_populates="wallet")
    notes_list: Mapped[list[Note]] = relationship("Note", back_populates="wallet")


class Network(Base):
    """Blockchain network configuration and identity."""

    __tablename__ = "networks"
    __table_args__ = (
        UniqueConstraint("chain_type", "chain_id", name="uq_network_chain_type_chain_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    chain_type: Mapped[str] = mapped_column(String(32), default="evm", nullable=False)
    chain_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rpc_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    explorer_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    native_token: Mapped[str | None] = mapped_column(String(32), default="ETH", nullable=True)
    symbol: Mapped[str | None] = mapped_column(String(32), nullable=True)
    decimals: Mapped[int] = mapped_column(Integer, default=18, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_testnet: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    wallet_networks: Mapped[list[WalletNetwork]] = relationship("WalletNetwork", back_populates="network")
    rpc_endpoints: Mapped[list[RpcEndpoint]] = relationship("RpcEndpoint", back_populates="network")
    contracts: Mapped[list[ProjectContract]] = relationship("ProjectContract", back_populates="network")
    activities: Mapped[list[Activity]] = relationship("Activity", back_populates="network")
    transactions: Mapped[list[Transaction]] = relationship("Transaction", back_populates="network")
    tokens: Mapped[list[Token]] = relationship("Token", back_populates="network")


class WalletNetwork(Base):
    """Association tracking a wallet monitored on a specific network."""

    __tablename__ = "wallet_networks"
    __table_args__ = (
        UniqueConstraint("wallet_id", "network_id", name="uq_wallet_network"),
        Index("ix_wallet_networks_network_id", "network_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wallet_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("wallets.id", ondelete="CASCADE"),
        nullable=False,
    )
    network_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("networks.id", ondelete="CASCADE"),
        nullable=False,
    )
    monitoring_status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    wallet: Mapped[Wallet] = relationship("Wallet", back_populates="networks")
    network: Mapped[Network] = relationship("Network", back_populates="wallet_networks")


class RpcEndpoint(Base):
    """RPC URL and health status for a network."""

    __tablename__ = "rpc_endpoints"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    network_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("networks.id", ondelete="CASCADE"),
        nullable=False,
    )
    url: Mapped[str] = mapped_column(String(255), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_backup: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_healthy: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    network: Mapped[Network] = relationship("Network", back_populates="rpc_endpoints")


class WalletTag(Base):
    """Tag taxonomy for labeling wallets."""

    __tablename__ = "wallet_tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    color: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    wallet_links: Mapped[list[WalletTagLink]] = relationship("WalletTagLink", back_populates="tag")


class WalletTagLink(Base):
    """Many-to-many link between a wallet and a tag."""

    __tablename__ = "wallet_tag_links"
    __table_args__ = (
        UniqueConstraint("wallet_id", "tag_id", name="uq_wallet_tag_link"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wallet_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("wallets.id", ondelete="CASCADE"),
        nullable=False,
    )
    tag_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("wallet_tags.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    wallet: Mapped[Wallet] = relationship("Wallet", back_populates="tag_links")
    tag: Mapped[WalletTag] = relationship("WalletTag", back_populates="wallet_links")


class WalletSocial(Base):
    """Social media links and external handles linked to a wallet."""

    __tablename__ = "wallet_socials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wallet_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("wallets.id", ondelete="CASCADE"),
        nullable=False,
    )
    platform: Mapped[str] = mapped_column(String(64), nullable=False)
    handle: Mapped[str] = mapped_column(String(128), nullable=False)
    url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    wallet: Mapped[Wallet] = relationship("Wallet", back_populates="socials")

    @property
    def value(self) -> str | None:
        """Alias for handle/url for backwards compatibility."""
        return self.url or self.handle


class WalletAuditLog(Base):
    """Audit trail recording historical metadata modifications to wallets."""

    __tablename__ = "wallet_audit_log"
    __table_args__ = (
        Index("ix_wallet_audit_log_wallet_id", "wallet_id"),
        Index("ix_wallet_audit_log_changed_at", "changed_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wallet_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("wallets.id", ondelete="CASCADE"),
        nullable=False,
    )
    field: Mapped[str] = mapped_column(String(64), nullable=False)
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    wallet: Mapped[Wallet] = relationship("Wallet", back_populates="audit_logs")



class WalletRelation(Base):
    """Inferred or manual relationship between two wallets."""

    __tablename__ = "wallet_relations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    from_wallet_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("wallets.id", ondelete="CASCADE"),
        nullable=False,
    )
    to_wallet_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("wallets.id", ondelete="CASCADE"),
        nullable=False,
    )
    relation_type: Mapped[str] = mapped_column(String(64), nullable=False)
    confidence: Mapped[str] = mapped_column(String(32), default="inferred", nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    from_wallet: Mapped[Wallet] = relationship("Wallet", foreign_keys=[from_wallet_id])
    to_wallet: Mapped[Wallet] = relationship("Wallet", foreign_keys=[to_wallet_id])


class Project(Base):
    """Project, protocol or testnet catalog entry."""

    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    official_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    contracts: Mapped[list[ProjectContract]] = relationship("ProjectContract", back_populates="project")
    project_wallets: Mapped[list[ProjectWallet]] = relationship("ProjectWallet", back_populates="project")
    tasks: Mapped[list[ProjectTask]] = relationship("ProjectTask", back_populates="project")
    notes_list: Mapped[list[Note]] = relationship("Note", back_populates="project")


class ProjectContract(Base):
    """Smart contract address associated with a project on a network."""

    __tablename__ = "project_contracts"
    __table_args__ = (
        UniqueConstraint("network_id", "contract_address", name="uq_project_contract_network_address"),
        Index("ix_project_contracts_contract_address", "contract_address"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    network_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("networks.id", ondelete="CASCADE"),
        nullable=False,
    )
    contract_address: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    abi: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    @validates("contract_address")
    def validate_contract_address(self, key: str, value: str | None) -> str | None:
        if isinstance(value, str):
            return value.lower()
        return value

    project: Mapped[Project] = relationship("Project", back_populates="contracts")
    network: Mapped[Network] = relationship("Network", back_populates="contracts")


class ProjectWallet(Base):
    """Participation link between a wallet and a project."""

    __tablename__ = "project_wallets"
    __table_args__ = (
        UniqueConstraint("project_id", "wallet_id", name="uq_project_wallet"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    wallet_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("wallets.id", ondelete="CASCADE"),
        nullable=False,
    )
    source: Mapped[str] = mapped_column(String(32), default="detected", nullable=False)  # detected|manual|task
    interactions_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    first_interaction_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_interaction_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    project: Mapped[Project] = relationship("Project", back_populates="project_wallets")
    wallet: Mapped[Wallet] = relationship("Wallet", back_populates="project_wallets")


class ProjectTask(Base):
    """User task or checklist item for a project."""

    __tablename__ = "project_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    wallet_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("wallets.id", ondelete="CASCADE"),
        nullable=True,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="todo", nullable=False)  # todo|in_progress|done|cancelled
    due_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    project: Mapped[Project] = relationship("Project", back_populates="tasks")
    wallet: Mapped[Wallet | None] = relationship("Wallet")


class Activity(Base):
    """On-chain or manual wallet activity event."""

    __tablename__ = "activities"
    __table_args__ = (
        UniqueConstraint("network_id", "tx_hash", "log_index", name="uq_activity_dedupe"),
        Index("ix_activities_occurred_at", "occurred_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wallet_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("wallets.id", ondelete="CASCADE"),
        nullable=False,
    )
    network_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("networks.id", ondelete="CASCADE"),
        nullable=False,
    )
    project_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True,
    )
    tx_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    log_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    activity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    contract_address: Mapped[str | None] = mapped_column(String(128), nullable=True)
    token_symbol: Mapped[str | None] = mapped_column(String(32), nullable=True)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="confirmed", nullable=False)
    source: Mapped[str] = mapped_column(String(32), default="chain", nullable=False)  # chain|provider|manual|inferred
    is_manual: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    explorer_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    extra_data: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    wallet: Mapped[Wallet] = relationship("Wallet", back_populates="activities")
    network: Mapped[Network] = relationship("Network", back_populates="activities")
    project: Mapped[Project | None] = relationship("Project")


class Transaction(Base):
    """Raw on-chain transaction record."""

    __tablename__ = "transactions"
    __table_args__ = (
        UniqueConstraint("network_id", "tx_hash", name="uq_transaction_network_tx_hash"),
        Index("ix_transactions_tx_hash", "tx_hash"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wallet_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("wallets.id", ondelete="CASCADE"),
        nullable=False,
    )
    network_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("networks.id", ondelete="CASCADE"),
        nullable=False,
    )
    tx_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    block_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    from_address: Mapped[str] = mapped_column(String(128), nullable=False)
    to_address: Mapped[str | None] = mapped_column(String(128), nullable=True)
    value: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    gas_price: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    gas_used: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="success", nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    source: Mapped[str] = mapped_column(String(32), default="chain", nullable=False)  # chain|provider|manual|inferred
    is_manual: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    wallet: Mapped[Wallet] = relationship("Wallet", back_populates="transactions")
    network: Mapped[Network] = relationship("Network", back_populates="transactions")


class Token(Base):
    """Fungible token contract metadata."""

    __tablename__ = "tokens"
    __table_args__ = (
        UniqueConstraint("network_id", "contract_address", name="uq_token_network_address"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    network_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("networks.id", ondelete="CASCADE"),
        nullable=False,
    )
    contract_address: Mapped[str] = mapped_column(String(128), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    decimals: Mapped[int] = mapped_column(Integer, default=18, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    @validates("contract_address")
    def validate_contract_address(self, key: str, value: str | None) -> str | None:
        if isinstance(value, str):
            return value.lower()
        return value

    network: Mapped[Network] = relationship("Network", back_populates="tokens")


class BalanceSnapshot(Base):
    """Historical snapshot of wallet balance or token balance."""

    __tablename__ = "balance_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wallet_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("wallets.id", ondelete="CASCADE"),
        nullable=False,
    )
    network_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("networks.id", ondelete="CASCADE"),
        nullable=False,
    )
    token_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("tokens.id", ondelete="SET NULL"),
        nullable=True,
    )
    raw_balance: Mapped[str | None] = mapped_column(String(128), nullable=True)
    balance: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    usd_price: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    usd_value: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    snapshot_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    wallet: Mapped[Wallet] = relationship("Wallet", back_populates="balance_snapshots")
    network: Mapped[Network] = relationship("Network")
    token: Mapped[Token | None] = relationship("Token")


class DeFiPosition(Base):
    """DeFi protocol position with certainty level."""

    __tablename__ = "defi_positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wallet_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("wallets.id", ondelete="CASCADE"),
        nullable=False,
    )
    network_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("networks.id", ondelete="CASCADE"),
        nullable=False,
    )
    protocol: Mapped[str] = mapped_column(String(100), nullable=False)
    position_type: Mapped[str] = mapped_column(String(64), nullable=False)  # lending|liquidity|staking|yield
    certainty: Mapped[str] = mapped_column(String(32), default="confirmed", nullable=False)  # confirmed|inferred|unknown
    amount: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    usd_value: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    wallet: Mapped[Wallet] = relationship("Wallet", back_populates="defi_positions")
    network: Mapped[Network] = relationship("Network")


class Provider(Base):
    """Data provider metadata and operational settings."""

    __tablename__ = "providers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    api_key_env: Mapped[str | None] = mapped_column(String(128), nullable=True)
    base_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    rate_limit_per_second: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SyncJob(Base):
    """Background synchronization job record."""

    __tablename__ = "sync_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wallet_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("wallets.id", ondelete="CASCADE"),
        nullable=True,
    )
    network_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("networks.id", ondelete="CASCADE"),
        nullable=True,
    )
    job_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)  # pending|running|completed|failed
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    wallet: Mapped[Wallet | None] = relationship("Wallet")
    network: Mapped[Network | None] = relationship("Network")


class SyncCursor(Base):
    """Cursor position tracking last synced block/timestamp per wallet, network and data type."""

    __tablename__ = "sync_cursors"
    __table_args__ = (
        UniqueConstraint("wallet_id", "network_id", "data_type", name="uq_sync_cursor"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wallet_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("wallets.id", ondelete="CASCADE"),
        nullable=False,
    )
    network_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("networks.id", ondelete="CASCADE"),
        nullable=False,
    )
    data_type: Mapped[str] = mapped_column(String(64), nullable=False)  # transactions|tokens|defi
    cursor_value: Mapped[str] = mapped_column(String(255), nullable=False)
    last_block_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    wallet: Mapped[Wallet] = relationship("Wallet")
    network: Mapped[Network] = relationship("Network")


class Note(Base):
    """User notes attached to wallets or projects."""

    __tablename__ = "notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wallet_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("wallets.id", ondelete="CASCADE"),
        nullable=True,
    )
    project_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=True,
    )
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    wallet: Mapped[Wallet | None] = relationship("Wallet", back_populates="notes_list")
    project: Mapped[Project | None] = relationship("Project", back_populates="notes_list")
