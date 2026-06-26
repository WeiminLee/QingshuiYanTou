"""Middleware Unit Tests - TEST-01 coverage for Phase 27"""

import pytest
from langchain.agents import AgentState
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.reasoning.config.loop_detection_config import LoopDetectionConfig, ToolFreqOverride
from app.reasoning.langchain_agent.middlewares.clarification import ClarificationMiddleware
from app.reasoning.langchain_agent.middlewares.loop_detection import (
    LoopDetectionMiddleware,
    _hash_tool_calls,
    _normalize_tool_call_args,
    _stable_tool_key,
)


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


class TestLoopDetectionConfig:
    """LoopDetectionConfig validation tests."""

    def test_default_config(self):
        """Default values should be valid."""
        config = LoopDetectionConfig()
        assert config.warn_threshold == 3
        assert config.hard_limit == 5
        assert config.window_size == 20

    def test_custom_config(self):
        """Custom values should be accepted."""
        config = LoopDetectionConfig(
            warn_threshold=5,
            hard_limit=10,
            window_size=50,
        )
        assert config.warn_threshold == 5
        assert config.hard_limit == 10

    def test_warn_threshold_cannot_exceed_hard_limit(self):
        """warn_threshold must be <= hard_limit."""
        with pytest.raises(ValueError, match="warn_threshold.*hard_limit"):
            LoopDetectionConfig(warn_threshold=10, hard_limit=5)

    def test_tool_freq_overrides(self):
        """Tool frequency overrides should work."""
        config = LoopDetectionConfig(
            tool_freq_overrides={
                "bash": ToolFreqOverride(warn=50, hard_limit=100),
            }
        )
        assert "bash" in config.tool_freq_overrides
        assert config.tool_freq_overrides["bash"].warn == 50
        assert config.tool_freq_overrides["bash"].hard_limit == 100


class TestNormalizeToolCallArgs:
    """_normalize_tool_call_args utility tests."""

    def test_dict_args(self):
        """Dict args should pass through unchanged."""
        args, fallback = _normalize_tool_call_args({"ts_code": "000001.SZ"})
        assert args == {"ts_code": "000001.SZ"}
        assert fallback is None

    def test_json_string_args(self):
        """JSON string args should be parsed."""
        args, fallback = _normalize_tool_call_args('{"ts_code": "000001.SZ"}')
        assert args == {"ts_code": "000001.SZ"}
        assert fallback is None

    def test_none_args(self):
        """None args should return empty dict."""
        args, fallback = _normalize_tool_call_args(None)
        assert args == {}
        assert fallback is None


class TestStableToolKey:
    """_stable_tool_key utility tests."""

    def test_read_file_path_bucket(self):
        """read_file should use path bucketing."""
        key1 = _stable_tool_key("read_file", {"path": "/a/b.py"}, None)
        key2 = _stable_tool_key(
            "read_file",
            {"path": "/a/b.py", "start_line": 1, "end_line": 50},
            None,
        )
        key3 = _stable_tool_key(
            "read_file",
            {"path": "/a/b.py", "start_line": 51, "end_line": 100},
            None,
        )
        # Both should fall in the same bucket (lines 1-200)
        assert key1 == key2 == key3

    def test_write_file_full_hash(self):
        """write_file should use full args hash."""
        key = _stable_tool_key(
            "write_file",
            {"path": "/a/b.py", "content": "print('hello')"},
            None,
        )
        assert key is not None

    def test_salient_fields(self):
        """Tools with salient fields should use those."""
        key = _stable_tool_key(
            "bash",
            {"command": "ls -la", "cwd": "/tmp"},
            None,
        )
        assert key is not None
        assert "command" in key


class TestHashToolCalls:
    """_hash_tool_calls utility tests."""

    def test_order_independent(self):
        """Hash should be the same regardless of tool call order."""
        calls_a = [
            {"name": "get_kline", "args": {"ts_code": "000001.SZ"}},
            {"name": "get_profile", "args": {"ts_code": "000001.SZ"}},
        ]
        calls_b = [
            {"name": "get_profile", "args": {"ts_code": "000001.SZ"}},
            {"name": "get_kline", "args": {"ts_code": "000001.SZ"}},
        ]
        assert _hash_tool_calls(calls_a) == _hash_tool_calls(calls_b)

    def test_different_calls_different_hash(self):
        """Different tool calls should produce different hashes."""
        calls_a = [{"name": "get_kline", "args": {"ts_code": "000001.SZ"}}]
        calls_b = [{"name": "get_kline", "args": {"ts_code": "000002.SZ"}}]
        assert _hash_tool_calls(calls_a) != _hash_tool_calls(calls_b)


class TestLoopDetectionMiddleware:
    """LoopDetectionMiddleware unit tests."""

    def _make_ai_msg_with_tools(self, tool_calls: list[dict]) -> AIMessage:
        """Helper to create AIMessage with properly formatted tool_calls."""
        from langchain_core.messages.function import FunctionMessage
        tc_list = []
        for i, tc in enumerate(tool_calls):
            tc_list.append({
                "name": tc.get("name", ""),
                "args": tc.get("args", {}),
                "id": f"call_{i}",
                "type": "tool_call",
            })
        return AIMessage(content="...", tool_calls=tc_list)

    def test_after_model_no_tool_calls(self):
        """Response without tool_calls should pass through."""
        middleware = LoopDetectionMiddleware()
        state: AgentState = {"messages": [AIMessage(content="分析完成")]}
        runtime = {}

        result = middleware.after_model(state, runtime)
        assert result is None

    def test_after_model_single_call_no_repeat(self):
        """Single tool call should not trigger detection."""
        middleware = LoopDetectionMiddleware(warn_threshold=3, hard_limit=5)
        msg = self._make_ai_msg_with_tools([
            {"name": "get_kline", "args": {"ts_code": "000001.SZ"}}
        ])
        state: AgentState = {"messages": [msg]}
        runtime = {"thread_id": "test-thread-1", "run_id": "run-1"}

        result = middleware.after_model(state, runtime)
        # No repeat yet, should pass through
        assert result is None

    def test_after_model_hard_limit_strips_tools(self):
        """At hard_limit, tool_calls should be stripped."""
        middleware = LoopDetectionMiddleware(warn_threshold=1, hard_limit=2)
        thread_id = "test-thread-hard-limit"

        # Build up repeats to hit hard limit
        for i in range(2):
            msg = self._make_ai_msg_with_tools([
                {"name": "get_kline", "args": {"ts_code": "000001.SZ"}}
            ])
            state: AgentState = {"messages": [msg]}
            runtime = {"thread_id": thread_id, "run_id": f"run-{i}"}
            result = middleware.after_model(state, runtime)

        # After hitting hard limit, result should strip tool_calls
        assert result is not None
        update = result
        assert update["messages"][0].tool_calls == []

    def test_from_config(self):
        """from_config should construct correctly."""
        config = LoopDetectionConfig(
            warn_threshold=5,
            hard_limit=8,
            tool_freq_warn=40,
            tool_freq_hard_limit=60,
            tool_freq_overrides={"bash": ToolFreqOverride(warn=50, hard_limit=100)},
        )
        middleware = LoopDetectionMiddleware.from_config(config)

        assert middleware.warn_threshold == 5
        assert middleware.hard_limit == 8
        assert middleware.tool_freq_warn == 40
        assert middleware.tool_freq_hard_limit == 60
        assert middleware._tool_freq_overrides == {"bash": (50, 100)}

    def test_reset_thread(self):
        """reset should clear thread state."""
        middleware = LoopDetectionMiddleware()
        thread_id = "test-reset-thread"

        # Add some state
        msg = self._make_ai_msg_with_tools([
            {"name": "get_kline", "args": {"ts_code": "000001.SZ"}}
        ])
        state: AgentState = {"messages": [msg]}
        runtime = {"thread_id": thread_id, "run_id": "run-1"}
        middleware.after_model(state, runtime)

        # Reset
        middleware.reset(thread_id=thread_id)

        # State should be cleared
        with middleware._lock:
            assert thread_id not in middleware._history

    def test_reset_all(self):
        """reset() without thread_id should clear all state."""
        middleware = LoopDetectionMiddleware()
        thread_id = "test-reset-all"

        msg = self._make_ai_msg_with_tools([
            {"name": "get_kline", "args": {"ts_code": "000001.SZ"}}
        ])
        state: AgentState = {"messages": [msg]}
        runtime = {"thread_id": thread_id, "run_id": "run-1"}
        middleware.after_model(state, runtime)

        # Reset all
        middleware.reset()

        # All state should be cleared
        with middleware._lock:
            assert len(middleware._history) == 0
            assert len(middleware._warned) == 0

    def test_tool_freq_detection(self):
        """Per-tool frequency should trigger warnings."""
        middleware = LoopDetectionMiddleware(
            tool_freq_warn=3,
            tool_freq_hard_limit=5,
        )
        thread_id = "test-freq-thread"

        # Call the same tool type multiple times
        for i in range(3):
            msg = self._make_ai_msg_with_tools([
                {"name": "read_file", "args": {"path": f"/file{i}.py"}}
            ])
            state: AgentState = {"messages": [msg]}
            runtime = {"thread_id": thread_id, "run_id": f"run-{i}"}
            middleware.after_model(state, runtime)

        # After 3 calls, should have queued a warning
        with middleware._lock:
            pending_key = (thread_id, "run-2")
            assert pending_key in middleware._pending_warnings
            assert len(middleware._pending_warnings[pending_key]) > 0

    def test_tool_freq_override(self):
        """Tool-specific overrides should take precedence."""
        middleware = LoopDetectionMiddleware(
            tool_freq_warn=10,
            tool_freq_hard_limit=15,
            tool_freq_overrides={"bash": (50, 100)},
        )

        assert middleware._tool_freq_overrides.get("bash") == (50, 100)
        # Non-overridden tools should use defaults
        name = "read_file"
        if name in middleware._tool_freq_overrides:
            eff_warn, eff_hard = middleware._tool_freq_overrides[name]
        else:
            eff_warn = middleware.tool_freq_warn
            eff_hard = middleware.tool_freq_hard_limit
        assert eff_warn == 10
        assert eff_hard == 15
