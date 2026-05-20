"""
tests/reasoning/test_context_compressor.py

Phase D TDD — 上下文压缩系统

验收标准：
- [x] 30+ 轮对话或 >60K token 触发压缩
- [x] 摘要保留原始关键信息
- [x] anti-thrashing（上次压缩节省 <10% 时跳过）
- [x] 单元测试覆盖率 ≥ 80%

Run: uv run --directory backend python -m pytest tests/reasoning/test_context_compressor.py -v
"""
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from dataclasses import dataclass


# ── 辅助 Mock ─────────────────────────────────────────────────────────

@dataclass
class MockMessage:
    """简化版消息对象，兼容 LangChain 消息接口"""
    content: str
    type: str = "human"


def _make_messages(count: int, content_template: str = "对话内容 {i}") -> list:
    """生成指定数量的 MockMessage 列表"""
    return [
        MockMessage(content=content_template.format(i=i), type="human" if i % 2 == 0 else "ai")
        for i in range(count)
    ]


# ── Test 1: 触发条件判断 ─────────────────────────────────────────────


class TestCompressionTrigger:
    """压缩触发条件：turns > 30 或 tokens > 60000"""

    def test_turns_exceeds_threshold_triggers(self):
        """消息数量超过阈值时应触发压缩"""
        from app.reasoning.langchain_agent.middlewares.context_compressor import (
            ContextCompressor,
        )
        mw = ContextCompressor(turn_threshold=30, token_threshold=60000)
        messages = _make_messages(35)
        should, reason = mw._should_summarize(messages)
        assert should is True, f"35条消息应触发压缩，实际：{reason}"

    def test_tokens_exceeds_threshold_triggers(self):
        """token 数量超过阈值时应触发压缩"""
        from app.reasoning.langchain_agent.middlewares.context_compressor import (
            ContextCompressor,
        )
        mw = ContextCompressor(turn_threshold=999, token_threshold=1000)
        # 每条消息 ~250 字符 ≈ 62 tokens，20条 ≈ 1240 tokens
        messages = _make_messages(20, content_template="对话内容测试 {i} " * 50)
        should, reason = mw._should_summarize(messages)
        assert should is True, f"20条长消息应触发压缩，实际：{reason}"

    def test_below_threshold_no_compression(self):
        """消息数量和 token 均低于阈值时不触发压缩"""
        from app.reasoning.langchain_agent.middlewares.context_compressor import (
            ContextCompressor,
        )
        mw = ContextCompressor(turn_threshold=30, token_threshold=60000)
        messages = _make_messages(10)
        should, reason = mw._should_summarize(messages)
        assert should is False, f"10条消息不应触发压缩，实际：{reason}"

    def test_custom_threshold(self):
        """自定义阈值应正确生效"""
        from app.reasoning.langchain_agent.middlewares.context_compressor import (
            ContextCompressor,
        )
        mw = ContextCompressor(turn_threshold=5, token_threshold=999999)
        messages = _make_messages(4)
        assert mw._should_summarize(messages)[0] is False
        messages = _make_messages(6)
        assert mw._should_summarize(messages)[0] is True


# ── Test 2: Token 估算 ───────────────────────────────────────────────


class TestTokenEstimation:
    """_estimate_tokens 估算准确性"""

    def test_empty_messages_zero_tokens(self):
        """空消息列表返回 0"""
        from app.reasoning.langchain_agent.middlewares.context_compressor import (
            ContextCompressor,
        )
        mw = ContextCompressor()
        assert mw._estimate_tokens([]) == 0

    def test_short_message_estimated(self):
        """短消息的 token 估算合理（约等于 len/4）"""
        from app.reasoning.langchain_agent.middlewares.context_compressor import (
            ContextCompressor,
        )
        mw = ContextCompressor()
        msgs = [MockMessage(content="hello world")]
        tokens = mw._estimate_tokens(msgs)
        # "hello world" 约 2 tokens，len=11，len/4=2.75
        assert 2 <= tokens <= 4

    def test_long_message_estimated(self):
        """长消息 token 估算（改进后会更准确）"""
        from app.reasoning.langchain_agent.middlewares.context_compressor import (
            ContextCompressor,
        )
        mw = ContextCompressor()
        long_content = "测试内容 " * 100
        msgs = [MockMessage(content=long_content)]
        tokens = mw._estimate_tokens(msgs)
        # 约 500 字符，中文约 200-300 tokens（改进后更准确）
        # 400 Chinese chars // 2 = 200 tokens + 100 spaces // 4 = 25 tokens = ~225 tokens
        assert 150 < tokens < 350, f"中文估算应更准确，实际: {tokens}"


# ── Test 3: 修剪旧 tool results ──────────────────────────────────────


class TestPruneToolResults:
    """_prune_tool_results 修剪无 LLM 调用的中间 tool results"""

    def test_empty_list_unchanged(self):
        """空列表直接返回"""
        from app.reasoning.langchain_agent.middlewares.context_compressor import (
            ContextCompressor,
        )
        mw = ContextCompressor()
        result = mw._prune_tool_results([])
        assert result == []

    def test_no_tool_results_unchanged(self):
        """没有 tool result 消息时列表不变"""
        from app.reasoning.langchain_agent.middlewares.context_compressor import (
            ContextCompressor,
        )
        mw = ContextCompressor()
        messages = _make_messages(5)
        result = mw._prune_tool_results(messages)
        assert len(result) == 5

    def test_old_tool_results_pruned(self):
        """中间部分的 tool result 应被修剪，保留首尾"""
        from app.reasoning.langchain_agent.middlewares.context_compressor import (
            ContextCompressor,
        )

        @dataclass
        class MockToolResult:
            content: str
            type: str = "tool"
            name: str = "get_kline"

        mw = ContextCompressor()
        messages = [
            MockMessage(content="查询光模块行情", type="human"),
            MockMessage(content="以下是光模块数据...", type="ai"),
            MockToolResult(content="[K线数据] 800G光模块 ..."),  # 旧 tool result → 修剪
            MockToolResult(content="[K线数据] 200G光模块 ..."),  # 旧 tool result → 修剪
            MockMessage(content="现在分析竞争格局", type="human"),
            MockToolResult(content="[K线数据] 中际旭创 ..."),   # 最近 tool result → 保留
        ]
        result = mw._prune_tool_results(messages)
        # 保留最近的 tool result（最后一个），中间的被修剪
        assert len(result) <= len(messages)
        # 保留最近 tool result 的完整内容
        tool_contents = [getattr(m, "content", "") for m in result if getattr(m, "type", "") == "tool"]
        assert any("中际旭创" in c for c in tool_contents)

    def test_pruned_tool_results_replaced_with_summary(self):
        """被修剪的 tool result 应替换为摘要占位符"""
        from app.reasoning.langchain_agent.middlewares.context_compressor import (
            ContextCompressor,
        )

        @dataclass
        class MockToolResult:
            content: str
            type: str = "tool"
            name: str = "get_kline"

        mw = ContextCompressor()
        messages = [
            MockMessage(content="查询光模块行情", type="human"),
            MockMessage(content="以下是光模块数据...", type="ai"),
            MockToolResult(content="[K线数据] 800G光模块 ... 非常长的内容"),  # 旧 → 修剪
        ]
        result = mw._prune_tool_results(messages)
        # 工具结果应该被替换（不包含原始长内容）
        tool_contents = [getattr(m, "content", "") for m in result if getattr(m, "type", "") == "tool"]
        for content in tool_contents:
            assert len(content) < 200, "修剪后的 tool result 应短于原始内容"


# ── Test 4: Head 保护 ────────────────────────────────────────────────


class TestProtectHead:
    """_protect_head 保留 system prompt 和首条交换"""

    def test_head_protected_count(self):
        """默认保护前 3 条消息（system + 首次交换）"""
        from app.reasoning.langchain_agent.middlewares.context_compressor import (
            ContextCompressor,
        )
        mw = ContextCompressor(protect_first_n=3)
        messages = _make_messages(20)
        protected, unprotected = mw._protect_head(messages)
        assert len(protected) == 3, f"应保护前3条，实际：{len(protected)}"
        assert len(unprotected) == 17

    def test_protected_messages_unchanged(self):
        """被保护的消息内容不变"""
        from app.reasoning.langchain_agent.middlewares.context_compressor import (
            ContextCompressor,
        )
        mw = ContextCompressor(protect_first_n=2)
        messages = _make_messages(10)
        protected, _ = mw._protect_head(messages)
        for i, msg in enumerate(protected):
            assert msg.content == messages[i].content


# ── Test 5: Tail 截断 ────────────────────────────────────────────────


class TestTruncateTail:
    """_truncate_tail 尾部 token 保护"""

    def test_below_budget_unchanged(self):
        """总 token 在预算内时尾部不变"""
        from app.reasoning.langchain_agent.middlewares.context_compressor import (
            ContextCompressor,
        )
        mw = ContextCompressor()
        messages = _make_messages(5, content_template="短消息 {i}")
        tail = messages[-3:]
        # 100% budget → 全部保留
        result = mw._truncate_tail(tail, budget_pct=1.0)
        assert len(result) == len(tail), f"预算内应保留全部尾部，实际保留 {len(result)}/{len(tail)}"

    def test_above_budget_truncated(self):
        """总 token 超出预算时截断尾部"""
        from app.reasoning.langchain_agent.middlewares.context_compressor import (
            ContextCompressor,
        )
        mw = ContextCompressor()
        # 每条约 125 tokens（500字符），3条约 375 tokens
        messages = _make_messages(3, content_template="测试内容 " * 125)
        budget_pct = 0.05  # 5% → 375 * 0.05 = 18.75 tokens，只够 0 条
        result = mw._truncate_tail(messages, budget_pct=budget_pct)
        # 预算极小时应截断（保留少于原始）
        assert len(result) < len(messages), (
            f"超低预算应截断尾部，实际保留 {len(result)}/{len(messages)} 条"
        )

    def test_empty_tail_unchanged(self):
        """空尾部直接返回"""
        from app.reasoning.langchain_agent.middlewares.context_compressor import (
            ContextCompressor,
        )
        mw = ContextCompressor()
        result = mw._truncate_tail([], budget_pct=0.2)
        assert result == []


# ── Test 6: LLM 摘要 ─────────────────────────────────────────────────


class TestLLMSummarize:
    """_llm_summarize 调用 LLM 生成结构化摘要"""

    def test_summarize_returns_structured_output(self):
        """LLM 摘要应包含结构化字段"""
        import asyncio
        from unittest.mock import AsyncMock
        from app.reasoning.langchain_agent.middlewares.context_compressor import (
            ContextCompressor,
        )

        mw = ContextCompressor(summary_model="mock-model")
        messages = _make_messages(10, content_template="分析光模块行业 {i}：竞争格局、技术路线、市场规模")
        # Mock LLM 调用（用 AsyncMock 确保协程正常返回）
        mock_response = """## 当前任务
分析光模块行业竞争格局

## 已完成行动
- 收集了中际旭创财务数据
- 整理了行业技术路线信息

## 遇到障碍
暂无

## 剩余工作
完成竞争格局总结
"""
        mock_llm = AsyncMock(return_value=mock_response)
        with patch(
            "app.reasoning.langchain_agent.middlewares.context_compressor.call_llm_async",
            mock_llm,
        ):
            result = asyncio.run(mw._llm_summarize(messages, current_task="分析光模块行业"))
            assert "当前任务" in result or "##" in result
            assert "已完成" in result or "##" in result

    def test_summarize_empty_messages_returns_empty(self):
        """空消息列表不应调用 LLM"""
        import asyncio
        from app.reasoning.langchain_agent.middlewares.context_compressor import (
            ContextCompressor,
        )

        mw = ContextCompressor()
        with patch(
            "app.reasoning.langchain_agent.middlewares.context_compressor.call_llm_async",
            new_callable=AsyncMock,
        ) as mock_llm:
            result = asyncio.run(mw._llm_summarize([]))
            assert mock_llm.call_count == 0
            assert result == ""


# ── Test 7: Anti-Thrashing ────────────────────────────────────────────


class TestAntiThrashing:
    """上次压缩节省 <10% 时跳过，避免反复压缩"""

    def test_savings_below_threshold_skips(self):
        """上次压缩节省率 < 10% 时，_should_summarize 应返回 False"""
        from app.reasoning.langchain_agent.middlewares.context_compressor import (
            ContextCompressor,
        )
        mw = ContextCompressor(
            turn_threshold=30,
            token_threshold=60000,
            min_savings_ratio=0.10,
        )
        # 模拟上次压缩节省了 5%
        mw._last_compression_savings_pct = 5.0
        messages = _make_messages(35)
        # anti-thrashing 应阻止压缩
        should, reason = mw._should_summarize(messages)
        assert should is False, f"anti-thrashing 应阻止压缩（节省率仅 5%），实际：{reason}"

    def test_savings_above_threshold_allows(self):
        """上次压缩节省率 ≥ 10% 时允许再次压缩"""
        from app.reasoning.langchain_agent.middlewares.context_compressor import (
            ContextCompressor,
        )
        mw = ContextCompressor(
            turn_threshold=30,
            token_threshold=60000,
            min_savings_ratio=0.10,
        )
        mw._last_compression_savings_pct = 50.0
        messages = _make_messages(35)
        should, _ = mw._should_summarize(messages)
        assert should is True

    def test_first_compression_not_blocked(self):
        """首次压缩（无历史节省率）不被阻止"""
        from app.reasoning.langchain_agent.middlewares.context_compressor import (
            ContextCompressor,
        )
        mw = ContextCompressor(turn_threshold=30)
        # _last_compression_savings_pct 未设置时（None）不阻止
        mw._last_compression_savings_pct = None
        messages = _make_messages(35)
        should, _ = mw._should_summarize(messages)
        assert should is True


# ── Test 8: 完整压缩流程 ─────────────────────────────────────────────


class TestFullCompression:
    """compress() 端到端压缩"""

    def test_compress_reduces_message_count(self):
        """压缩后消息数量应显著减少"""
        import asyncio
        from unittest.mock import AsyncMock
        from app.reasoning.langchain_agent.middlewares.context_compressor import (
            ContextCompressor,
        )

        mw = ContextCompressor(
            turn_threshold=5,
            token_threshold=100,
            protect_first_n=2,
            min_savings_ratio=0.10,
        )
        messages = _make_messages(20, content_template="这是第 {i} 条分析内容，用于测试上下文压缩功能 " * 20)

        # Mock LLM 返回正常摘要（不抛异常）
        mock_llm = AsyncMock(return_value="## 摘要\n已完成 18 条分析。")
        with patch(
            "app.reasoning.langchain_agent.middlewares.context_compressor.call_llm_async",
            mock_llm,
        ):
            result = asyncio.run(mw.compress(messages))

        # 压缩后消息数量应减少（head + summary + tail < 原始）
        assert len(result) < len(messages), (
            f"压缩后({len(result)})应少于原始({len(messages)})"
        )

    def test_compress_preserves_head_and_tail(self):
        """压缩后首尾消息内容保留"""
        import asyncio
        from unittest.mock import AsyncMock
        from app.reasoning.langchain_agent.middlewares.context_compressor import (
            ContextCompressor,
        )

        mw = ContextCompressor(
            turn_threshold=5,
            token_threshold=100,
            protect_first_n=2,
            min_savings_ratio=0.10,
        )
        messages = _make_messages(20)
        original_head = messages[:2]

        mock_llm = AsyncMock(return_value="## 摘要\n已完成分析。")
        with patch(
            "app.reasoning.langchain_agent.middlewares.context_compressor.call_llm_async",
            mock_llm,
        ):
            result = asyncio.run(mw.compress(messages))

        # Head 消息内容保留
        for i, orig_msg in enumerate(original_head):
            assert result[i].content == orig_msg.content

    def test_compress_updates_savings_tracking(self):
        """压缩后更新节省率追踪"""
        import asyncio
        from unittest.mock import AsyncMock
        from app.reasoning.langchain_agent.middlewares.context_compressor import (
            ContextCompressor,
        )

        mw = ContextCompressor(
            turn_threshold=5,
            token_threshold=100,
            min_savings_ratio=0.10,
        )
        messages = _make_messages(20, content_template="测试压缩 " * 50)

        mock_llm = AsyncMock(return_value="## 摘要\n已压缩。")
        with patch(
            "app.reasoning.langchain_agent.middlewares.context_compressor.call_llm_async",
            mock_llm,
        ):
            asyncio.run(mw.compress(messages))

        # 节省率应被记录（> 0 表示发生了有效压缩）
        assert mw._last_compression_savings_pct is not None
        assert mw._last_compression_savings_pct >= 0  # 可能为 0（LLM 摘要为空时）

    def test_compress_below_threshold_unchanged(self):
        """消息数量低于阈值时不压缩"""
        from app.reasoning.langchain_agent.middlewares.context_compressor import (
            ContextCompressor,
        )

        mw = ContextCompressor(turn_threshold=30, token_threshold=60000)
        messages = _make_messages(10)
        result = mw.compress_sync(messages)
        assert len(result) == len(messages)


# ── Test 9: can_parallel 启发式（Phase E）─────────────────────────────


class TestCanParallelHeuristic:
    """Phase E: 工具并发执行启发式"""

    def test_single_tool_not_parallel(self):
        """单个工具调用不并发"""
        from app.reasoning.langchain_agent.middlewares.context_compressor import (
            can_parallel,
        )

        tool_calls = [{"name": "get_kline", "args": {}}]
        assert can_parallel(tool_calls) is False

    def test_readonly_tools_parallel(self):
        """多个只读工具可以并发"""
        from app.reasoning.langchain_agent.middlewares.context_compressor import (
            can_parallel,
        )

        tool_calls = [
            {"name": "get_kline", "args": {}},
            {"name": "get_concept_hot", "args": {}},
            {"name": "tavily_search", "args": {}},
        ]
        assert can_parallel(tool_calls) is True

    def test_write_tool_prevents_parallel(self):
        """写操作工具禁止并发"""
        from app.reasoning.langchain_agent.middlewares.context_compressor import (
            can_parallel,
        )

        tool_calls = [
            {"name": "get_kline", "args": {}},
            {"name": "present_chart", "args": {}},  # 生成文件
        ]
        assert can_parallel(tool_calls) is False

    def test_clarify_never_parallel(self):
        """clarify 工具永不并发"""
        from app.reasoning.langchain_agent.middlewares.context_compressor import (
            can_parallel,
        )

        tool_calls = [
            {"name": "get_kline", "args": {}},
            {"name": "clarify", "args": {}},
        ]
        assert can_parallel(tool_calls) is False

    def test_path_conflict_prevents_parallel(self):
        """相同文件路径的工具调用不并发"""
        from app.reasoning.langchain_agent.middlewares.context_compressor import (
            can_parallel,
        )

        tool_calls = [
            {"name": "get_kline", "args": {"code": "000001"}},
            {"name": "get_kline", "args": {"code": "000001"}},  # 相同标的
        ]
        # 相同 code → 路径冲突
        assert can_parallel(tool_calls) is False

    def test_different_paths_can_parallel(self):
        """不同标的的工具可以并发"""
        from app.reasoning.langchain_agent.middlewares.context_compressor import (
            can_parallel,
        )

        tool_calls = [
            {"name": "get_kline", "args": {"code": "000001"}},
            {"name": "get_kline", "args": {"code": "000002"}},
            {"name": "get_stock_profile", "args": {"code": "300308"}},
        ]
        assert can_parallel(tool_calls) is True

    def test_unknown_tool_prevents_parallel(self):
        """未知工具禁止并发（保守策略）"""
        from app.reasoning.langchain_agent.middlewares.context_compressor import (
            can_parallel,
        )

        tool_calls = [
            {"name": "get_kline", "args": {}},
            {"name": "unknown_custom_tool", "args": {}},
        ]
        assert can_parallel(tool_calls) is False

    def test_empty_list_not_parallel(self):
        """空列表不并发"""
        from app.reasoning.langchain_agent.middlewares.context_compressor import (
            can_parallel,
        )

        assert can_parallel([]) is False


# ── Test 10: 降级处理 ────────────────────────────────────────────────


class TestCompressorDegradation:
    """压缩过程异常时不阻断 Agent"""

    def test_llm_summary_failure_does_not_raise(self):
        """LLM 摘要失败时返回原始消息列表"""
        import asyncio
        from app.reasoning.langchain_agent.middlewares.context_compressor import (
            ContextCompressor,
        )

        mw = ContextCompressor(turn_threshold=5, token_threshold=100)

        @dataclass
        class MockMsg:
            content: str
            type: str = "human"

        messages = [MockMsg(content=f"msg {i}") for i in range(20)]

        with patch(
            "app.reasoning.langchain_agent.middlewares.context_compressor.call_llm_async",
            side_effect=Exception("LLM 服务不可用"),
        ):
            # compress_sync 不应抛异常
            try:
                mw.compress_sync(messages)
            except Exception as e:
                pytest.fail(f"compress_sync 不应抛异常，实际：{e}")

    def test_malformed_message_handled(self):
        """格式不正确的消息（缺少属性）不崩溃"""
        from app.reasoning.langchain_agent.middlewares.context_compressor import (
            ContextCompressor,
        )

        mw = ContextCompressor()
        # 无 content 属性的消息
        bad_messages = [object()] * 5
        try:
            mw._estimate_tokens(bad_messages)
        except Exception as e:
            pytest.fail(f"_estimate_tokens 不应崩溃，实际：{e}")
