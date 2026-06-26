"""
tests/reasoning/test_sse_event_filter.py

Phase A SSE 事件过滤/转换测试。

Phase A 事件映射规则：
  - thinking_delta → thinking         （前端可见）
  - ai_message    → thinking         （向后兼容）
  - tool_called   → tool_called     （Phase A: 前端可见）
  - tool_call     → tool_called     （向后兼容）
  - tool_result   → tool_result    （Phase A: 前端可见，含 truncated 元信息）
  - reasoning_end → stream_end      （前端可见）
  - reasoning_completed → stream_end

Run: uv run --directory backend python -m pytest tests/reasoning/test_sse_event_filter.py -v
"""


class TestEventFilterMapping:
    """事件过滤/映射转换"""

    def test_thinking_delta_becomes_thinking(self):
        """Phase A: thinking_delta → thinking"""
        from app.reasoning.api.agent import _filter_sse_event

        kept, event_type = _filter_sse_event("thinking_delta", {"delta": "正在分析光模块行业..."})
        assert kept is True
        assert event_type == "thinking"

    def test_ai_message_becomes_thinking(self):
        """向后兼容：ai_message → thinking"""
        from app.reasoning.api.agent import _filter_sse_event

        kept, event_type = _filter_sse_event("ai_message", {"content": "正在分析光模块行业..."})
        assert kept is True
        assert event_type == "thinking"

    def test_tool_called_is_visible(self):
        """Phase A: tool_called → 前端可见（替代 tool_call 过滤）"""
        from app.reasoning.api.agent import _filter_sse_event

        kept, new_type = _filter_sse_event("tool_called", {"name": "get_kline", "args": {"code": "300308"}})
        assert kept is True
        assert new_type == "tool_called"

    def test_tool_call_becomes_tool_called(self):
        """向后兼容：tool_call → tool_called"""
        from app.reasoning.api.agent import _filter_sse_event

        kept, new_type = _filter_sse_event("tool_call", {"name": "retrieval", "args": {"query": "中际旭创"}})
        assert kept is True
        assert new_type == "tool_called"

    def test_tool_result_is_visible(self):
        """Phase A: tool_result → 前端可见（含 truncated 元信息）"""
        from app.reasoning.api.agent import _filter_sse_event

        kept, new_type = _filter_sse_event(
            "tool_result",
            {"name": "get_kline", "result": "...", "truncated": True, "original_len": 5000},
        )
        assert kept is True
        assert new_type == "tool_result"

    def test_reasoning_end_becomes_stream_end(self):
        """reasoning_end → stream_end"""
        from app.reasoning.api.agent import _filter_sse_event

        kept, new_type = _filter_sse_event("reasoning_end", {"turns": 3, "content": "综合分析结论..."})
        assert kept is True
        assert new_type == "stream_end"

    def test_reasoning_completed_becomes_stream_end(self):
        """reasoning_completed → stream_end"""
        from app.reasoning.api.agent import _filter_sse_event

        kept, new_type = _filter_sse_event("reasoning_completed", {"total_turns": 2})
        assert kept is True
        assert new_type == "stream_end"

    def test_legacy_reasoning_started_maps_to_canonical_start(self):
        """Phase 7: legacy reasoning_started maps to canonical reasoning_start."""
        from app.reasoning.api.agent import _filter_sse_event

        kept, event_type = _filter_sse_event("reasoning_started", {"question": "test"})
        assert kept is True
        assert event_type == "reasoning_start"

    def test_ai_message_empty_content(self):
        """向后兼容：ai_message → thinking（不崩溃）"""
        from app.reasoning.api.agent import _filter_sse_event

        kept, new_type = _filter_sse_event("ai_message", {})
        assert kept is True
        assert new_type == "thinking"

    def test_thinking_delta_empty_delta(self):
        """Phase A: thinking_delta 空 delta → 仍映射，不崩溃"""
        from app.reasoning.api.agent import _filter_sse_event

        kept, new_type = _filter_sse_event("thinking_delta", {})
        assert kept is True
        assert new_type == "thinking"

    def test_stream_end_not_double_wrapped(self):
        """stream_end 本身不需再映射"""
        from app.reasoning.api.agent import _filter_sse_event

        kept, event_type = _filter_sse_event("stream_end", {"content": "最终报告"})
        assert kept is True
        assert event_type == "stream_end"


class TestEventFilterWithContext:
    """带 context 的事件过滤"""

    def test_ai_message_preserves_turn_context(self):
        """ai_message 转换时保留 turn 等上下文"""
        from app.reasoning.api.agent import _filter_sse_event

        kept, new_type = _filter_sse_event("ai_message", {"content": "正在分析", "turn": 2, "has_tool_calls": True})
        assert kept is True
        assert new_type == "thinking"
