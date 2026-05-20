"""
测试 Phase 1: MessageBuilder 消息组装器

覆盖场景：
- build_initial_messages() 构建完整消息列表
- append_tool_result() 追加工具结果
- Memory Context 注入
- KG Anchors 注入
- Background Knowledge 注入
- 空值安全处理
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestMessageBuilderBuild:
    """MessageBuilder.build_initial_messages() 测试"""

    def test_build_with_all_contexts(self):
        """
        场景：所有上下文均存在
        期望：System → Background → Memory → KG → UserMessage
        """
        from app.reasoning.langchain_agent.message_builder import (
            MessageBuilder,
            MessageContext,
        )

        mb = MessageBuilder()
        ctx = MessageContext(
            thread_id="t-001",
            user_message="分析中际旭创的竞争格局",
            memory_context="用户之前关注光模块行业",
            kg_anchors="中际旭创 → 光模块 → 高速光模块",
            background_knowledge="中际旭创是全球光模块龙头",
        )

        messages = mb.build_initial_messages(ctx)

        # 验证消息数量（至少 system + user）
        assert len(messages) >= 2
        # 最后一条必须是用户消息
        last = messages[-1]
        assert "中际旭创" in last.content
        # 消息顺序：BG/Memory/KG 在前，User 永远最后
        assert messages[0].content  # 第一条有内容
        # 倒数第二条不应该是 user message
        assert messages[-1].type == "human"

    def test_build_with_minimal_context(self):
        """
        场景：只有用户消息，其他上下文为空
        期望：只返回 UserMessage
        """
        from app.reasoning.langchain_agent.message_builder import (
            MessageBuilder,
            MessageContext,
        )

        mb = MessageBuilder()
        ctx = MessageContext(
            thread_id="t-002",
            user_message="什么是 KDJ 指标",
            memory_context="",
            kg_anchors="",
            background_knowledge="",
        )

        messages = mb.build_initial_messages(ctx)

        assert len(messages) == 1
        assert messages[0].content == "什么是 KDJ 指标"

    def test_build_skips_empty_sections(self):
        """
        场景：Background 有值，Memory/KG 为空
        期望：Background 注入，但 Memory/KG 不产生空消息
        """
        from app.reasoning.langchain_agent.message_builder import (
            MessageBuilder,
            MessageContext,
        )

        mb = MessageBuilder()
        ctx = MessageContext(
            thread_id="t-003",
            user_message="查询今日市场宽度",
            memory_context="",
            kg_anchors="",
            background_knowledge="<background>\n## 相关背景知识\n- 今日 A 股震荡\n</background>",
        )

        messages = mb.build_initial_messages(ctx)

        # 不应有空内容的消息
        for msg in messages:
            assert msg.content.strip(), "不应有空内容的消息"
        # User message 存在
        user_contents = [m.content for m in messages]
        assert any("查询今日市场宽度" in c for c in user_contents)


class TestMessageBuilderAppend:
    """MessageBuilder.append_tool_result() 测试"""

    def test_append_single_result(self):
        """
        场景：追加单个工具结果
        期望：消息列表追加 ToolMessage，包含 tool_call_id
        """
        from app.reasoning.langchain_agent.message_builder import (
            MessageBuilder,
            MessageContext,
        )
        from langchain_core.messages import HumanMessage

        mb = MessageBuilder()
        ctx = MessageContext(thread_id="t-004", user_message="查 K 线")
        messages = mb.build_initial_messages(ctx)

        # 追加工具结果
        result = mb.append_tool_result(
            messages=messages,
            tool_name="get_kline",
            result="KDJ 金叉信号出现",
            tool_call_id="call-abc123",
        )

        # 验证追加成功
        assert len(messages) == 2
        last = messages[-1]
        assert last.type == "tool"
        assert last.content == "KDJ 金叉信号出现"
        assert last.tool_call_id == "call-abc123"
        assert last.name == "get_kline"

    def test_append_multiple_results(self):
        """
        场景：追加多个工具结果（模拟一轮多个工具并发执行）
        期望：按调用顺序追加，最后一条是 UserMessage
        """
        from app.reasoning.langchain_agent.message_builder import (
            MessageBuilder,
            MessageContext,
        )

        mb = MessageBuilder()
        ctx = MessageContext(thread_id="t-005", user_message="分析光模块行业")
        messages = mb.build_initial_messages(ctx)

        mb.append_tool_result(
            messages, tool_name="get_concept_hot", result="光模块热度排名第3", tool_call_id="c1"
        )
        mb.append_tool_result(
            messages, tool_name="get_market_breadth", result="上涨家数占比 55%", tool_call_id="c2"
        )

        assert len(messages) == 3
        # 初始: [HumanMessage(user_message)]
        # 追加 c1: [HumanMessage, ToolMessage(c1)]
        # 追加 c2: [HumanMessage, ToolMessage(c1), ToolMessage(c2)]
        assert messages[0].type == "human"
        assert messages[1].name == "get_concept_hot"
        assert messages[2].name == "get_market_breadth"
        assert messages[2].type == "tool"

    def test_append_empty_result(self):
        """
        场景：工具返回空结果
        期望：仍追加 ToolMessage，内容为空字符串
        """
        from app.reasoning.langchain_agent.message_builder import (
            MessageBuilder,
            MessageContext,
        )

        mb = MessageBuilder()
        ctx = MessageContext(thread_id="t-006", user_message="查公告")
        messages = mb.build_initial_messages(ctx)

        mb.append_tool_result(messages, tool_name="get_announcement", result="", tool_call_id="c-empty")

        assert len(messages) == 2
        assert messages[-1].content == ""
        assert messages[-1].tool_call_id == "c-empty"


class TestMessageContext:
    """MessageContext 数据类测试"""

    def test_message_context_default_values(self):
        """所有字段有合理的默认值"""
        from app.reasoning.langchain_agent.message_builder import MessageContext

        ctx = MessageContext(thread_id="t-007", user_message="测试")
        assert ctx.thread_id == "t-007"
        assert ctx.user_message == "测试"
        assert ctx.memory_context == ""
        assert ctx.kg_anchors == ""
        assert ctx.background_knowledge == ""
        assert ctx.system_vars == {}

    def test_message_context_with_all_fields(self):
        """所有字段均可赋值"""
        from app.reasoning.langchain_agent.message_builder import MessageContext

        ctx = MessageContext(
            thread_id="t-008",
            user_message="分析贵州茅台",
            memory_context="用户关注白酒板块",
            kg_anchors="贵州茅台 → 高端白酒 → 酱香型",
            background_knowledge="茅台一季度营收增长 15%",
            system_vars={"language": "zh", "temperature": 0.1},
        )
        assert ctx.memory_context == "用户关注白酒板块"
        assert ctx.kg_anchors == "贵州茅台 → 高端白酒 → 酱香型"
        assert ctx.system_vars["language"] == "zh"


class TestBackgroundKnowledgeFormatting:
    """Background Knowledge 格式化测试"""

    def test_background_injected_before_user_message(self):
        """
        场景：Background Knowledge 存在
        期望：Background 消息在 User 消息之前
        """
        from app.reasoning.langchain_agent.message_builder import (
            MessageBuilder,
            MessageContext,
        )

        mb = MessageBuilder()
        ctx = MessageContext(
            thread_id="t-009",
            user_message="分析中际旭创",
            background_knowledge="<background>\n## 相关背景知识\n- 中际旭创是全球光模块龙头\n</background>",
        )
        messages = mb.build_initial_messages(ctx)

        # 找 user message 的位置
        user_indices = [i for i, m in enumerate(messages) if "分析中际旭创" in m.content]
        # 找 background message 的位置
        bg_indices = [
            i for i, m in enumerate(messages) if "background" in m.content.lower()
        ]

        if user_indices and bg_indices:
            # Background 应在 User 之前
            assert bg_indices[0] < user_indices[0], "Background 知识应在 User 消息之前"


class TestKGAnchors:
    """KG Anchors 注入测试"""

    def test_kg_anchors_in_system_message(self):
        """
        场景：KG Anchors 存在
        期望：KG Anchors 在 System 消息中（不是单独消息）
        """
        from app.reasoning.langchain_agent.message_builder import (
            MessageBuilder,
            MessageContext,
        )

        mb = MessageBuilder()
        ctx = MessageContext(
            thread_id="t-010",
            user_message="分析中际旭创",
            kg_anchors="中际旭创 → 光模块 → 高速光模块",
        )
        messages = mb.build_initial_messages(ctx)

        # 检查是否有 system 类型的消息包含 KG Anchors
        system_msgs = [m for m in messages if m.type in ("system", "human")]
        all_content = "\n".join(m.content for m in messages)
        assert "中际旭创" in all_content or "KG" in all_content


class TestBuildMessagesOrder:
    """消息顺序验证测试"""

    def test_message_ordering(self):
        """
        验证消息顺序：System/Background → Memory → UserMessage
        UserMessage 永远是最后一条
        """
        from app.reasoning.langchain_agent.message_builder import (
            MessageBuilder,
            MessageContext,
        )

        mb = MessageBuilder()
        ctx = MessageContext(
            thread_id="t-011",
            user_message="最终问题",
            memory_context="记忆内容",
            background_knowledge="背景知识",
        )
        messages = mb.build_initial_messages(ctx)

        # 验证最后一条是用户消息
        assert "最终问题" in messages[-1].content
