from unittest.mock import AsyncMock, MagicMock

import pytest

import app.reasoning.langchain_agent.memory.portfolio_reader as pr


class _Pos:
    def __init__(self, ts_code, stock_name):
        self.ts_code = ts_code
        self.stock_name = stock_name


@pytest.mark.asyncio
async def test_formats_positions(monkeypatch):
    async def fake_list(session, user_id):
        return [_Pos("300308.SZ", "中际旭创"), _Pos("300502.SZ", "新易盛")]

    # async context manager 模拟 async_session()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value="SESSION")
    cm.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(pr, "async_session", lambda: cm)
    monkeypatch.setattr(pr, "_list_for_user", fake_list)

    lines = await pr.fetch_portfolio_lines("lwm")
    assert lines == ["中际旭创(300308.SZ)", "新易盛(300502.SZ)"]


@pytest.mark.asyncio
async def test_db_error_returns_empty(monkeypatch):
    def boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(pr, "async_session", boom)
    lines = await pr.fetch_portfolio_lines("lwm")
    assert lines == []


@pytest.mark.asyncio
async def test_no_positions_returns_empty(monkeypatch):
    async def fake_list(session, user_id):
        return []

    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value="SESSION")
    cm.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(pr, "async_session", lambda: cm)
    monkeypatch.setattr(pr, "_list_for_user", fake_list)

    assert await pr.fetch_portfolio_lines("lwm") == []
