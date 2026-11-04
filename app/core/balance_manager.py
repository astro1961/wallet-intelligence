"""Balance persistence and snapshot management."""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from app.database.models import BalanceSnapshot, Network, Wallet

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def save_native_balance(
    session: Session,
    wallet: Wallet | int,
    network: Network | int,
    amount: Decimal | int,
    block_number: int | None = None,
) -> BalanceSnapshot:
    """Persist a point-in-time snapshot of raw native currency balance (in wei).

    Args:
        session: Active SQLAlchemy database session.
        wallet: Wallet model instance or integer wallet_id.
        network: Network model instance or integer network_id.
        amount: Raw balance amount in wei as Decimal or int. Never float.
        block_number: Optional block number at which balance was observed.

    Returns:
        Created and flushed BalanceSnapshot record.
    """
    if isinstance(amount, float):
        raise TypeError(f"amount must be Decimal or int, got float: {amount}")

    if not isinstance(amount, (Decimal, int)):
        raise TypeError(f"amount must be Decimal or int, got {type(amount).__name__}")

    wallet_id = wallet.id if isinstance(wallet, Wallet) else int(wallet)
    network_id = network.id if isinstance(network, Network) else int(network)

    amount_dec = Decimal(str(amount))
    now_utc = datetime.now(UTC)

    snapshot = BalanceSnapshot(
        wallet_id=wallet_id,
        network_id=network_id,
        token_id=None,
        raw_balance=str(amount),
        balance=amount_dec,
        usd_price=None,
        usd_value=None,
        block_number=block_number,
        snapshot_at=now_utc,
    )
    session.add(snapshot)
    session.flush()
    return snapshot
