"""Activity tracker for recording and classifying blockchain activities."""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select

from app.database.models import Activity, Network, ProjectContract, Wallet

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker

    from app.config import AppConfig

logger = logging.getLogger(__name__)


def _to_utc(dt: datetime | None) -> datetime:
    """Ensure datetime is UTC and timezone-aware."""
    if dt is None:
        return datetime.now(UTC)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


class ActivityTracker:
    """Manages classification and persistence of wallet activities."""

    def __init__(self, session_factory: sessionmaker[Session] | None, config: AppConfig | None) -> None:
        self.session_factory = session_factory
        self.config = config

    def classify(
        self,
        wallet_address: str,
        tx: Any,
        network_id: int | None = None,
        session: Session | None = None,
    ) -> str:
        """Classify a transaction relative to wallet address.

        Returns one of: "self", "contract_call", "send", "receive".
        """
        w_addr = wallet_address.strip().lower()
        from_addr = (getattr(tx, "from_address", None) or "").strip().lower()
        to_addr_raw = getattr(tx, "to_address", None)
        to_addr = to_addr_raw.strip().lower() if to_addr_raw else None

        # 1. Self transfer: wallet sends to itself
        if from_addr == w_addr and to_addr == w_addr:
            return "self"

        # 2. Contract call to a known ProjectContract
        if to_addr:
            sess = session
            should_close = False
            if sess is None and self.session_factory is not None:
                sess = self.session_factory()
                should_close = True

            if sess is not None:
                try:
                    stmt = select(ProjectContract).where(
                        func.lower(ProjectContract.contract_address) == to_addr
                    )
                    if network_id is not None:
                        stmt = stmt.where(ProjectContract.network_id == network_id)
                    pc = sess.execute(stmt).scalar_one_or_none()
                    if pc is not None:
                        return "contract_call"
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Error checking project contracts in classify: %s", exc)
                finally:
                    if should_close:
                        sess.close()

        # 3. Standard send
        if from_addr == w_addr:
            return "send"

        # 4. Standard receive
        if to_addr == w_addr:
            return "receive"

        # Default fallback
        return "contract_call"

    def record(self, session: Session, wallet: Wallet | int, network: Network | int | str, tx: Any) -> Activity:
        """Record an activity event derived from a transaction item.

        Idempotent by (wallet_id, tx_hash, log_index).
        """
        # Resolve wallet instance
        if isinstance(wallet, Wallet):
            w = wallet
        else:
            w = session.get(Wallet, int(wallet))
            if w is None:
                raise ValueError(f"Wallet with id {wallet} not found")

        # Resolve network instance
        if isinstance(network, Network):
            net = network
        elif isinstance(network, int):
            net = session.get(Network, network)
            if net is None:
                raise ValueError(f"Network with id {network} not found")
        else:
            net = session.execute(
                select(Network).where(func.lower(Network.name) == str(network).strip().lower())
            ).scalar_one_or_none()
            if net is None:
                raise ValueError(f"Network '{network}' not found")

        tx_hash = getattr(tx, "hash", None)
        if not tx_hash:
            raise ValueError("Transaction item must have a valid hash")

        log_index_val = getattr(tx, "log_index", None)
        log_index = log_index_val if log_index_val is not None else 0

        # Idempotency check: dedup by (wallet_id, tx_hash, log_index)
        existing = session.execute(
            select(Activity).where(
                Activity.wallet_id == w.id,
                Activity.tx_hash == tx_hash,
                Activity.log_index == log_index,
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing

        to_addr_raw = getattr(tx, "to_address", None)
        to_addr = to_addr_raw.strip().lower() if to_addr_raw else None

        # Project detection lookup over project_contracts by (network_id, lower(address))
        project_id: int | None = None
        source = "chain"
        activity_type: str

        if to_addr:
            stmt = select(ProjectContract).where(
                ProjectContract.network_id == net.id,
                func.lower(ProjectContract.contract_address) == to_addr,
            )
            pc = session.execute(stmt).scalar_one_or_none()
            if pc is not None:
                project_id = pc.project_id
                source = "detected"
                activity_type = "contract_call"
            else:
                activity_type = self.classify(w.address, tx, network_id=net.id, session=session)
        else:
            activity_type = self.classify(w.address, tx, network_id=net.id, session=session)

        # Parse amount as Decimal
        val = getattr(tx, "value", Decimal(0))
        if isinstance(val, float):
            raise TypeError(f"Transaction value must be Decimal or int, got float: {val}")
        amount_dec = Decimal(str(val)) if val is not None else Decimal(0)

        # Parse timestamp
        raw_ts = getattr(tx, "timestamp", None)
        occurred_at = _to_utc(raw_ts)

        # Status mapping
        raw_status = getattr(tx, "status", "ok")
        act_status = "confirmed" if str(raw_status).lower() in {"ok", "confirmed", "success"} else "failed"

        # Explorer URL
        explorer_url: str | None = None
        if net.explorer_url and tx_hash:
            explorer_url = f"{net.explorer_url.rstrip('/')}/tx/{tx_hash}"

        contract_addr = to_addr if activity_type == "contract_call" else None

        act = Activity(
            wallet_id=w.id,
            network_id=net.id,
            project_id=project_id,
            tx_hash=tx_hash,
            log_index=log_index,
            activity_type=activity_type,
            occurred_at=occurred_at,
            contract_address=contract_addr,
            token_symbol=getattr(tx, "token_symbol", None) or net.native_token,
            amount=amount_dec,
            status=act_status,
            source=source,
            is_manual=False,
            explorer_url=explorer_url,
            extra_data=getattr(tx, "extra_data", None),
        )
        session.add(act)
        session.flush()

        # Update wallet activity timestamps if applicable
        if w.first_activity_at is None or occurred_at < _to_utc(w.first_activity_at):
            w.first_activity_at = occurred_at
        if w.last_activity_at is None or occurred_at > _to_utc(w.last_activity_at):
            w.last_activity_at = occurred_at

        return act
