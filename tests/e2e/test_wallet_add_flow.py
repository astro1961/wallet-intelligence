"""E2E test: adding wallet and verifying its presence on dashboard panel."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.application import WalletTrackerApp
from app.database.models import Wallet


@pytest.mark.asyncio
async def test_wallet_add_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    """E2E flow:
    1) Start Textual WalletTrackerApp (WIT_DB_PATH=/tmp/qa_e2e.db, remove old DB before start).
    2) Navigate to Wallets.
    3) Add wallet to test DB using models (app.state.session_factory).
    4) Return to Dashboard (nav_to dashboard).
    5) Verify that the wallet appears in #panel-wallets.
    """
    db_path = Path("/tmp/qa_e2e.db")
    if db_path.exists():
        db_path.unlink()

    monkeypatch.setenv("WIT_DB_PATH", str(db_path))

    app = WalletTrackerApp()
    async with app.run_test(size=(140, 40)) as pilot:
        # Step 1: Verify app started on dashboard
        assert app.screen.id == "dashboard"
        await pilot.pause()

        # Step 2: Open Wallets screen
        app.nav_to("wallets")
        await pilot.pause()
        assert app.screen.id == "wallets"

        # Step 3: Add wallet into test DB via models and app.state.session_factory
        assert app.state.session_factory is not None
        wallet_name = "TestWallet1"
        wallet_address = "0x111122223333444455556667777888899990000a"
        with app.state.session_factory() as session:
            wallet = Wallet(
                address=wallet_address,
                name=wallet_name,
                chain_type="evm",
            )
            session.add(wallet)
            session.commit()

        # Step 4: Return to Dashboard (nav_to dashboard)
        app.nav_to("dashboard")
        await pilot.pause()
        assert app.screen.id == "dashboard"

        # Step 5: Verify wallet appears in panel #panel-wallets
        panel = app.screen.query_one("#panel-wallets")
        rendered = str(panel.renderable if hasattr(panel, "renderable") else panel.render())

        assert (
            wallet_name in rendered or "0x1111...000a" in rendered
        ), f"Added wallet not found in #panel-wallets content:\n{rendered}"
