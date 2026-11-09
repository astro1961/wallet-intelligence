"""E2E: экраны с загруженными данными (activities, projects, graph)."""

from __future__ import annotations

import pytest
from textual.widgets import DataTable

from app.application import WalletTrackerApp
from app.database.models import Activity, Network, Project
from tests.fixtures.factories import make_wallet

pytestmark = pytest.mark.skip(reason="Screens Activities/Projects/Graph disabled (only Dashboard/Wallets)")


async def test_activities_screen_shows_activity(app_env) -> None:
    """Созданная активность видна на экране Activities."""
    app = WalletTrackerApp()
    async with app.run_test(size=(140, 40)) as pilot:
        with app.state.session_factory() as session:
            w = make_wallet(session)
            net = Network(name="Ethereum", chain_type="evm", chain_id=1)
            session.add(net)
            session.commit()
            session.add(
                Activity(wallet_id=w.id, network_id=net.id, activity_type="swap", token_symbol="ETH")
            )
            session.commit()

        app.nav_to("activities")
        await pilot.pause()
        text = str(app.screen.query_one("#activities-feed-text").render())
        assert "swap" in text.lower(), f"activity not shown: {text[:300]}"


async def test_projects_screen_shows_project(app_env) -> None:
    """Созданный проект виден в таблице Projects."""
    app = WalletTrackerApp()
    async with app.run_test(size=(140, 40)) as pilot:
        with app.state.session_factory() as session:
            session.add(Project(name="Uniswap", category="defi"))
            session.commit()

        app.nav_to("projects")
        await pilot.pause()
        table = app.screen.query_one("#projects-table", DataTable)
        assert table.row_count >= 1


async def test_graph_screen_with_wallet(app_env) -> None:
    """Graph рендерится при наличии кошелька без исключений."""
    app = WalletTrackerApp()
    async with app.run_test(size=(140, 40)) as pilot:
        with app.state.session_factory() as session:
            make_wallet(session)

        app.nav_to("graph")
        await pilot.pause()
        assert app.screen.id == "graph"
