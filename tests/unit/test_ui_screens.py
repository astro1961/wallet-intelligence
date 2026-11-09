"""Unit tests for screen rendering, adaptivity, and empty states."""
from __future__ import annotations

from pathlib import Path

import pytest

SCREEN_KEYS = [
    "dashboard",
    "wallets",
]


@pytest.mark.parametrize("idx", range(1, 3))
@pytest.mark.asyncio
async def test_all_screens_render_without_crashing_at_sizes(idx: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Requirement 5: each screen renders its empty state without errors at 100x30 and 60x20."""
    db_file = tmp_path / f"screens_render_{idx}.db"
    monkeypatch.setenv("WIT_DB_PATH", str(db_file))

    from app.application import WalletTrackerApp

    app = WalletTrackerApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.press(str(idx))
        await pilot.pause()

        # Adaptivity check down to 60x20
        await pilot.resize_terminal(60, 20)
        await pilot.pause()

        # Restore size
        await pilot.resize_terminal(100, 30)
        await pilot.pause()


@pytest.mark.parametrize("idx,key", list(enumerate(SCREEN_KEYS, start=1)))
@pytest.mark.asyncio
async def test_screen_empty_states_contain_descriptions_and_stage(
    idx: int, key: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Empty states: each screen shows its title, one line of what belongs there, and stage."""
    db_file = tmp_path / f"empty_states_{idx}.db"
    monkeypatch.setenv("WIT_DB_PATH", str(db_file))

    from app.application import WalletTrackerApp

    app = WalletTrackerApp()
    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.press(str(idx))
        await pilot.pause()

        # Check screen has empty state elements
        assert app.screen.id == key
        title_node = app.screen.query_one(".screen-title")
        assert title_node is not None
        assert len(str(title_node.render())) > 0

        desc_node = app.screen.query_one(".screen-desc")
        assert desc_node is not None
        assert len(str(desc_node.render())) > 0

        stage_node = app.screen.query_one(".screen-stage")
        assert stage_node is not None
        assert "Stage" in str(stage_node.render())
