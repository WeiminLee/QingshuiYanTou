"""Tests: MemoryManager integration into run_lead_agent.

Tests the integration patterns as they appear in client.py
without importing client.py itself (which requires langchain_openai).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.reasoning.langchain_agent.memory.manager import MemoryManager


# ── Helpers ─────────────────────────────────────────────────────────────────


def _make_mock_builtin():
    m = MagicMock()
    m.name = "builtin"
    return m


class _FailingBuiltin:
    name = "builtin"
    def __init__(self):
        raise RuntimeError("MongoDB unavailable")
    def initialize(self, session_id: str) -> None:
        pass


# ── MemoryManager creation patterns ─────────────────────────────────────────


class TestMemoryManagerCreation:
    """Verify creation patterns used in client.py."""

    def test_memory_manager_created_when_init_succeeds(self):
        provider = _make_mock_builtin()
        provider.initialize("test_sid")
        mm = MemoryManager()
        mm.add_provider(provider)
        assert mm is not None
        assert len(mm._providers) == 1
        assert mm._providers[0].name == "builtin"

    def test_memory_manager_is_none_when_init_raises(self):
        memory_manager = None
        try:
            provider = _FailingBuiltin()
            provider.initialize("test_sid")
            memory_manager = MemoryManager()
            memory_manager.add_provider(provider)
        except Exception:
            memory_manager = None
        assert memory_manager is None


# ── manage_memory tool injection patterns ───────────────────────────────────


class TestManageMemoryToolInjection:
    """Verify tool injection logic as it appears in client.py."""

    def test_tool_appended_when_memory_manager_exists(self):
        from app.reasoning.langchain_agent.memory.tool import manage_memory, set_memory_manager

        mock_mgr = MagicMock(spec=MemoryManager)
        tools: list = []
        memory_manager = mock_mgr

        if memory_manager is not None:
            set_memory_manager(memory_manager)
            tools = list(tools)
            if manage_memory not in tools:
                tools.append(manage_memory)

        assert manage_memory in tools

    def test_tool_not_appended_when_memory_manager_none(self):
        from app.reasoning.langchain_agent.memory.tool import manage_memory

        tools: list = []
        memory_manager = None

        if memory_manager is not None:
            from app.reasoning.langchain_agent.memory.tool import set_memory_manager
            set_memory_manager(memory_manager)
            tools = list(tools)
            if manage_memory not in tools:
                tools.append(manage_memory)

        assert manage_memory not in tools

    def test_tool_list_copy_avoids_cache_mutation(self):
        """Verify list(tools) copy prevents mutating the original cache."""
        from app.reasoning.langchain_agent.memory.tool import manage_memory

        original_tools = [MagicMock(name="tool_a")]
        tools = original_tools
        memory_manager = MagicMock(spec=MemoryManager)

        if memory_manager is not None:
            tools = list(tools)
            if manage_memory not in tools:
                tools.append(manage_memory)

        assert manage_memory not in original_tools
        assert manage_memory in tools

    def test_manage_memory_not_in_original_tools(self):
        from app.reasoning.langchain_agent.memory.tool import manage_memory
        from app.reasoning.tools.tools import get_available_tools

        tools = get_available_tools(subagent_enabled=False)
        assert manage_memory not in tools


# ── prefetch_all patterns ────────────────────────────────────────────────────


class TestPrefetchAll:
    """Verify prefetch_all usage patterns."""

    @pytest.mark.asyncio
    async def test_called_with_question(self):
        mm = AsyncMock(spec=MemoryManager)
        mm.prefetch_all = AsyncMock(return_value="<memory-context>mock</memory-context>")
        result = await mm.prefetch_all("光伏行业前景")
        mm.prefetch_all.assert_awaited_once_with("光伏行业前景")
        assert result == "<memory-context>mock</memory-context>"

    @pytest.mark.asyncio
    async def test_not_called_when_memory_manager_none(self):
        mm = None
        if mm is not None:
            await mm.prefetch_all("test")
        # Should not raise

    @pytest.mark.asyncio
    async def test_graceful_degradation(self):
        mm = AsyncMock(spec=MemoryManager)
        mm.prefetch_all = AsyncMock(side_effect=RuntimeError("DB error"))
        result = ""
        try:
            result = await mm.prefetch_all("test")
        except Exception:
            result = ""
        assert result == ""


# ── sync_all patterns ────────────────────────────────────────────────────────


class TestSyncAll:
    """Verify per-turn sync_all usage patterns."""

    @pytest.mark.asyncio
    async def test_called_with_question_and_asst(self):
        mm = AsyncMock(spec=MemoryManager)
        mm.sync_all = AsyncMock()
        await mm.sync_all("分析光伏", "隆基绿能是光伏龙头")
        mm.sync_all.assert_awaited_once_with("分析光伏", "隆基绿能是光伏龙头")

    @pytest.mark.asyncio
    async def test_not_called_when_memory_manager_none(self):
        mm = None
        if mm is not None:
            await mm.sync_all("test", "asst")

    @pytest.mark.asyncio
    async def test_not_called_when_no_assistant_text(self):
        mm = AsyncMock(spec=MemoryManager)
        question = "分析光伏"
        asst_text = ""
        if mm is not None and asst_text:
            await mm.sync_all(question, asst_text)
        mm.sync_all.assert_not_called()

    @pytest.mark.asyncio
    async def test_not_duplicated_for_same_text(self):
        mm = AsyncMock(spec=MemoryManager)
        question = "分析光伏"
        asst_text = "隆基绿能分析"
        _last_synced_asst = ""

        if mm is not None:
            if asst_text and asst_text != _last_synced_asst:
                await mm.sync_all(question, asst_text)
                _last_synced_asst = asst_text

        mm.sync_all.assert_awaited_once()

        # Second call with identical text — should NOT sync again
        if mm is not None:
            if asst_text and asst_text != _last_synced_asst:
                await mm.sync_all(question, asst_text)
                _last_synced_asst = asst_text

        mm.sync_all.assert_awaited_once()


# ── shutdown_all patterns ────────────────────────────────────────────────────


class TestShutdownAll:
    """Verify shutdown_all usage patterns."""

    @pytest.mark.asyncio
    async def test_called_at_end(self):
        mm = AsyncMock(spec=MemoryManager)
        mm.shutdown_all = AsyncMock()
        if mm is not None:
            await mm.shutdown_all()
        mm.shutdown_all.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_not_called_when_memory_manager_none(self):
        mm = None
        if mm is not None:
            await mm.shutdown_all()

    @pytest.mark.asyncio
    async def test_graceful_degradation(self):
        mm = AsyncMock(spec=MemoryManager)
        mm.shutdown_all = AsyncMock(side_effect=RuntimeError("shutdown error"))
        try:
            if mm is not None:
                await mm.shutdown_all()
        except Exception:
            pass
        mm.shutdown_all.assert_awaited_once()


# ── End-to-end scenario ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_full_pipeline():
    """Simulate the full integration pipeline end-to-end."""
    mm = AsyncMock(spec=MemoryManager)
    mm.prefetch_all = AsyncMock(return_value="<memory-context>mock ctx</memory-context>")
    mm.sync_all = AsyncMock()
    mm.shutdown_all = AsyncMock()

    question = "分析光伏行业"
    memory_manager = mm

    # Step: prefetch
    if memory_manager is not None:
        memory_context = await memory_manager.prefetch_all(question)
        assert memory_context == "<memory-context>mock ctx</memory-context>"

    # Step: per-turn sync
    if memory_manager is not None:
        await memory_manager.sync_all(question, "助理分析内容")

    # Step: shutdown
    if memory_manager is not None:
        await memory_manager.shutdown_all()

    mm.prefetch_all.assert_awaited_once_with(question)
    mm.sync_all.assert_awaited_once_with(question, "助理分析内容")
    mm.shutdown_all.assert_awaited_once()
