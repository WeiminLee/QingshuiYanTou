"""
Phase 2 — ContextCompressorMiddleware 单元测试

测试覆盖：
- before_model / abefore_model 触发条件
- 头部和尾部保护
- 工具结果修剪
- _summarize_section 截断回退
- _asummarize_section LLM 总结（mock）
- SummaryMessage 类型
- disabled 时跳过
"""

from unittest.mock import AsyncMock

from langchain.agents.middleware import Runtime
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.reasoning.harness.token_counter import count_messages_tokens
from app.reasoning.langchain_agent.middlewares.context_compressor import (
    ContextCompressorMiddleware,
    SummaryMessage,
)


# ── 辅助函数 ─────────────────────────────────────────────────────────


def _make_text_messages(count: int, text: str = "msg {i}") -> list:
    msgs = []
    for i in range(count):
        content = text.format(i=i)
        if i % 2 == 0:
            msgs.append(HumanMessage(content=content))
        else:
            msgs.append(AIMessage(content=content))
    return msgs


# ── 测试类 ───────────────────────────────────────────────────────────


class TestSummaryMessage:
    def test_type_is_summary(self):
        sm = SummaryMessage(content="test")
        assert sm.type == "summary"

    def test_content_string_property(self):
        assert SummaryMessage(content="hello").content_string == "hello"

    def test_content_string_empty(self):
        assert SummaryMessage(content="").content_string == ""


class TestBeforeModel:
    """before_model 同步钩子"""

    def test_below_threshold_returns_none(self):
        mw = ContextCompressorMiddleware(token_threshold=999999)
        result = mw.before_model({"messages": _make_text_messages(5)}, Runtime())
        assert result is None

    def test_above_threshold_returns_compressed(self):
        mw = ContextCompressorMiddleware(token_threshold=10)
        messages = _make_text_messages(50, text="hello world {i}")
        result = mw.before_model({"messages": messages}, Runtime())
        assert result is not None
        assert "messages" in result
        assert len(result["messages"]) < len(messages)

    def test_no_messages_returns_none(self):
        mw = ContextCompressorMiddleware(token_threshold=10)
        result = mw.before_model({"messages": []}, Runtime())
        assert result is None

    def test_disabled_returns_none(self):
        mw = ContextCompressorMiddleware(token_threshold=10)
        mw._enabled = False
        result = mw.before_model({"messages": _make_text_messages(100)}, Runtime())
        assert result is None

    def test_head_messages_preserved(self):
        mw = ContextCompressorMiddleware(token_threshold=10, protect_first_n=3)
        messages = _make_text_messages(50, text="message {i}")
        result = mw.before_model({"messages": messages}, Runtime())
        compressed = result["messages"]
        for i, orig in enumerate(messages[:3]):
            assert compressed[i].content == orig.content

    def test_tail_messages_preserved(self):
        mw = ContextCompressorMiddleware(token_threshold=10, protect_first_n=3)
        messages = _make_text_messages(50, text="message {i}")
        result = mw.before_model({"messages": messages}, Runtime())
        compressed = result["messages"]
        tail_count = 3
        for i, orig in enumerate(messages[-tail_count:]):
            assert compressed[-(tail_count - i)].content == orig.content

    def test_protect_first_n_larger_than_list(self):
        mw = ContextCompressorMiddleware(token_threshold=10, protect_first_n=100)
        result = mw.before_model({"messages": _make_text_messages(5)}, Runtime())
        assert result is None


class TestAbeforeModel:
    """abefore_model 异步钩子（带 LLM）"""

    async def test_with_llm_summarizes(self):
        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value.content = "## 摘要\n已完成分析。"
        mw = ContextCompressorMiddleware(
            token_threshold=10, protect_first_n=1, llm=mock_llm
        )
        messages = _make_text_messages(30, text="hello world {i}")
        result = await mw.abefore_model({"messages": messages}, Runtime())
        assert result is not None
        compressed = result["messages"]
        assert len(compressed) < len(messages)
        # 应包含 SummaryMessage
        assert any(isinstance(m, SummaryMessage) for m in compressed)

    async def test_without_llm_falls_back(self):
        mw = ContextCompressorMiddleware(token_threshold=10, protect_first_n=1)
        messages = _make_text_messages(30, text="hello world {i}")
        result = await mw.abefore_model({"messages": messages}, Runtime())
        assert result is not None
        # 无 LLM 时应通过截断回退
        assert "messages" in result

    async def test_llm_failure_graceful(self):
        mock_llm = AsyncMock()
        mock_llm.ainvoke.side_effect = Exception("LLM unavailable")
        mw = ContextCompressorMiddleware(
            token_threshold=10, protect_first_n=1, llm=mock_llm
        )
        messages = _make_text_messages(30, text="hello world {i}")
        result = await mw.abefore_model({"messages": messages}, Runtime())
        # LLM 失败应回退截断，不抛异常
        assert result is not None
        assert "messages" in result


class TestToolPruning:
    def test_long_tool_content_shortened(self):
        mw = ContextCompressorMiddleware(token_threshold=50, protect_first_n=1)
        messages = [
            HumanMessage(content="query"),
            ToolMessage(content="x" * 500, tool_call_id="1", name="search_1"),
            HumanMessage(content="continue"),
            ToolMessage(content="y" * 500, tool_call_id="2", name="search_2"),
            AIMessage(content="done"),
        ]
        result = mw._prune_tool_results(messages)
        pruned = [
            m for m in result
            if isinstance(m, ToolMessage) and "pruned" in m.content
        ]
        assert len(pruned) > 0

    def test_short_tool_content_unchanged(self):
        mw = ContextCompressorMiddleware(token_threshold=50)
        msg = ToolMessage(content="short", tool_call_id="1", name="search")
        result = mw._prune_tool_results([msg])
        assert result[0].content == "short"


class TestSummarizeSection:
    def test_within_budget_unchanged(self):
        mw = ContextCompressorMiddleware(token_threshold=999999)
        msgs = _make_text_messages(3, text="short")
        # _summarize_section 会计算内部 budget，用极大阈值确保不触发
        result = mw._summarize_section(msgs)
        assert len(result) == 3

    def test_returns_summary_when_truncated(self):
        mw = ContextCompressorMiddleware(token_threshold=1)
        msgs = _make_text_messages(20, text="long message content {i} " * 10)
        result = mw._summarize_section(msgs)
        # 第一条应为 SummaryMessage
        assert isinstance(result[0], SummaryMessage)
        assert len(result) < len(msgs)


class TestAsummarizeSection:
    async def test_calls_llm_and_returns_summary(self):
        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value.content = "## Summary\nDone."
        mw = ContextCompressorMiddleware(
            token_threshold=10, llm=mock_llm
        )
        msgs = _make_text_messages(10, text="test message {i}")
        result = await mw._asummarize_section(msgs)
        assert len(result) == 1
        assert isinstance(result[0], SummaryMessage)
        mock_llm.ainvoke.assert_awaited_once()

    async def test_existing_summary_incremental(self):
        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value.content = "## Updated Summary\nDone."
        mw = ContextCompressorMiddleware(
            token_threshold=10, llm=mock_llm
        )
        # 已有 SummaryMessage + 新消息
        msgs = [
            SummaryMessage(content="old summary"),
            HumanMessage(content="new message"),
            AIMessage(content="new response"),
        ]
        result = await mw._asummarize_section(msgs)
        assert len(result) == 1
        assert isinstance(result[0], SummaryMessage)
        # LLM 应收到已有摘要和新消息
        call_args = mock_llm.ainvoke.await_args
        assert call_args is not None
        # call_args[0] = positional args tuple, call_args[0][0] = messages list
        prompt_text = call_args[0][0][0].content
        assert "old summary" in prompt_text


class TestStructureAware:
    """结构感知：保护结构标记消息"""

    def test_has_structural_marker_detects_memory(self):
        mw = ContextCompressorMiddleware()
        assert mw._has_structural_marker("[历史记忆] 用户关注光模块行业") is True

    def test_has_structural_marker_detects_kg_anchors(self):
        mw = ContextCompressorMiddleware()
        assert mw._has_structural_marker("<kg_anchors>\n中际旭创\n</kg_anchors>") is True

    def test_has_structural_marker_returns_false_for_normal(self):
        mw = ContextCompressorMiddleware()
        assert mw._has_structural_marker("分析光模块行业竞争格局") is False

    def test_structural_messages_not_pruned(self):
        mw = ContextCompressorMiddleware(token_threshold=50, protect_first_n=1)
        messages = [
            HumanMessage(content="query"),
            ToolMessage(content="[K线数据] 中际旭创收盘价 45.6", tool_call_id="1", name="get_kline"),
            ToolMessage(content="x" * 200, tool_call_id="2", name="search"),
            AIMessage(content="done"),
        ]
        result = mw._prune_tool_results(messages)
        # 带有 [K线数据] 标记的不应被修剪
        for msg in result:
            if isinstance(msg, ToolMessage) and "[K线数据]" in msg.content:
                assert "pruned" not in msg.content
                break
        else:
            pytest.fail("should contain [K线数据] ToolMessage")

    def test_structural_context_extracted(self):
        mw = ContextCompressorMiddleware()
        msgs = [
            HumanMessage(content="hello"),
            HumanMessage(content="[历史记忆] 用户关注 AI 芯片"),
            AIMessage(content="ok"),
        ]
        ctx = mw._extract_structural_context(msgs)
        assert "历史记忆" in ctx
        assert "AI 芯片" in ctx
        assert "hello" not in ctx  # 无标记的消息不提取

    def test_structural_context_empty_when_no_markers(self):
        mw = ContextCompressorMiddleware()
        msgs = [HumanMessage(content="hello"), AIMessage(content="world")]
        ctx = mw._extract_structural_context(msgs)
        assert ctx == ""

    async def test_structural_context_passed_to_llm(self):
        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value.content = "summary"
        mw = ContextCompressorMiddleware(token_threshold=10, llm=mock_llm)
        msgs = [
            HumanMessage(content="[历史记忆] 用户关注光模块"),
            AIMessage(content="分析中"),
        ]
        await mw._asummarize_section(msgs)
        call_args = mock_llm.ainvoke.await_args
        assert call_args is not None
        prompt_text = call_args[0][0][0].content
        assert "历史记忆" in prompt_text
        assert "用户关注光模块" in prompt_text

    def test_truncation_preserves_structural_messages(self):
        mw = ContextCompressorMiddleware(token_threshold=1)
        # 构造大量普通消息 + 结构消息
        msgs = _make_text_messages(15, text="msg {i}")
        msgs.append(HumanMessage(content="[历史记忆] 重要上下文"))
        result = mw._summarize_section(msgs)
        # 结构消息应出现在结果中
        found = any(
            "[历史记忆]" in (getattr(m, "content", "") or "")
            for m in result
        )
        assert found, "truncation should preserve structural messages"


class TestEdgeCases:
    def test_custom_model_name(self):
        mw = ContextCompressorMiddleware(token_threshold=10, model_name="gpt-4o")
        messages = _make_text_messages(50, text="hello world {i}")
        result = mw.before_model({"messages": messages}, Runtime())
        assert result is not None

    def test_tenant_id_passed(self):
        mw = ContextCompressorMiddleware(tenant_id="tenant_abc")
        assert mw._tenant_id == "tenant_abc"

    def test_disabled_abefore_model(self):
        mw = ContextCompressorMiddleware(token_threshold=10)
        mw._enabled = False
        import asyncio
        result = asyncio.run(
            mw.abefore_model({"messages": _make_text_messages(100)}, Runtime())
        )
        assert result is None

    def test_split_preserves_order(self):
        mw = ContextCompressorMiddleware(protect_first_n=2)
        msgs = _make_text_messages(10, text="msg {i}")
        head, middle, tail = mw._split(msgs)
        assert len(head) == 2
        assert len(tail) == 3
        assert len(middle) == 5
        # 顺序不变
        assert head + middle + tail == msgs


class TestAntiThrashing:
    """Anti-thrashing：避免过于频繁或低效的压缩"""

    def test_should_skip_when_savings_below_threshold(self):
        mw = ContextCompressorMiddleware(token_threshold=10, min_savings_ratio=0.10)
        mw._last_savings_pct = 5.0  # 5% < 10%
        msgs = _make_text_messages(50, text="hello world {i}")
        tokens = count_messages_tokens(msgs)
        reason = mw._should_skip_compression(tokens)
        assert reason is not None
        assert "below min" in reason

    def test_allows_when_savings_above_threshold(self):
        mw = ContextCompressorMiddleware(token_threshold=10, min_savings_ratio=0.10)
        mw._last_savings_pct = 50.0  # 50% > 10%
        msgs = _make_text_messages(50, text="hello world {i}")
        tokens = count_messages_tokens(msgs)
        reason = mw._should_skip_compression(tokens)
        assert reason is None

    def test_first_compression_not_blocked(self):
        mw = ContextCompressorMiddleware(token_threshold=10)
        assert mw._last_savings_pct is None
        msgs = _make_text_messages(50, text="hello world {i}")
        tokens = count_messages_tokens(msgs)
        reason = mw._should_skip_compression(tokens)
        assert reason is None

    def test_record_compression_updates_state(self):
        mw = ContextCompressorMiddleware(token_threshold=10)
        mw._record_compression(before_tokens=1000, after_tokens=300)
        assert mw._last_compression_time is not None
        assert mw._last_savings_pct == 70.0  # (1 - 300/1000) * 100

    def test_skipped_via_before_model_hook(self):
        mw = ContextCompressorMiddleware(token_threshold=10)
        # 模拟上次节省率极低
        mw._last_savings_pct = 3.0
        messages = _make_text_messages(50, text="hello world {i}")
        result = mw.before_model({"messages": messages}, Runtime())
        assert result is None  # anti-thrashing 阻止

    async def test_skipped_via_abefore_model_hook(self):
        mw = ContextCompressorMiddleware(token_threshold=10, llm=AsyncMock())
        mw._last_savings_pct = 3.0
        messages = _make_text_messages(50, text="hello world {i}")
        result = await mw.abefore_model({"messages": messages}, Runtime())
        assert result is None


class TestFallbackLLM:
    """3 级回退：primary → fallback → truncation"""

    async def test_primary_succeeds(self):
        primary = AsyncMock()
        primary.ainvoke.return_value.content = "primary summary"
        fallback = AsyncMock()
        mw = ContextCompressorMiddleware(
            token_threshold=10, llm=primary, fallback_llm=fallback
        )
        msgs = _make_text_messages(10, text="test {i}")
        result = await mw._asummarize_section(msgs)
        assert isinstance(result[0], SummaryMessage)
        assert "primary" in result[0].content
        primary.ainvoke.assert_awaited_once()
        fallback.ainvoke.assert_not_awaited()

    async def test_fallback_succeeds_when_primary_fails(self):
        primary = AsyncMock()
        primary.ainvoke.side_effect = Exception("primary down")
        fallback = AsyncMock()
        fallback.ainvoke.return_value.content = "fallback summary"
        mw = ContextCompressorMiddleware(
            token_threshold=10, llm=primary, fallback_llm=fallback
        )
        msgs = _make_text_messages(10, text="test {i}")
        result = await mw._asummarize_section(msgs)
        assert isinstance(result[0], SummaryMessage)
        assert "fallback" in result[0].content
        fallback.ainvoke.assert_awaited_once()

    async def test_both_fail_falls_back_to_truncation(self):
        primary = AsyncMock()
        primary.ainvoke.side_effect = Exception("primary down")
        fallback = AsyncMock()
        fallback.ainvoke.side_effect = Exception("fallback down")
        mw = ContextCompressorMiddleware(
            token_threshold=10, llm=primary, fallback_llm=fallback
        )
        msgs = _make_text_messages(20, text="long message {i} " * 10)
        result = await mw._asummarize_section(msgs)
        # 回退截断后第一条是 SummaryMessage
        assert isinstance(result[0], SummaryMessage)
        assert len(result) < len(msgs)
