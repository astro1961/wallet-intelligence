"""DeFi portfolio analyzer: token balance snapshots, protocol positions, and aggregation."""
from __future__ import annotations

import logging
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.database.models import (
    BalanceSnapshot,
    DeFiPosition,
    Network,
    Token,
    Wallet,
    utc_now,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import sessionmaker

    from app.config import AppConfig

logger = logging.getLogger(__name__)

VALID_CERTAINTIES: frozenset[str] = frozenset({"confirmed", "inferred", "unknown"})


class DeFiAnalyzer:
    """Analyzer managing DeFi protocol positions, token balance snapshots, and aggregation."""

    def __init__(
        self,
        session_factory: sessionmaker[Session] | Session,
        price_provider: Any = None,
        config: AppConfig | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.price_provider = price_provider
        self.config = config

    @contextmanager
    def _session(self) -> Generator[Session, None, None]:
        if isinstance(self.session_factory, Session):
            yield self.session_factory
        elif callable(self.session_factory):
            sess = self.session_factory()
            sess.expire_on_commit = False
            try:
                yield sess
                sess.commit()
            except Exception:
                sess.rollback()
                raise
            finally:
                sess.close()
        else:
            raise TypeError(f"Invalid session_factory: {type(self.session_factory).__name__}")

    def _resolve_price(self, chain: str, contract_address: str) -> Decimal | None:
        if self.price_provider is None:
            return None

        try:
            res = self.price_provider.get_token_price(chain, contract_address)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Price provider failed for chain=%s token=%s: %s",
                chain,
                contract_address,
                exc,
            )
            return None

        if res is None:
            return None

        # Check for ProviderResult object (status, data)
        if hasattr(res, "status") and hasattr(res, "data"):
            from app.providers.base import ProviderStatus

            if res.status != ProviderStatus.OK or res.data is None:
                return None
            res_data = res.data
            if isinstance(res_data, Decimal):
                return res_data
            try:
                return Decimal(str(res_data))
            except (InvalidOperation, ValueError, TypeError) as exc:
                logger.warning("Failed converting ProviderResult data to Decimal: %s", exc)
                return None

        if isinstance(res, Decimal):
            return res

        try:
            return Decimal(str(res))
        except (InvalidOperation, ValueError, TypeError) as exc:
            logger.warning("Failed converting provider result to Decimal: %s", exc)
            return None

    def snapshot_token_balance(
        self,
        wallet: Wallet | int,
        network: Network | int | str,
        token: Token | int,
        raw_balance: Decimal | int,
    ) -> BalanceSnapshot:
        """Create and persist a point-in-time snapshot of a token balance with price lookup."""
        if type(raw_balance).__name__ == "float":
            raise TypeError(f"raw_balance must be Decimal or int, got float: {raw_balance}")
        if not isinstance(raw_balance, (Decimal, int)):
            raise TypeError(f"raw_balance must be Decimal or int, got {type(raw_balance).__name__}")

        with self._session() as session:
            # Resolve wallet id
            if isinstance(wallet, Wallet) or hasattr(wallet, "id"):
                w_id = wallet.id
            else:
                w_id = int(wallet)

            # Resolve network id and name
            if isinstance(network, Network) or hasattr(network, "name") and hasattr(network, "id"):
                net_id = network.id
                net_name = network.name
            elif isinstance(network, int):
                net_obj = session.get(Network, network)
                if net_obj is None:
                    raise ValueError(f"Network with id {network} not found")
                net_id = net_obj.id
                net_name = net_obj.name
            elif isinstance(network, str):
                net_obj = session.execute(
                    select(Network).where(func.lower(Network.name) == network.strip().lower())
                ).scalar_one_or_none()
                if net_obj is None:
                    raise ValueError(f"Network with name '{network}' not found")
                net_id = net_obj.id
                net_name = net_obj.name
            else:
                raise TypeError(f"Unsupported network identifier: {network}")

            # Resolve token id, contract_address, and decimals
            if isinstance(token, Token):
                tok_id = token.id
                tok_addr = token.contract_address
                tok_dec = token.decimals
            elif hasattr(token, "contract_address") and hasattr(token, "decimals"):
                tok_id = getattr(token, "id", None)
                tok_addr = token.contract_address
                tok_dec = token.decimals
            elif isinstance(token, int):
                tok_obj = session.get(Token, token)
                if tok_obj is None:
                    raise ValueError(f"Token with id {token} not found")
                tok_id = tok_obj.id
                tok_addr = tok_obj.contract_address
                tok_dec = tok_obj.decimals
            else:
                raise TypeError(f"Unsupported token identifier: {token}")

            raw_dec = Decimal(str(raw_balance))
            decimals_int = int(tok_dec) if tok_dec is not None else 18
            divisor = Decimal(10) ** Decimal(decimals_int)
            balance = raw_dec / divisor

            price = self._resolve_price(net_name, tok_addr)
            if price is not None:
                usd_price = price
                usd_value = balance * price
            else:
                usd_price = None
                usd_value = None

            snapshot = BalanceSnapshot(
                wallet_id=w_id,
                network_id=net_id,
                token_id=tok_id,
                raw_balance=str(raw_balance),
                balance=balance,
                usd_price=usd_price,
                usd_value=usd_value,
                snapshot_at=utc_now(),
            )
            session.add(snapshot)
            session.commit()
            return snapshot

    def upsert_position(
        self,
        wallet: Wallet | int,
        network: Network | int | str,
        protocol: str,
        position_type: str,
        amount: Decimal | None = None,
        usd_value: Decimal | None = None,
        certainty: str = "confirmed",
        details: str | None = None,
    ) -> DeFiPosition:
        """Upsert a DeFi position idempotently per (wallet, network, protocol, position_type)."""
        if certainty not in VALID_CERTAINTIES:
            raise ValueError(
                f"Invalid certainty '{certainty}'. Must be one of: {sorted(VALID_CERTAINTIES)}"
            )

        if not protocol or not str(protocol).strip():
            raise ValueError("protocol cannot be empty")
        if not position_type or not str(position_type).strip():
            raise ValueError("position_type cannot be empty")

        if type(amount).__name__ == "float":
            raise TypeError(f"amount must be Decimal or int, got float: {amount}")
        if type(usd_value).__name__ == "float":
            raise TypeError(f"usd_value must be Decimal or int, got float: {usd_value}")

        proto_str = str(protocol).strip()
        ptype_str = str(position_type).strip()

        amt_dec: Decimal | None = None
        if amount is not None:
            amt_dec = amount if isinstance(amount, Decimal) else Decimal(str(amount))

        val_dec: Decimal | None = None
        if usd_value is not None:
            val_dec = usd_value if isinstance(usd_value, Decimal) else Decimal(str(usd_value))

        with self._session() as session:
            # Resolve wallet id
            if isinstance(wallet, Wallet) or hasattr(wallet, "id"):
                w_id = wallet.id
            else:
                w_id = int(wallet)

            # Resolve network id
            if isinstance(network, Network) or hasattr(network, "id"):
                net_id = network.id
            elif isinstance(network, int):
                net_id = network
            elif isinstance(network, str):
                net_obj = session.execute(
                    select(Network).where(func.lower(Network.name) == network.strip().lower())
                ).scalar_one_or_none()
                if net_obj is None:
                    raise ValueError(f"Network with name '{network}' not found")
                net_id = net_obj.id
            else:
                raise TypeError(f"Unsupported network identifier: {network}")

            existing = session.execute(
                select(DeFiPosition).where(
                    DeFiPosition.wallet_id == w_id,
                    DeFiPosition.network_id == net_id,
                    DeFiPosition.protocol == proto_str,
                    DeFiPosition.position_type == ptype_str,
                )
            ).scalar_one_or_none()

            now = utc_now()
            if existing is not None:
                existing.amount = amt_dec
                existing.usd_value = val_dec
                existing.certainty = certainty
                existing.details = details
                existing.last_updated_at = now
                session.commit()
                return existing

            pos = DeFiPosition(
                wallet_id=w_id,
                network_id=net_id,
                protocol=proto_str,
                position_type=ptype_str,
                amount=amt_dec,
                usd_value=val_dec,
                certainty=certainty,
                details=details,
                last_updated_at=now,
                created_at=now,
            )
            session.add(pos)
            session.commit()
            return pos

    def list_positions(self, wallet_id: int | None = None) -> list[DeFiPosition]:
        """List DeFi positions, optionally filtered by wallet_id."""
        with self._session() as session:
            stmt = select(DeFiPosition).options(joinedload(DeFiPosition.network))
            if wallet_id is not None:
                stmt = stmt.where(DeFiPosition.wallet_id == int(wallet_id))
            stmt = stmt.order_by(DeFiPosition.id.asc())
            return list(session.execute(stmt).scalars().all())

    def aggregate(self, wallet_id: int | None = None) -> dict[str, Any]:
        """Compute aggregated portfolio figures separated by certainty, protocol, and network."""
        with self._session() as session:
            stmt = select(DeFiPosition).options(joinedload(DeFiPosition.network))
            if wallet_id is not None:
                stmt = stmt.where(DeFiPosition.wallet_id == int(wallet_id))
            positions = list(session.execute(stmt).scalars().all())

        total_value = Decimal(0)
        by_protocol: dict[str, Decimal] = {}
        by_network: dict[str, Decimal] = {}
        by_certainty: dict[str, Decimal] = {
            "confirmed": Decimal(0),
            "inferred": Decimal(0),
            "unknown": Decimal(0),
        }

        for pos in positions:
            val = pos.usd_value if pos.usd_value is not None else Decimal(0)
            total_value += val

            by_protocol[pos.protocol] = by_protocol.get(pos.protocol, Decimal(0)) + val

            net_name = pos.network.name if pos.network else f"network_{pos.network_id}"
            by_network[net_name] = by_network.get(net_name, Decimal(0)) + val

            cert = pos.certainty
            if cert in by_certainty:
                by_certainty[cert] += val
            else:
                by_certainty[cert] = val

        return {
            "total_value": total_value,
            "by_protocol": by_protocol,
            "by_network": by_network,
            "by_certainty": by_certainty,
        }

    def value_history(self, wallet_id: int | None = None, limit: int = 100) -> list[dict[str, Any]]:
        """Return historical balance snapshots ordered oldest to newest."""
        with self._session() as session:
            stmt = select(BalanceSnapshot)
            if wallet_id is not None:
                stmt = stmt.where(BalanceSnapshot.wallet_id == int(wallet_id))
            stmt = stmt.order_by(BalanceSnapshot.snapshot_at.asc(), BalanceSnapshot.id.asc())
            if limit is not None and limit > 0:
                stmt = stmt.limit(int(limit))
            snapshots = list(session.execute(stmt).scalars().all())

        history: list[dict[str, Any]] = []
        for s in snapshots:
            snap_dt = s.snapshot_at
            if snap_dt.tzinfo is None:
                snap_dt = snap_dt.replace(tzinfo=UTC)
            snap_dt = snap_dt.astimezone(UTC)

            bal_dec = s.balance if isinstance(s.balance, Decimal) else Decimal(str(s.balance))
            usd_dec = (
                s.usd_value
                if (s.usd_value is None or isinstance(s.usd_value, Decimal))
                else Decimal(str(s.usd_value))
            )

            history.append({
                "snapshot_at": snap_dt,
                "balance": bal_dec,
                "usd_value": usd_dec,
            })
        return history
