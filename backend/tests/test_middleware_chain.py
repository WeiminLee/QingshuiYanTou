"""Tests for new middlewares: TokenUsageMiddleware and DanglingToolCallMiddleware."""
from __future__ import annotations

import time

import pytest
from langchain_core.messages import AIMessage


class TestTokenUsageMiddleware:
    """TokenUsageMiddleware 测试"""

    def test_extract_usage_from_response_metadata(self):
        """测试从 AIMessage 提取 usage"""
        from app.reasoning.langchain_agent.middlewares.token_usage import TokenUsageMiddleware

        mw = TokenUsageMiddleware()

        # 模拟带 usage 的 AIMessage
        response = AIMessage(
            content="Test response",
        )
        # 设置 response_metadata
        response.response_metadata = {
            "usage": {
                "prompt_tokens": 1000,
                "completion_tokens": 500,
                "total_tokens": 1500,
            },
            "model": "claude2.5",
        }

        state = {"messages": [], "configurable": {"thread_id": "test-thread"}}

        # 执行 after_model_hook
        result = mw.after_model_hook(state, response)

        # 验证结果
        assert result is response  # 不修改 response

        stats = mw.get_session_stats("test-thread")
        assert stats is not None
        assert stats["total_tokens"] == 1500
        assert stats["total_prompt_tokens"] == 1000
        assert stats["total_completion_tokens"] == 500
        assert stats["call_count"] == 1

    def test_token_alert_threshold(self):
        """测试 token 超阈值告警"""
        from app.reasoning.langchain_agent.middlewares.token_usage import TokenUsageMiddleware

        # 设置较低的告警阈值以便测试
        mw = TokenUsageMiddleware(alert_threshold=1000)

        response = AIMessage(content="Large response")
        response.response_metadata = {
            "usage": {
                "prompt_tokens": 500,
                "completion_tokens": 800,
                "total_tokens": 1300,  # 超过 1000 阈值
            },
        }

        state = {"messages": [], "configurable": {"thread_id": "alert-test"}}

        # 应该不抛异常，只是记录 WARNING
        result = mw.after_model_hook(state, response)
        assert result is response

    def test_session_stats_tracking(self):
        """测试多轮调用统计"""
        from app.reasoning.langchain_agent.middlewares.token_usage import TokenUsageMiddleware

        mw = TokenUsageMiddleware()

        for i in range(5):
            response = AIMessage(content=f"Response {i}")
            response.response_metadata = {
                "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
            }
            state = {"messages": [], "configurable": {"thread_id": "multi-call"}}
            mw.after_model_hook(state, response)

        stats = mw.get_session_stats("multi-call")
        assert stats["call_count"] == 5
        assert stats["total_tokens"] == 750
        assert stats["avg_tokens_per_call"] == 150.0

    def test_reset_session(self):
        """测试重置会话统计"""
        from app.reasoning.langchain_agent.middlewares.token_usage import TokenUsageMiddleware

        mw = TokenUsageMiddleware()

        # 添加一些数据
        response = AIMessage(content="test")
        response.response_metadata = {
            "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
        }
        state = {"messages": [], "configurable": {"thread_id": "reset-test"}}
        mw.after_model_hook(state, response)

        # 验证有数据
        assert mw.get_session_stats("reset-test") is not None

        # 重置
        mw.reset_session("reset-test")

        # 验证已清除
        assert mw.get_session_stats("reset-test") is None

    def test_cost_estimate(self):
        """测试成本估算"""
        from app.reasoning.langchain_agent.middlewares.token_usage import TokenUsageMiddleware

        mw = TokenUsageMiddleware()

        # 添加测试数据: 1M prompt tokens, 500k completion tokens
        response = AIMessage(content="test")
        response.response_metadata = {
            "usage": {
                "prompt_tokens": 1_000_000,
                "completion_tokens": 500_000,
                "total_tokens": 1_500_000,
            },
        }
        state = {"messages": [], "configurable": {"thread_id": "cost-test"}}
        mw.after_model_hook(state, response)

        costs = mw.get_total_cost_estimate(prompt_price_per_1m=0.5, completion_price_per_1m=1.5)

        # prompt: 1M * 0.5 = 0.5
        # completion: 0.5M * 1.5 = 0.75
        # total = 1.25
        assert costs["total_cost"] == 1.25
        assert costs["prompt_cost"] == 0.5
        assert costs["completion_cost"] == 0.75


class TestDanglingToolCallMiddleware:
    """DanglingToolCallMiddleware 测试"""

    def test_no_fix_when_no_tool_calls(self):
        """测试没有 tool_calls 时不修复"""
        from app.reasoning.langchain_agent.middlewares.dangling_tool_call import (
            DanglingToolCallMiddleware,
        )

        mw = DanglingToolCallMiddleware()

        state = {
            "messages": [AIMessage(content="Hello")],
            "configurable": {"thread_id": "test"},
        }

        result = mw.before_model_hook(state)
        assert result is None  # 不需要修复

    def test_no_fix_when_tool_message_exists(self):
        """测试已有 ToolMessage 时不修复"""
        from langchain_core.messages import HumanMessage, ToolMessage

        from app.reasoning.langchain_agent.middlewares.dangling_tool_call import (
            DanglingToolCallMiddleware,
        )

        mw = DanglingToolCallMiddleware()

        # AIMessage 有 tool_calls，但后续有 ToolMessage
        state = {
            "messages": [
                HumanMessage(content="test"),
                AIMessage(
                    content="",
                    tool_calls=[{"id": "abc123", "name": "test_tool", "args": {}}],
                ),
                ToolMessage(content="result", tool_call_id="abc123", name="test_tool"),
            ],
            "configurable": {"thread_id": "test"},
        }

        result = mw.before_model_hook(state)
        assert result is None

    def test_fix_dangling_tool_call(self):
        """测试修复断开的 tool_call"""
        from langchain_core.messages import HumanMessage

        from app.reasoning.langchain_agent.middlewares.dangling_tool_call import (
            DanglingToolCallMiddleware,
        )

        mw = DanglingToolCallMiddleware()

        # AIMessage 有 tool_calls，但没有 ToolMessage
        state = {
            "messages": [
                HumanMessage(content="test"),
                AIMessage(content="", tool_calls=[{"id": "abc123", "name": "test_tool", "args": {}}]),
            ],
            "configurable": {"thread_id": "test"},
        }

        result = mw.before_model_hook(state)

        # 应该返回修复后的消息
        assert result is not None
        assert "messages" in result
        assert len(result["messages"]) == 3  # 原始 + 修复的 ToolMessage

        # 验证修复的 ToolMessage
        fixed_msg = result["messages"][-1]
        assert fixed_msg.tool_call_id == "abc123"
        assert fixed_msg.name == "test_tool"
        assert "执行中断" in fixed_msg.content

    def test_fix_multiple_dangling_tool_calls(self):
        """测试修复多个断开的 tool_calls"""
        from langchain_core.messages import HumanMessage

        from app.reasoning.langchain_agent.middlewares.dangling_tool_call import (
            DanglingToolCallMiddleware,
        )

        mw = DanglingToolCallMiddleware()

        state = {
            "messages": [
                HumanMessage(content="test"),
                AIMessage(
                    content="",
                    tool_calls=[
                        {"id": "tc1", "name": "tool_a", "args": {}},
                        {"id": "tc2", "name": "tool_b", "args": {}},
                    ],
                ),
            ],
            "configurable": {"thread_id": "test"},
        }

        result = mw.before_model_hook(state)

        assert result is not None
        # 应该有 2 个修复的 ToolMessage
        assert len(result["messages"]) == 4


class TestMiddlewareChain:
    """中间件链集成测试"""

    def test_build_middlewares_returns_correct_count(self):
        """测试 _build_middlewares 返回正确数量的中间件"""
        from langchain_core.runnables import RunnableConfig

        from app.reasoning.langchain_agent.lead_agent import _build_middlewares

        config = RunnableConfig()
        middlewares = _build_middlewares(config, thread_id="test", plan_mode=False)

        # 当前应该有 5 个中间件
        assert len(middlewares) == 5

        names = [mw.name for mw in middlewares]
        expected = [
            "context_compressor",
            "dangling_tool_call",
            "loop_detection",
            "reasoning_validation",
            "token_usage",
        ]
        assert names == expected

    def test_middleware_instances_are_different(self):
        """测试每次调用 _build_middlewares 创建新实例"""
        from langchain_core.runnables import RunnableConfig

        from app.reasoning.langchain_agent.lead_agent import _build_middlewares

        config = RunnableConfig()

        mw1 = _build_middlewares(config, thread_id="test1", plan_mode=False)
        mw2 = _build_middlewares(config, thread_id="test2", plan_mode=False)

        # 应该不是同一个对象
        for a, b in zip(mw1, mw2):
            assert a is not b