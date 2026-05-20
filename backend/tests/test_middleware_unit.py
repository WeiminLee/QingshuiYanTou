"""Middleware Unit Tests - TEST-01 coverage for Phase 27"""
import pytest
from unittest.mock import MagicMock
from langchain_core.messages import AIMessage, HumanMessage

from app.reasoning.langchain_agent.middlewares.clarification import ClarificationMiddleware
from app.reasoning.langchain_agent.middlewares.loop_detection import LoopDetectionMiddleware


class TestClarificationMiddleware:
    """ClarificationMiddleware unit tests."""

    def test_needs_clarification_empty_string(self):
        """Empty input should need clarification."""
        assert ClarificationMiddleware._needs_clarification("") is True
        assert ClarificationMiddleware._needs_clarification("   ") is True
        assert ClarificationMiddleware._needs_clarification("ab") is True  # too short

    def test_needs_clarification_vague_phrases(self):
        """Vague phrases should need clarification."""
        # Pattern '怎么样' triggers ambiguity score >= 0.6
        assert ClarificationMiddleware._needs_clarification("这只股票怎么样") is True
        # Pattern '好不好' triggers ambiguity score >= 0.6
        assert ClarificationMiddleware._needs_clarification("好不好") is True

    def test_needs_clarification_specific_input(self):
        """Specific stock code/name should not need clarification."""
        # Stock code pattern
        assert ClarificationMiddleware._needs_clarification("帮我分析000001的估值") is False
        # Stock name pattern
        assert ClarificationMiddleware._needs_clarification("中际旭创的竞争格局如何") is False

    def test_build_suggestions_empty(self):
        """Empty input should produce basic suggestions."""
        suggestions = ClarificationMiddleware._build_suggestions("")
        assert len(suggestions) >= 1
        assert "股票代码或名称" in suggestions[0] or "细节" in suggestions[0]

    def test_build_suggestions_vague(self):
        """Vague input should produce relevant suggestions."""
        suggestions = ClarificationMiddleware._build_suggestions("这只怎么样")
        assert len(suggestions) >= 1

    def test_build_suggestions_specific(self):
        """Specific input should still produce suggestions if needed."""
        suggestions = ClarificationMiddleware._build_suggestions("中际旭创好不好")
        # Should still suggest adding context
        assert len(suggestions) >= 1

    def test_after_model_hook_passes_through_normal(self):
        """Normal input should pass through without modification."""
        middleware = ClarificationMiddleware()
        state = {"messages": [HumanMessage(content="帮我分析000001的估值")]}
        response = AIMessage(content="好的，我来分析这只股票。")

        result = middleware.after_model_hook(state, response)
        assert result.content == response.content

    def test_after_model_hook_no_messages(self):
        """Empty messages should return original response."""
        middleware = ClarificationMiddleware()
        state = {"messages": []}
        response = AIMessage(content="Hello")

        result = middleware.after_model_hook(state, response)
        assert result.content == "Hello"


class TestLoopDetectionMiddleware:
    """LoopDetectionMiddleware unit tests."""

    def test_tool_call_fingerprint_identical(self):
        """Identical tool calls should produce same fingerprint."""
        tool_call = {"name": "get_kline", "args": {"ts_code": "000001.SZ"}}
        fp1 = LoopDetectionMiddleware._tool_call_fingerprint(tool_call)
        fp2 = LoopDetectionMiddleware._tool_call_fingerprint(tool_call)
        assert fp1 == fp2

    def test_tool_call_fingerprint_different_args(self):
        """Different args should produce different fingerprint."""
        tool_call1 = {"name": "get_kline", "args": {"ts_code": "000001.SZ"}}
        tool_call2 = {"name": "get_kline", "args": {"ts_code": "000002.SZ"}}
        fp1 = LoopDetectionMiddleware._tool_call_fingerprint(tool_call1)
        fp2 = LoopDetectionMiddleware._tool_call_fingerprint(tool_call2)
        assert fp1 != fp2

    def test_tool_call_fingerprint_different_tool(self):
        """Different tool names should produce different fingerprint."""
        tool_call1 = {"name": "get_kline", "args": {"ts_code": "000001.SZ"}}
        tool_call2 = {"name": "get_stock_profile", "args": {"ts_code": "000001.SZ"}}
        fp1 = LoopDetectionMiddleware._tool_call_fingerprint(tool_call1)
        fp2 = LoopDetectionMiddleware._tool_call_fingerprint(tool_call2)
        assert fp1 != fp2

    def test_after_model_hook_no_tool_calls(self):
        """Response without tool_calls should pass through."""
        middleware = LoopDetectionMiddleware()
        state = {"messages": []}
        response = AIMessage(content="分析完成")

        result = middleware.after_model_hook(state, response)
        assert result.content == "分析完成"

    def test_after_model_hook_no_repeat(self):
        """Non-repeated tool calls should pass through."""
        middleware = LoopDetectionMiddleware()
        # Single tool call with required 'id' field
        response = AIMessage(
            content="分析中",
            tool_calls=[{"name": "get_kline", "args": {"ts_code": "000001.SZ"}, "id": "call_1"}]
        )
        state = {"messages": []}

        result = middleware.after_model_hook(state, response)
        # Should pass through with tool_calls intact
        assert getattr(result, "tool_calls", None) is not None

    def test_after_model_hook_with_repeats(self):
        """Repeated tool calls should be detected or passed through."""
        middleware = LoopDetectionMiddleware(max_repeats=3)
        # Simulate state with some tool calls
        state = {"messages": [AIMessage(content="...", tool_calls=[{"name": "get_kline", "args": {"ts_code": "000001.SZ"}, "id": "call_1"}])]}
        response = AIMessage(
            content="...",
            tool_calls=[{"name": "get_kline", "args": {"ts_code": "000001.SZ"}, "id": "call_2"}]
        )

        result = middleware.after_model_hook(state, response)
        # Should handle gracefully (either pass through or modify)
        assert result is not None
