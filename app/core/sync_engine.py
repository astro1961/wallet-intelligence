"""Synchronization engine for wallet balances, transactions, and activities."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from app.core.activity_tracker import ActivityTracker
from app.core.balance_manager import save_native_balance
from app.database.models import (
    Activity,
    BalanceSnapshot,
    Network,
    SyncCursor,
    SyncJob,
    Transaction,
    Wallet,
    WalletNetwork,
)
from app.providers.base import ProviderStatus, TransactionItem, TransactionListResult

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker

    from app.config import AppConfig
    from app.providers.registry import ProviderRegistry

logger = logging.getLogger(__name__)


def _to_utc(dt: datetime | None) -> datetime:
    """Ensure datetime is UTC and timezone-aware."""
    if dt is None:
        return datetime.now(UTC)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


@dataclass
class SyncReport:
    """Outcome report for a single wallet synchronization run."""

    wallet_id: int
    network: str
    status: str  # "ok" | "error" | "skipped"
    activities_added: int = 0
    activities_updated: int = 0
    balance_saved: bool = False
    error: str | None = None


class SyncEngine:
    """Engine orchestrating data provider sync into local database models."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        providers: ProviderRegistry,
        config: AppConfig | None,
    ) -> None:
        self.session_factory = session_factory
        self.providers = providers
        self.config = config
        self.tracker = ActivityTracker(session_factory, config)
        self._paused: bool = False

    def request_pause(self) -> None:
        """Request synchronization to pause after the currently running wallet finishes."""
        self._paused = True

    def request_resume(self) -> None:
        """Clear pause state so subsequent sync operations process all wallets."""
        self._paused = False

    @property
    def is_paused(self) -> bool:
        """Check whether synchronization is currently requested to be paused."""
        return self._paused

    def _skip_paused_wallet(self, wallet_id: int, network: str | None = None) -> SyncReport:
        """Record a paused SyncJob and return a skipped SyncReport for a wallet."""
        now = datetime.now(UTC)
        target_net_name = network or "unknown"
        with self.session_factory() as session:
            wallet = session.get(Wallet, wallet_id)
            net_id: int | None = None
            if wallet is not None:
                net = self._resolve_network(session, wallet, network)
                if net is not None:
                    net_id = net.id
                    target_net_name = net.name

            job = SyncJob(
                wallet_id=wallet_id,
                network_id=net_id,
                job_type="wallet_sync",
                status="paused",
                started_at=now,
                finished_at=now,
                error_message="Sync paused by request",
                created_at=now,
            )
            session.add(job)
            session.commit()

        return SyncReport(
            wallet_id=wallet_id,
            network=target_net_name,
            status="skipped",
            error="Sync paused by request",
        )

    def _resolve_network(self, session: Session, wallet: Wallet, network_name: str | None) -> Network | None:
        """Resolve target Network model for a wallet sync operation."""
        if network_name:
            net = session.execute(
                select(Network).where(func.lower(Network.name) == network_name.strip().lower())
            ).scalar_one_or_none()
            if net is not None:
                return net

        # Check wallet monitored networks
        for wn in wallet.networks:
            if wn.monitoring_status == "active" and wn.network and wn.network.enabled:
                return wn.network

        # Fallback to first enabled network in DB
        net = session.execute(
            select(Network).where(Network.enabled == True).order_by(Network.id)
        ).scalar_one_or_none()
        return net

    def sync_wallet(self, wallet_id: int, network: str | None = None) -> SyncReport:
        """Synchronize native balance, transactions, and activities for a single wallet."""
        if self._paused:
            return self._skip_paused_wallet(wallet_id, network=network)

        with self.session_factory() as session:
            wallet = session.get(Wallet, wallet_id)
            if wallet is None:
                err = f"Wallet with id {wallet_id} not found"
                logger.warning("Sync failed: %s", err)
                return SyncReport(
                    wallet_id=wallet_id,
                    network=network or "unknown",
                    status="error",
                    error=err,
                )

            if wallet.archived:
                logger.info("Wallet %s is archived, skipping sync", wallet.address)
                return SyncReport(
                    wallet_id=wallet.id,
                    network=network or "unknown",
                    status="skipped",
                )

            net = self._resolve_network(session, wallet, network)
            if net is None:
                err = f"Network '{network}' not configured or available"
                logger.warning("Sync failed for wallet %s: %s", wallet.address, err)
                return SyncReport(
                    wallet_id=wallet.id,
                    network=network or "unknown",
                    status="error",
                    error=err,
                )

            net_id = net.id
            net_name = net.name

            # Start sync job
            now = datetime.now(UTC)
            job = SyncJob(
                wallet_id=wallet.id,
                network_id=net_id,
                job_type="wallet_sync",
                status="running",
                started_at=now,
                created_at=now,
            )
            session.add(job)
            session.flush()

            try:
                # 1. Read existing SyncCursor for incremental resume
                cursor_row = session.execute(
                    select(SyncCursor).where(
                        SyncCursor.wallet_id == wallet.id,
                        SyncCursor.network_id == net.id,
                        SyncCursor.data_type == "tx",
                    )
                ).scalar_one_or_none()

                provider_cursor: dict[str, Any] | None = None
                if cursor_row is not None and cursor_row.last_block_number is not None:
                    provider_cursor = {
                        "block": cursor_row.last_block_number,
                        "last_block": cursor_row.last_block_number,
                    }

                # 2. Fetch native balance
                bal_res = self.providers.get_native_balance(wallet.address, net.name)
                if bal_res.status == ProviderStatus.RATE_LIMITED:
                    err_msg = "Rate limited by provider: retry later"
                    job.status = "failed"
                    job.finished_at = datetime.now(UTC)
                    job.error_message = err_msg
                    session.commit()
                    logger.warning("Sync failed for wallet %s on %s using provider %s: %s", wallet.id, net.name, bal_res.source or "unknown", err_msg)
                    return SyncReport(
                        wallet_id=wallet.id,
                        network=net.name,
                        status="error",
                        error=err_msg,
                    )

                if bal_res.status != ProviderStatus.OK:
                    err_msg = bal_res.error or f"Failed to fetch balance from {bal_res.source or 'provider'}"
                    job.status = "failed"
                    job.finished_at = datetime.now(UTC)
                    job.error_message = err_msg
                    session.commit()
                    logger.warning("Sync failed for wallet %s on %s using provider %s: %s", wallet.id, net.name, bal_res.source or "unknown", err_msg)
                    return SyncReport(
                        wallet_id=wallet.id,
                        network=net.name,
                        status="error",
                        error=err_msg,
                    )

                balance_amount = bal_res.data
                if isinstance(balance_amount, float):
                    raise TypeError(f"balance amount from provider must be Decimal or int, got float: {balance_amount}")
                if not isinstance(balance_amount, Decimal):
                    balance_amount = Decimal(str(balance_amount))

                # 3. Fetch transactions
                tx_res = self.providers.get_transactions(wallet.address, net.name, cursor=provider_cursor)
                if tx_res.status == ProviderStatus.RATE_LIMITED:
                    err_msg = "Rate limited by provider: retry later"
                    job.status = "failed"
                    job.finished_at = datetime.now(UTC)
                    job.error_message = err_msg
                    session.commit()
                    logger.warning("Sync failed for wallet %s on %s using provider %s: %s", wallet.id, net.name, tx_res.source or "unknown", err_msg)
                    return SyncReport(
                        wallet_id=wallet.id,
                        network=net.name,
                        status="error",
                        error=err_msg,
                    )

                if tx_res.status != ProviderStatus.OK:
                    err_msg = tx_res.error or f"Failed to fetch transactions from {tx_res.source or 'provider'}"
                    job.status = "failed"
                    job.finished_at = datetime.now(UTC)
                    job.error_message = err_msg
                    session.commit()
                    logger.warning("Sync failed for wallet %s on %s using provider %s: %s", wallet.id, net.name, tx_res.source or "unknown", err_msg)
                    return SyncReport(
                        wallet_id=wallet.id,
                        network=net.name,
                        status="error",
                        error=err_msg,
                    )

                tx_items: list[TransactionItem] = []
                if isinstance(tx_res.data, TransactionListResult):
                    tx_items = tx_res.data.items
                elif isinstance(tx_res.data, list):
                    tx_items = tx_res.data

                # Determine latest block from transactions or provider
                processed_blocks = [tx.block_number for tx in tx_items if tx.block_number is not None]
                latest_block: int | None = max(processed_blocks) if processed_blocks else None

                # 4. Save BalanceSnapshot with idempotency check
                balance_saved = False
                existing_snap = session.execute(
                    select(BalanceSnapshot)
                    .where(
                        BalanceSnapshot.wallet_id == wallet.id,
                        BalanceSnapshot.network_id == net.id,
                    )
                    .order_by(BalanceSnapshot.id.desc())
                ).scalars().first()

                is_duplicate_snap = (
                    existing_snap is not None
                    and (
                        (latest_block is not None and existing_snap.block_number == latest_block)
                        or (latest_block is None and existing_snap.balance == balance_amount)
                    )
                )

                if not is_duplicate_snap:
                    save_native_balance(session, wallet, net, balance_amount, block_number=latest_block)
                    balance_saved = True

                # 5. Process transactions and activities
                activities_added = 0
                activities_updated = 0

                for tx_item in tx_items:
                    # Dedup Transaction
                    existing_tx = session.execute(
                        select(Transaction).where(
                            Transaction.wallet_id == wallet.id,
                            Transaction.network_id == net.id,
                            Transaction.tx_hash == tx_item.hash,
                        )
                    ).scalar_one_or_none()

                    if existing_tx is None:
                        raw_val = getattr(tx_item, "value", Decimal(0))
                        if isinstance(raw_val, float):
                            raise TypeError(f"Transaction value must be Decimal or int, got float: {raw_val}")
                        val_dec = Decimal(str(raw_val)) if raw_val is not None else Decimal(0)
                        tx_ts = _to_utc(getattr(tx_item, "timestamp", None))
                        tx_status = getattr(tx_item, "status", "ok")
                        status_str = "success" if str(tx_status).lower() in {"ok", "success", "confirmed"} else "failed"

                        to_addr_str = tx_item.to_address.lower() if tx_item.to_address else None

                        tx_record = Transaction(
                            wallet_id=wallet.id,
                            network_id=net.id,
                            tx_hash=tx_item.hash,
                            block_number=tx_item.block_number,
                            from_address=tx_item.from_address.lower(),
                            to_address=to_addr_str,
                            value=val_dec,
                            gas_price=getattr(tx_item, "gas_price", None),
                            gas_used=getattr(tx_item, "gas_used", None),
                            status=status_str,
                            occurred_at=tx_ts,
                            source="chain",
                            is_manual=False,
                        )
                        session.add(tx_record)
                        session.flush()

                    # Dedup Activity
                    log_idx = getattr(tx_item, "log_index", None) or 0
                    existing_act = session.execute(
                        select(Activity).where(
                            Activity.wallet_id == wallet.id,
                            Activity.tx_hash == tx_item.hash,
                            Activity.log_index == log_idx,
                        )
                    ).scalar_one_or_none()

                    if existing_act is None:
                        self.tracker.record(session, wallet, net, tx_item)
                        activities_added += 1

                # 6. Update SyncCursor
                if cursor_row is None:
                    cursor_row = SyncCursor(
                        wallet_id=wallet.id,
                        network_id=net.id,
                        data_type="tx",
                        cursor_value=str(latest_block or 0),
                        last_block_number=latest_block,
                        updated_at=datetime.now(UTC),
                    )
                    session.add(cursor_row)
                else:
                    if latest_block is not None:
                        prev_block = cursor_row.last_block_number or 0
                        new_block = max(prev_block, latest_block)
                        cursor_row.last_block_number = new_block
                        cursor_row.cursor_value = str(new_block)
                        cursor_row.updated_at = datetime.now(UTC)

                # 7. Update WalletNetwork last_sync_at
                wn = session.execute(
                    select(WalletNetwork).where(
                        WalletNetwork.wallet_id == wallet.id,
                        WalletNetwork.network_id == net.id,
                    )
                ).scalar_one_or_none()
                if wn is not None:
                    wn.last_sync_at = datetime.now(UTC)

                # 8. Complete SyncJob
                job.status = "completed"
                job.finished_at = datetime.now(UTC)
                job.error_message = None
                session.commit()

                logger.info(
                    "Wallet %s synced on %s: %d activities added, %d updated, balance_saved=%s",
                    wallet.address,
                    net.name,
                    activities_added,
                    activities_updated,
                    balance_saved,
                )

                return SyncReport(
                    wallet_id=wallet.id,
                    network=net.name,
                    status="ok",
                    activities_added=activities_added,
                    activities_updated=activities_updated,
                    balance_saved=balance_saved,
                    error=None,
                )
            except Exception as exc:  # noqa: BLE001
                err_msg = str(exc)
                try:
                    session.rollback()
                except SQLAlchemyError as rb_exc:
                    logger.debug("Failed to rollback session: %s", rb_exc)

                target_net_name = net_name if "net_name" in locals() else (network or "unknown")
                logger.warning("Sync failed for wallet %s on %s: %s", wallet_id, target_net_name, err_msg)

                if "net_id" in locals() and "now" in locals():
                    try:
                        failed_job = SyncJob(
                            wallet_id=wallet_id,
                            network_id=net_id,
                            job_type="wallet_sync",
                            status="failed",
                            started_at=now,
                            finished_at=datetime.now(UTC),
                            error_message=err_msg,
                            created_at=now,
                        )
                        session.add(failed_job)
                        session.commit()
                    except SQLAlchemyError as job_exc:
                        logger.debug("Failed to record failed sync job: %s", job_exc)
                        try:
                            session.rollback()
                        except SQLAlchemyError as rb2_exc:
                            logger.debug("Failed second rollback: %s", rb2_exc)

                return SyncReport(
                    wallet_id=wallet_id,
                    network=target_net_name,
                    status="error",
                    error=err_msg,
                )

    def sync_all(self, network: str | None = None) -> list[SyncReport]:
        """Synchronize all active wallets with error isolation across wallets."""
        with self.session_factory() as session:
            wallets = list(
                session.execute(
                    select(Wallet).where(Wallet.archived == False).order_by(Wallet.id)
                ).scalars().all()
            )
            wallet_ids = [w.id for w in wallets]

        reports: list[SyncReport] = []
        for wid in wallet_ids:
            if self._paused:
                reports.append(self._skip_paused_wallet(wid, network=network))
                continue

            try:
                report = self.sync_wallet(wid, network=network)
                reports.append(report)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Sync failed for wallet %s on %s: %s", wid, network or "default", exc)
                reports.append(
                    SyncReport(
                        wallet_id=wid,
                        network=network or "unknown",
                        status="error",
                        error=str(exc),
                    )
                )

        return reports
