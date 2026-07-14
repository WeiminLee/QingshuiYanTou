from unittest.mock import AsyncMock, MagicMock

import pytest

import app.reasoning.langchain_agent.memory.user_memory_provider as ump
from app.reasoning.langchain_agent.memory.user_memory_provider import UserMemoryProvider


def _setup(monkeypatch, profile=None, prefs=None, notes=None, portfolio=None):
    def factory(name):
        c = MagicMock()
        if name == ump.PROFILE_COLLECTION:
            c.find_one = AsyncMock(return_value={"profile": profile} if profile else None)
        elif name == ump.PREF_COLLECTION:
            c.find_one = AsyncMock(return_value={"items": prefs} if prefs else None)
        elif name == ump.NOTES_COLLECTION:
            c.find_one = AsyncMock(return_value={"entries": notes} if notes else None)
        else:
            c.find_one = AsyncMock(return_value=None)
        return c

    monkeypatch.setattr(ump, "_get_collection", factory)

    async def fake_portfolio(uid):
        return portfolio or []

    monkeypatch.setattr(ump, "fetch_portfolio_lines", fake_portfolio)


@pytest.mark.asyncio
async def test_empty_memory_returns_empty_block(monkeypatch):
    _setup(monkeypatch)
    p = UserMemoryProvider(); p.initialize("lwm")
    assert await p.prefetch("q") == "<user-memory></user-memory>"


@pytest.mark.asyncio
async def test_prefetch_contains_all_sections(monkeypatch):
    _setup(
        monkeypatch,
        profile="偏好科技成长股",
        prefs=[{"subject": "光模块", "subject_type": "sector", "stance": "看好", "reason": "AI算力"}],
        notes=[{"content": "年底想减仓", "category": "general"}],
        portfolio=["中际旭创(300308.SZ)"],
    )
    p = UserMemoryProvider(); p.initialize("lwm")
    out = await p.prefetch("q")
    assert "<profile>偏好科技成长股</profile>" in out
    assert "[看好] 光模块(sector)：AI算力" in out
    assert "中际旭创(300308.SZ)" in out
    assert "年底想减仓" in out


@pytest.mark.asyncio
async def test_prefetch_truncates_notes_first(monkeypatch):
    big_notes = [{"content": "x" * 500, "category": "general"} for _ in range(50)]
    _setup(monkeypatch, profile="P", prefs=[{"subject": "光模块", "subject_type": "sector", "stance": "看好", "reason": ""}], notes=big_notes)
    p = UserMemoryProvider(); p.initialize("lwm")
    out = await p.prefetch("q")
    assert "<profile>P</profile>" in out          # profile 保留
    assert "光模块" in out                          # preferences 保留
    assert len(out) <= ump.MAX_PREFETCH_TOKENS * 4 + 200  # 截断生效
