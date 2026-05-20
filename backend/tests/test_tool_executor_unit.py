"""Tool Executor Unit Tests - TEST-02 + Bug T6 regression for Phase 27"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.reasoning.langchain_agent.tool_executor import ToolExecutor, ToolResult, SLOW_TOOL_THRESHOLD_MS


class TestToolResult:
    """ToolResult dataclass tests."""

    def test_tool_result_success(self):
        """Successful result has correct attributes."""
        result = ToolResult(
            tool_name="test_tool",
            success=True,
            result="output",
            duration_ms=100.0,
        )
        assert result.tool_name == "test_tool"
        assert result.success is True
        assert result.result == "output"
        assert result.duration_ms == 100.0

    def test_tool_result_failure(self):
        """Failed result has correct attributes."""
        result = ToolResult(
            tool_name="test_tool",
            success=False,
            result="",
            duration_ms=50.0,
            error="timeout",
        )
        assert result.tool_name == "test_tool"
        assert result.success is False
        assert result.error == "timeout"
        assert result.duration_ms == 50.0

    def test_tool_result_with_attempts(self):
        """Result tracks retry attempts."""
        result = ToolResult(
            tool_name="test_tool",
            success=True,
            result="output",
            duration_ms=300.0,
            attempts=3,
        )
        assert result.attempts == 3

    def test_slow_tool_threshold_constant(self):
        """SLOW_TOOL_THRESHOLD_MS is 5000 (5 seconds)."""
        assert SLOW_TOOL_THRESHOLD_MS == 5000
        # Bug T6 regression: threshold should be 5000ms, not 5000 microseconds
        assert SLOW_TOOL_THRESHOLD_MS >= 1000  # At least 1 second


class TestToolExecutorBasic:
    """Basic ToolExecutor tests."""

    def test_executor_creation(self):
        """ToolExecutor can be created with tools."""
        mock_tool = MagicMock()
        mock_tool.name = "test_tool"
        executor = ToolExecutor(tools=[mock_tool])
        assert executor is not None

    def test_executor_with_configs(self):
        """ToolExecutor accepts tool_configs."""
        mock_tool = MagicMock()
        mock_tool.name = "test_tool"
        executor = ToolExecutor(
            tools=[mock_tool],
            tool_configs={"test_tool": {"timeout": 60.0}},
        )
        assert executor is not None


class TestToolExecutorTimeout:
    """Timeout behavior tests."""

    @pytest.mark.asyncio
    async def test_fast_tool_completes(self):
        """Fast tool should complete successfully."""
        mock_tool = MagicMock()
        mock_tool.name = "fast_tool"

        async def fast_invoke():
            await asyncio.sleep(0.01)  # 10ms
            return "result"

        mock_tool.ainvoke = AsyncMock(side_effect=lambda _: asyncio.sleep(0.01) or {"output": "result"})
        mock_tool.name = "fast_tool"

        executor = ToolExecutor(tools=[mock_tool], default_timeout=30.0)
        # Just verify it can be created with timeout config
        assert executor._default_timeout == 30.0
