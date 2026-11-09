"""Factories для тестовых данных (test data).

Фабрики создают и возвращают объекты в переданной session. Явные аргументы —
без скрытых зависимостей. Детерминированные значения по умолчанию.

Использование:
    from tests.fixtures.factories import make_wallet

    with app.state.session_factory() as session:
        wallet = make_wallet(session, name="TestWallet1")
"""

from __future__ import annotations

from typing import Any

from app.database.models import Wallet

DEFAULT_ADDRESS = "0x111122223333444455556667777888899990000a"
DEFAULT_WALLET_NAME = "TestWallet1"


def make_wallet(
    session: Any,
    address: str = DEFAULT_ADDRESS,
    name: str = DEFAULT_WALLET_NAME,
    chain_type: str = "evm",
    **kwargs: Any,
) -> Wallet:
    """Create and persist a Wallet. Returns the attached instance."""
    wallet = Wallet(address=address, name=name, chain_type=chain_type, **kwargs)
    session.add(wallet)
    session.commit()
    session.refresh(wallet)
    return wallet
