"""
tests/reasoning/test_rest_api_reasoning.py

Bug M3 TDD: REST API 缺少 reasoning_end 内容

Bug 描述：
  /chat 和 /invoke 端点返回的结果中没有 thinking/reasoning 内容。
  只有 /stream/report 通过 SSE 发送 thinking 事件。

期望行为：
  REST API 返回结果应包含 reasoning/thinking 内容，供前端展示。

Run: uv run --directory backend python -m pytest tests/reasoning/test_rest_api_reasoning.py -v
"""
import pytest
from unittest.mock import patch, AsyncMock


class TestRestApiReasoningContent:
    """REST API reasoning 内容测试"""

    def test_chat_response_should_have_reasoning_field(self):
        """
        ChatResponse 应包含 reasoning 或 thinking 字段

        当前实现只返回 content，缺少 thinking/reasoning 字段
        """
        from app.reasoning.api.agent import ChatResponse

        # 检查 ChatResponse 是否有 reasoning 相关字段
        fields = ChatResponse.model_fields.keys()

        print(f"ChatResponse 字段: {list(fields)}")

        # 应该包含 thinking 或 reasoning 字段
        has_reasoning = "reasoning" in fields or "thinking" in fields

        assert has_reasoning, "ChatResponse 应包含 reasoning 或 thinking 字段"

    def test_result_response_should_have_reasoning_field(self):
        """
        ResultResponse 应包含 reasoning 或 thinking 字段

        当前实现只返回 content/report_json，缺少 thinking/reasoning 字段
        """
        from app.reasoning.api.agent import ResultResponse

        # 检查 ResultResponse 是否有 reasoning 相关字段
        fields = ResultResponse.model_fields.keys()

        print(f"ResultResponse 字段: {list(fields)}")

        # 应该包含 thinking 或 reasoning 字段
        has_reasoning = "reasoning" in fields or "thinking" in fields

        assert has_reasoning, "ResultResponse 应包含 reasoning 或 thinking 字段"

    def test_stream_endpoint_emits_thinking_events(self):
        """
        SSE 流式端点应发送 thinking 事件

        这个测试验证流式端点的正确性
        """
        from app.reasoning.api.agent import _run_stream_report
        import inspect

        source = inspect.getsource(_run_stream_report)

        # 验证事件映射
        assert "thinking" in source, "流式端点应发送 thinking 事件"
        assert "stream_end" in source, "流式端点应在结束时发送 stream_end"