from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import app.reasoning.context.user_snapshot as us
from app.reasoning.context.user_snapshot import build_user_snapshot


@pytest.mark.asyncio
async def test_build_user_snapshot_reads_portfolio_and_preferences(monkeypatch):
    monkeypatch.setattr(
        us,
        "_list_portfolio",
        AsyncMock(return_value=[SimpleNamespace(ts_code="300308.SZ", stock_name="中际旭创")]),
    )
    pref_collection = MagicMock()
    pref_collection.find_one = AsyncMock(return_value={
        "items": [{"subject": "光模块", "subject_type": "concept", "stance": "关注", "reason": "AI算力"}]
    })
    monkeypatch.setattr(us, "_get_collection", lambda name: pref_collection)

    snapshot, warnings = await build_user_snapshot("lwm")

    assert warnings == []
    assert snapshot.portfolio == [{"ts_code": "300308.SZ", "name": "中际旭创"}]
    assert snapshot.preferences[0]["subject"] == "光模块"


@pytest.mark.asyncio
async def test_build_user_snapshot_fail_soft_on_portfolio_error(monkeypatch):
    async def raise_portfolio(*args, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(us, "_list_portfolio", raise_portfolio)
    pref_collection = MagicMock()
    pref_collection.find_one = AsyncMock(return_value=None)
    monkeypatch.setattr(us, "_get_collection", lambda name: pref_collection)

    snapshot, warnings = await build_user_snapshot("lwm")

    assert snapshot.portfolio == []
    assert "portfolio_read_failed" in warnings
