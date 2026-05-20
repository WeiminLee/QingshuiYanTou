"""
V2 Agent 集成测试 — 模拟前端请求，验证工具调用和 SSE 事件格式

测试目标：
1. 工具调用正确性（tool_called 事件格式）
2. SSE 事件格式符合前端组件需求（thinking/tool_called/tool_result/stream_end）
3. V2 架构（create_agent + agent.stream）端到端流程

策略：Mock LLM 返回预设的 AIMessage 序列，驱动 agent.stream() 产生
完整的 ReAct 循环，通过 emit_fn 捕获所有 SSE 事件并验证格式。

Run: uv run --directory backend python -m pytest tests/reasoning/test_v2_agent_integration.py -v
"""
import asyncio
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool


# ── Mock LLM ────────────────────────────────────────────────────────


class MockLLM:
    """
    可配置响应序列的 Mock LLM，兼容 create_agent 的 bind_tools(**kwargs) 签名。
    """

    def __init__(self, responses: list[AIMessage]):
        self._responses = list(responses)
        self._call_count = 0

    def bind_tools(self, tools, **kwargs):
        return self

    def invoke(self, messages, **kwargs):
        if self._call_count < len(self._responses):
            resp = self._responses[self._call_count]
            self._call_count += 1
            return resp
        # 兜底：无更多工具调用，返回纯文本
        return AIMessage(content="分析完成。")


# ── Mock 工具 ────────────────────────────────────────────────────────


@tool
def get_kline(ts_code: str) -> str:
    """获取K线数据"""
    return "股票 300308.SZ K线（20240101~20241231，日线，共120条）：\n- 最新价：45.23（↑3.45%）\n"


@tool
def tavily_search(query: str) -> str:
    """联网检索"""
    return (
        "## 联网检索：「新能源汽车」\n\n"
        "**1. 政策补贴解读**\n   来源：[新浪](https://sina.com)\n\n"
        "**2. 碳酸锂价格**\n   来源：[东财](https://eastmoney.com)\n\n"
    )


@tool
def get_concept_hot() -> str:
    """获取概念板块热度"""
    return "## 概念板块热度排名（按涨跌幅，共 20 条）\n\n| 排名 | 板块名称 | 涨跌幅 |\n| 1 | AI芯片 | ↑5.23% |\n"


@tool
def get_stock_profile(ts_code: str) -> str:
    """获取股票概况"""
    return "## 300308.SZ 股票概况\n\n- **主营业务**：高端光通信模块及器件的研发、生产和销售\n"


MOCK_TOOLS = [get_kline, tavily_search, get_concept_hot, get_stock_profile]


# ── 辅助函数 ────────────────────────────────────────────────────────


def _run_agent_stream(
    mock_llm: MockLLM,
    user_message: str = "查询300308的K线",
    tools: list | None = None,
    system_prompt: str = "你是投研助手。",
) -> list[tuple[str, dict]]:
    """
    运行 create_agent + agent.stream()，通过 emit_fn 捕获所有 SSE 事件。

    模拟 client.py 中 run_lead_agent 的核心循环逻辑：
    - 遍历 agent.stream() 的每个 chunk
    - 对 messages 去重（seen_msg_ids）
    - AIMessage: 提取 tool_calls → tool_called, text → thinking_delta
    - ToolMessage: 提取 result → tool_result（含 preview）
    - 结束时发射 stream_end

    Returns:
        [(event_type, data_dict), ...]
    """
    if tools is None:
        tools = MOCK_TOOLS

    agent = create_agent(
        model=mock_llm,
        tools=tools,
        system_prompt=system_prompt,
    )

    state = {"messages": [HumanMessage(content=user_message)]}
    config = RunnableConfig(
        configurable={"thread_id": f"test-{str(uuid.uuid4())[:8]}"},
        recursion_limit=20,
    )

    emitted: list[tuple[str, dict]] = []
    seen_msg_ids: set[str] = set()
    full_content: list[str] = []
    turn_count = 0

    from app.reasoning.langchain_agent.tool_executor import build_preview

    for chunk in agent.stream(state, config=config, stream_mode="values"):
        messages = chunk.get("messages", [])
        turn_count += 1

        for msg in messages:
            msg_id = getattr(msg, "id", None) or str(uuid.uuid4())[:8]
            if msg_id in seen_msg_ids:
                continue
            seen_msg_ids.add(msg_id)

            if isinstance(msg, AIMessage):
                # Tool calls → tool_called
                if msg.tool_calls:
                    for tc in msg.tool_calls:
                        tc_id = tc.get("id") or str(uuid.uuid4())[:8]
                        tc_name = tc.get("name", "")
                        tc_args = tc.get("args", {}) or {}
                        emitted.append(("tool_called", {
                            "id": tc_id,
                            "name": tc_name,
                            "args": tc_args,
                            "turn": turn_count,
                        }))

                # Text content → thinking_delta
                text = _extract_text(msg.content)
                if text:
                    full_content.append(text)
                    emitted.append(("thinking_delta", {
                        "delta": text,
                        "turn": turn_count,
                    }))

            elif isinstance(msg, ToolMessage):
                result_str = _extract_text(msg.content) or str(msg.content)
                tool_name = getattr(msg, "name", "unknown")
                preview = build_preview(tool_name, result_str)

                emitted.append(("tool_result", {
                    "id": msg_id,
                    "name": tool_name,
                    "result": preview,
                    "success": True,
                    "turn": turn_count,
                    "original_len": len(result_str),
                    "duration_ms": 0.0,
                }))

    # stream_end
    from app.reasoning.output.report import AnalysisReport
    from datetime import datetime

    report = AnalysisReport(
        report_id=str(uuid.uuid4())[:8],
        topic=user_message,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        raw_analysis="".join(full_content),
    )
    report.compliance_declared = True

    emitted.append(("stream_end", {
        "report_content": report.to_markdown(),
        "report_json": report.to_dict(),
        "report_id": report.report_id,
        "compliance_passed": report.compliance_declared,
        "turns": turn_count,
        "content": "".join(full_content),
    }))

    return emitted


def _extract_text(content: str | list | None) -> str:
    """从 AIMessage.content 中提取纯文本"""
    if not content:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        return "".join(parts)
    return str(content)


# ══════════════════════════════════════════════════════════════════════════════
# 测试 1: 工具调用正确性
# ══════════════════════════════════════════════════════════════════════════════


class TestToolCallCorrectness:
    """验证 agent 正确调用工具并产生 tool_called 事件"""

    def test_single_tool_call_emits_tool_called(self):
        """
        场景：LLM 调用单个工具 get_kline
        期望：发射 tool_called 事件，含 id/name/args/turn
        """
        mock_llm = MockLLM(responses=[
            AIMessage(content="", tool_calls=[
                {"id": "tc_1", "name": "get_kline", "args": {"ts_code": "300308.SZ"}}
            ]),
            AIMessage(content="K线数据显示上涨趋势。"),
        ])

        emitted = _run_agent_stream(mock_llm)

        tool_called_events = [e for e in emitted if e[0] == "tool_called"]
        assert len(tool_called_events) >= 1, \
            f"未发射 tool_called 事件，实际事件：{[e[0] for e in emitted]}"

        _, data = tool_called_events[0]
        assert data["name"] == "get_kline", f"工具名应为 get_kline，实际：{data['name']}"
        assert data["args"]["ts_code"] == "300308.SZ", f"参数应含 ts_code，实际：{data['args']}"
        assert "id" in data, "tool_called 应含 id 字段"
        assert "turn" in data, "tool_called 应含 turn 字段"

    def test_multiple_tool_calls_emit_multiple_events(self):
        """
        场景：LLM 并发调用 get_kline + tavily_search
        期望：发射两个 tool_called 事件，id 唯一
        """
        mock_llm = MockLLM(responses=[
            AIMessage(content="", tool_calls=[
                {"id": "tc_1", "name": "get_kline", "args": {"ts_code": "300308.SZ"}},
                {"id": "tc_2", "name": "tavily_search", "args": {"query": "光模块行业"}},
            ]),
            AIMessage(content="综合分析完成。"),
        ])

        emitted = _run_agent_stream(mock_llm)

        tool_called_events = [e for e in emitted if e[0] == "tool_called"]
        assert len(tool_called_events) == 2, \
            f"应发射 2 个 tool_called，实际：{len(tool_called_events)}"

        names = [e[1]["name"] for e in tool_called_events]
        assert "get_kline" in names, f"应含 get_kline，实际：{names}"
        assert "tavily_search" in names, f"应含 tavily_search，实际：{names}"

        ids = [e[1]["id"] for e in tool_called_events]
        assert len(ids) == len(set(ids)), f"tool_called id 应唯一，实际：{ids}"

    def test_tool_called_event_schema(self):
        """
        场景：tool_called 事件
        期望：符合前端组件需要的 schema
        前端需要：{ id, name, args, turn }
        """
        mock_llm = MockLLM(responses=[
            AIMessage(content="", tool_calls=[
                {"id": "tc_schema", "name": "get_stock_profile", "args": {"ts_code": "300308.SZ"}}
            ]),
            AIMessage(content="分析完成。"),
        ])

        emitted = _run_agent_stream(mock_llm)

        tool_called_events = [e for e in emitted if e[0] == "tool_called"]
        assert len(tool_called_events) >= 1

        _, data = tool_called_events[0]
        required_fields = {"id", "name", "args", "turn"}
        missing = required_fields - set(data.keys())
        assert not missing, f"tool_called 缺少字段：{missing}"


# ══════════════════════════════════════════════════════════════════════════════
# 测试 2: SSE 事件格式符合前端组件需求
# ══════════════════════════════════════════════════════════════════════════════


class TestSSEEventFormat:
    """验证 SSE 事件格式符合前端组件渲染需求"""

    def test_thinking_delta_format(self):
        """
        场景：LLM 返回文本内容
        期望：thinking_delta 事件含 delta 字段（增量文本）和 turn
        前端 ThinkingBlock 需要：{ delta: string, turn: number }
        """
        mock_llm = MockLLM(responses=[
            AIMessage(content="中际旭创光模块业务表现强劲，维持买入评级。"),
        ])

        emitted = _run_agent_stream(mock_llm)

        thinking_events = [e for e in emitted if e[0] == "thinking_delta"]
        assert len(thinking_events) >= 1, \
            f"未发射 thinking_delta，实际事件：{[e[0] for e in emitted]}"

        _, data = thinking_events[0]
        assert "delta" in data, "thinking_delta 应含 delta 字段"
        assert isinstance(data["delta"], str), "delta 应为字符串"
        assert len(data["delta"]) > 0, "delta 不应为空"
        assert "turn" in data, "thinking_delta 应含 turn 字段"

    def test_tool_result_format(self):
        """
        场景：工具执行完成
        期望：tool_result 事件含前端需要的所有字段
        前端 ToolCallBlock 需要：{ id, name, result, success, turn }
        """
        mock_llm = MockLLM(responses=[
            AIMessage(content="", tool_calls=[
                {"id": "tc_1", "name": "get_kline", "args": {"ts_code": "300308.SZ"}}
            ]),
            AIMessage(content="K线数据已获取。"),
        ])

        emitted = _run_agent_stream(mock_llm)

        tool_result_events = [e for e in emitted if e[0] == "tool_result"]
        assert len(tool_result_events) >= 1, \
            f"未发射 tool_result，实际事件：{[e[0] for e in emitted]}"

        _, data = tool_result_events[0]
        # 前端必需字段
        required_fields = {"id", "name", "result", "success", "turn"}
        missing = required_fields - set(data.keys())
        assert not missing, f"tool_result 缺少前端必需字段：{missing}"

        # Phase F: result 应为 preview 短描述
        assert isinstance(data["result"], str), "result 应为字符串"
        assert len(data["result"]) < 200, \
            f"Phase F: result 应为 preview 短描述（<200字符），实际长度={len(data['result'])}"
        assert isinstance(data["success"], bool), "success 应为布尔值"

    def test_tool_result_preview_is_meaningful(self):
        """
        场景：get_kline 返回 Markdown
        期望：preview 包含统计信息（如 K 线条数），不是原始数据
        """
        mock_llm = MockLLM(responses=[
            AIMessage(content="", tool_calls=[
                {"id": "tc_1", "name": "get_kline", "args": {"ts_code": "300308.SZ"}}
            ]),
            AIMessage(content="分析完成。"),
        ])

        emitted = _run_agent_stream(mock_llm)

        tool_result_events = [e for e in emitted if e[0] == "tool_result"]
        assert len(tool_result_events) >= 1

        _, data = tool_result_events[0]
        # preview 应包含统计信息
        assert "120" in data["result"] or "条" in data["result"], \
            f"K线 preview 应包含条数统计，实际：{data['result']}"

    def test_tool_result_original_len_field(self):
        """
        场景：tool_result 事件
        期望：含 original_len 字段（前端可展示数据量级）
        """
        mock_llm = MockLLM(responses=[
            AIMessage(content="", tool_calls=[
                {"id": "tc_1", "name": "get_kline", "args": {"ts_code": "300308.SZ"}}
            ]),
            AIMessage(content="完成。"),
        ])

        emitted = _run_agent_stream(mock_llm)

        tool_result_events = [e for e in emitted if e[0] == "tool_result"]
        assert len(tool_result_events) >= 1

        _, data = tool_result_events[0]
        assert "original_len" in data, "tool_result 应含 original_len 字段"
        assert data["original_len"] > 0, "原始结果长度应 > 0"

    def test_stream_end_format(self):
        """
        场景：Agent 分析完成
        期望：stream_end 事件含前端需要的所有字段
        前端需要：{ report_content, report_json, report_id, compliance_passed, turns }
        """
        mock_llm = MockLLM(responses=[
            AIMessage(content="中际旭创光模块业务表现强劲，维持买入评级。"),
        ])

        emitted = _run_agent_stream(mock_llm)

        stream_end_events = [e for e in emitted if e[0] == "stream_end"]
        assert len(stream_end_events) >= 1, \
            f"未发射 stream_end，实际事件：{[e[0] for e in emitted]}"

        _, data = stream_end_events[0]
        required_fields = {"report_content", "report_json", "report_id", "compliance_passed", "turns"}
        missing = required_fields - set(data.keys())
        assert not missing, f"stream_end 缺少前端必需字段：{missing}"

    def test_stream_end_report_content_is_markdown(self):
        """
        场景：stream_end 中的 report_content
        期望：为非空 Markdown 字符串
        """
        mock_llm = MockLLM(responses=[
            AIMessage(content="光模块景气向上，中际旭创为龙头。"),
        ])

        emitted = _run_agent_stream(mock_llm)

        stream_end_events = [e for e in emitted if e[0] == "stream_end"]
        assert len(stream_end_events) >= 1

        report_content = stream_end_events[0][1]["report_content"]
        assert isinstance(report_content, str), "report_content 应为字符串"
        assert len(report_content) > 0, "report_content 不应为空"

    def test_stream_end_report_json_has_report_id(self):
        """
        场景：stream_end 中的 report_json
        期望：含 report_id 字段（前端缓存 key）
        """
        mock_llm = MockLLM(responses=[
            AIMessage(content="分析结论。"),
        ])

        emitted = _run_agent_stream(mock_llm)

        stream_end_events = [e for e in emitted if e[0] == "stream_end"]
        assert len(stream_end_events) >= 1

        report_json = stream_end_events[0][1]["report_json"]
        assert "report_id" in report_json, "report_json 应含 report_id"
        assert report_json["report_id"], "report_id 不应为空"

    def test_stream_end_compliance_passed_is_bool(self):
        """
        场景：stream_end 中的 compliance_passed
        期望：为布尔值
        """
        mock_llm = MockLLM(responses=[
            AIMessage(content="结论。"),
        ])

        emitted = _run_agent_stream(mock_llm)

        stream_end_events = [e for e in emitted if e[0] == "stream_end"]
        assert len(stream_end_events) >= 1

        compliance = stream_end_events[0][1]["compliance_passed"]
        assert isinstance(compliance, bool), f"compliance_passed 应为 bool，实际：{type(compliance)}"


# ══════════════════════════════════════════════════════════════════════════════
# 测试 3: 完整事件序列验证
# ══════════════════════════════════════════════════════════════════════════════


class TestEventSequence:
    """验证完整 ReAct 循环的事件序列"""

    def test_full_react_cycle_event_order(self):
        """
        场景：完整 ReAct 循环（思考→工具调用→工具结果→最终回答）
        期望：事件序列为 tool_called → tool_result → thinking_delta → stream_end
        """
        mock_llm = MockLLM(responses=[
            AIMessage(content="", tool_calls=[
                {"id": "tc_1", "name": "get_kline", "args": {"ts_code": "300308.SZ"}}
            ]),
            AIMessage(content="K线数据显示上涨趋势，建议关注。"),
        ])

        emitted = _run_agent_stream(mock_llm)

        event_types = [e[0] for e in emitted]

        # 应包含完整的 ReAct 事件序列
        assert "tool_called" in event_types, "应包含 tool_called 事件"
        assert "tool_result" in event_types, "应包含 tool_result 事件"
        assert "thinking_delta" in event_types, "应包含 thinking_delta 事件"
        assert "stream_end" in event_types, "应包含 stream_end 事件"

        # stream_end 应为最后一个事件
        assert event_types[-1] == "stream_end", \
            f"stream_end 应为最后一个事件，实际最后事件：{event_types[-1]}"

    def test_multi_tool_react_cycle(self):
        """
        场景：多工具 ReAct 循环
        期望：每个工具调用都有对应的 tool_called + tool_result
        """
        mock_llm = MockLLM(responses=[
            AIMessage(content="", tool_calls=[
                {"id": "tc_1", "name": "get_kline", "args": {"ts_code": "300308.SZ"}},
                {"id": "tc_2", "name": "get_concept_hot", "args": {}},
            ]),
            AIMessage(content="综合分析完成。"),
        ])

        emitted = _run_agent_stream(mock_llm)

        tool_called = [e for e in emitted if e[0] == "tool_called"]
        tool_results = [e for e in emitted if e[0] == "tool_result"]

        assert len(tool_called) == 2, f"应有 2 个 tool_called，实际：{len(tool_called)}"
        assert len(tool_results) == 2, f"应有 2 个 tool_result，实际：{len(tool_results)}"

        # 工具名匹配
        called_names = [e[1]["name"] for e in tool_called]
        result_names = [e[1]["name"] for e in tool_results]
        assert set(called_names) == set(result_names), \
            f"tool_called 和 tool_result 的工具名应匹配：{called_names} vs {result_names}"

    def test_no_tool_calls_only_thinking(self):
        """
        场景：LLM 直接回答，不调用工具
        期望：只有 thinking_delta + stream_end，无 tool_called/tool_result
        """
        mock_llm = MockLLM(responses=[
            AIMessage(content="这是一个简单的市场概述，无需查询数据。"),
        ])

        emitted = _run_agent_stream(mock_llm)

        event_types = [e[0] for e in emitted]
        assert "tool_called" not in event_types, "不应有 tool_called 事件"
        assert "tool_result" not in event_types, "不应有 tool_result 事件"
        assert "thinking_delta" in event_types, "应有 thinking_delta 事件"
        assert "stream_end" in event_types, "应有 stream_end 事件"


# ══════════════════════════════════════════════════════════════════════════════
# 测试 4: SSE 事件映射（前端可见事件名）
# ══════════════════════════════════════════════════════════════════════════════


class TestSSEEventMapping:
    """验证后端事件到前端可见事件的映射"""

    def test_visible_map_covers_core_events(self):
        """
        场景：前端需要接收的核心事件类型
        期望：_VISIBLE_MAP 覆盖 thinking_delta/tool_called/tool_result/reasoning_start
        """
        from app.reasoning.api.agent import _VISIBLE_MAP

        core_events = ["thinking_delta", "tool_called", "tool_result", "reasoning_start"]
        for event in core_events:
            assert event in _VISIBLE_MAP, \
                f"_VISIBLE_MAP 应包含 {event}，实际：{list(_VISIBLE_MAP.keys())}"

    def test_thinking_delta_maps_to_thinking(self):
        """thinking_delta 应映射为前端 thinking 事件"""
        from app.reasoning.api.agent import _VISIBLE_MAP

        assert _VISIBLE_MAP["thinking_delta"] == "thinking", \
            f"thinking_delta 应映射为 thinking，实际：{_VISIBLE_MAP.get('thinking_delta')}"

    def test_tool_called_maps_to_tool_called(self):
        """tool_called 前端事件名不变"""
        from app.reasoning.api.agent import _VISIBLE_MAP

        assert _VISIBLE_MAP["tool_called"] == "tool_called", \
            f"tool_called 应映射为 tool_called，实际：{_VISIBLE_MAP.get('tool_called')}"

    def test_tool_result_maps_to_tool_result(self):
        """tool_result 前端事件名不变"""
        from app.reasoning.api.agent import _VISIBLE_MAP

        assert _VISIBLE_MAP["tool_result"] == "tool_result", \
            f"tool_result 应映射为 tool_result，实际：{_VISIBLE_MAP.get('tool_result')}"

    def test_filter_sse_event_function(self):
        """_filter_sse_event 正确映射和过滤事件"""
        from app.reasoning.api.agent import _filter_sse_event

        # thinking_delta → thinking（可见）
        is_visible, mapped = _filter_sse_event("thinking_delta", {})
        assert is_visible is True
        assert mapped == "thinking"

        # tool_called → tool_called（可见）
        is_visible, mapped = _filter_sse_event("tool_called", {})
        assert is_visible is True
        assert mapped == "tool_called"

        # tool_result → tool_result（可见）
        is_visible, mapped = _filter_sse_event("tool_result", {})
        assert is_visible is True
        assert mapped == "tool_result"

        # 未知事件 → 原样透传
        is_visible, mapped = _filter_sse_event("custom_event", {})
        assert is_visible is True
        assert mapped == "custom_event"


# ══════════════════════════════════════════════════════════════════════════════
# 测试 5: build_preview 各工具类型
# ══════════════════════════════════════════════════════════════════════════════


class TestBuildPreviewIntegration:
    """验证 build_preview 在 agent stream 中的集成效果"""

    def test_kline_preview_in_tool_result(self):
        """get_kline 工具结果 preview 包含条数"""
        mock_llm = MockLLM(responses=[
            AIMessage(content="", tool_calls=[
                {"id": "tc_1", "name": "get_kline", "args": {"ts_code": "300308.SZ"}}
            ]),
            AIMessage(content="完成。"),
        ])

        emitted = _run_agent_stream(mock_llm)
        tool_results = [e for e in emitted if e[0] == "tool_result" and e[1]["name"] == "get_kline"]
        assert len(tool_results) >= 1

        preview = tool_results[0][1]["result"]
        assert "120" in preview or "条" in preview, \
            f"K线 preview 应包含条数，实际：{preview}"

    def test_tavily_search_preview_in_tool_result(self):
        """tavily_search 工具结果 preview 包含文章数"""
        mock_llm = MockLLM(responses=[
            AIMessage(content="", tool_calls=[
                {"id": "tc_1", "name": "tavily_search", "args": {"query": "光模块"}}
            ]),
            AIMessage(content="完成。"),
        ])

        emitted = _run_agent_stream(mock_llm)
        tool_results = [e for e in emitted if e[0] == "tool_result" and e[1]["name"] == "tavily_search"]
        assert len(tool_results) >= 1

        preview = tool_results[0][1]["result"]
        assert "2" in preview or "篇" in preview, \
            f"搜索 preview 应包含文章数，实际：{preview}"

    def test_concept_hot_preview_in_tool_result(self):
        """get_concept_hot 工具结果 preview 包含板块数"""
        mock_llm = MockLLM(responses=[
            AIMessage(content="", tool_calls=[
                {"id": "tc_1", "name": "get_concept_hot", "args": {}}
            ]),
            AIMessage(content="完成。"),
        ])

        emitted = _run_agent_stream(mock_llm)
        tool_results = [e for e in emitted if e[0] == "tool_result" and e[1]["name"] == "get_concept_hot"]
        assert len(tool_results) >= 1

        preview = tool_results[0][1]["result"]
        assert "20" in preview or "板块" in preview, \
            f"热度 preview 应包含板块数，实际：{preview}"

    def test_stock_profile_preview_in_tool_result(self):
        """get_stock_profile 工具结果 preview 包含主营业务"""
        mock_llm = MockLLM(responses=[
            AIMessage(content="", tool_calls=[
                {"id": "tc_1", "name": "get_stock_profile", "args": {"ts_code": "300308.SZ"}}
            ]),
            AIMessage(content="完成。"),
        ])

        emitted = _run_agent_stream(mock_llm)
        tool_results = [e for e in emitted if e[0] == "tool_result" and e[1]["name"] == "get_stock_profile"]
        assert len(tool_results) >= 1

        preview = tool_results[0][1]["result"]
        assert "光通信" in preview or "主营业务" in preview, \
            f"股票概况 preview 应包含主营业务关键词，实际：{preview}"


# ══════════════════════════════════════════════════════════════════════════════
# 测试 6: run_lead_agent 端到端（mock 外部依赖）
# ══════════════════════════════════════════════════════════════════════════════


class TestRunLeadAgentE2E:
    """
    直接调用 run_lead_agent()，mock 掉 Qdrant/Memory/LLM 等外部依赖，
    验证完整 SSE 事件流格式。
    """

    def test_run_lead_agent_emits_correct_events(self):
        """
        场景：调用 run_lead_agent()，mock LLM 返回工具调用序列
        期望：emit_fn 收到 thinking_delta / tool_called / tool_result / stream_end
        """
        asyncio.run(self._test_emits_correct_events())

    async def _test_emits_correct_events(self):
        from app.reasoning.langchain_agent.client import run_lead_agent

        emitted = []

        async def emit_fn(event_type, data):
            emitted.append((event_type, data))

        # Mock 掉外部依赖
        with patch("app.reasoning.langchain_agent.client._pre_search", new_callable=AsyncMock) as mock_pre, \
             patch("app.reasoning.langchain_agent.client._load_memory_context", new_callable=AsyncMock) as mock_mem, \
             patch("app.reasoning.langchain_agent.client._create_chat_model") as mock_model_fn, \
             patch("app.reasoning.langchain_agent.client._get_tools") as mock_tools, \
             patch("app.reasoning.langchain_agent.client.make_lead_agent") as mock_make_agent:

            mock_pre.return_value = ""
            mock_mem.return_value = ""

            # 创建 mock model
            call_count = [0]
            def mock_invoke(messages, **kwargs):
                call_count[0] += 1
                if call_count[0] == 1:
                    return AIMessage(content="", tool_calls=[
                        {"id": "tc_e2e", "name": "get_kline", "args": {"ts_code": "300308.SZ"}}
                    ])
                return AIMessage(content="K线分析完成，上涨趋势。")

            mock_model = MagicMock()
            mock_model.bind_tools = MagicMock(return_value=mock_model)
            mock_model.invoke = mock_invoke
            mock_model.ainvoke = AsyncMock(side_effect=lambda messages, **kwargs: mock_invoke(messages, **kwargs))
            mock_model_fn.return_value = mock_model

            # Mock 工具
            mock_tool = MagicMock()
            mock_tool.name = "get_kline"
            mock_tool.description = "获取K线数据"
            mock_tool.invoke = MagicMock(return_value="K线数据：300308.SZ，共120条")
            mock_tools.return_value = [mock_tool]

            class FakeAgent:
                async def astream(self, state, config=None, stream_mode=None):
                    yield {"messages": [
                        AIMessage(content="", tool_calls=[
                            {"id": "tc_e2e", "name": "get_kline", "args": {"ts_code": "300308.SZ"}}
                        ])
                    ]}
                    yield {"messages": [
                        ToolMessage(content="K线数据：300308.SZ，共120条", tool_call_id="tc_e2e", name="get_kline"),
                    ]}
                    yield {"messages": [AIMessage(content="K线分析完成，上涨趋势。")]}

            mock_make_agent.return_value = FakeAgent()

            result = await run_lead_agent(
                question="查询300308的K线",
                thread_id="test-e2e-thread",
                model_name="test-model",
                max_turns=4,
                emit_fn=emit_fn,
            )

        # 验证返回结果
        assert "content" in result, f"返回结果应含 content，实际：{list(result.keys())}"
        assert "thread_id" in result, f"返回结果应含 thread_id，实际：{list(result.keys())}"
        assert result["thread_id"] == "test-e2e-thread"

        # 验证 SSE 事件
        event_types = [e[0] for e in emitted]

        # 至少应有 reasoning_start + stream_end
        assert "reasoning_start" in event_types, \
            f"应有 reasoning_start，实际事件：{event_types}"
        assert "stream_end" in event_types, \
            f"应有 stream_end，实际事件：{event_types}"

    def test_run_lead_agent_clarification_intercept(self):
        """
        场景：发送模糊问题（太短）
        期望：ClarificationMiddleware 拦截，发射 clarification_request 事件
        """
        asyncio.run(self._test_clarification_intercept())

    async def _test_clarification_intercept(self):
        from app.reasoning.langchain_agent.client import run_lead_agent

        emitted = []

        async def emit_fn(event_type, data):
            emitted.append((event_type, data))

        with patch("app.reasoning.langchain_agent.client._pre_search", new_callable=AsyncMock) as mock_pre, \
             patch("app.reasoning.langchain_agent.client._load_memory_context", new_callable=AsyncMock) as mock_mem:

            mock_pre.return_value = ""
            mock_mem.return_value = ""

            result = await run_lead_agent(
                question="分析",  # 太短，应被拦截
                thread_id="test-clarify",
                model_name="test-model",
                max_turns=4,
                emit_fn=emit_fn,
            )

        # 验证拦截
        assert result.get("status") == "clarification_requested", \
            f"应被澄清拦截，实际状态：{result.get('status')}"

        event_types = [e[0] for e in emitted]
        assert "clarification_request" in event_types, \
            f"应有 clarification_request 事件，实际：{event_types}"

    def test_run_lead_agent_error_handling(self):
        """
        场景：agent 执行过程中抛出异常
        期望：emit_fn 收到 error 事件
        """
        asyncio.run(self._test_error_handling())

    async def _test_error_handling(self):
        from app.reasoning.langchain_agent.client import run_lead_agent

        emitted = []

        async def emit_fn(event_type, data):
            emitted.append((event_type, data))

        with patch("app.reasoning.langchain_agent.client._pre_search", new_callable=AsyncMock) as mock_pre, \
             patch("app.reasoning.langchain_agent.client._load_memory_context", new_callable=AsyncMock) as mock_mem, \
             patch("app.reasoning.langchain_agent.client._create_chat_model") as mock_model_fn, \
             patch("app.reasoning.langchain_agent.client._get_tools") as mock_tools, \
             patch("app.reasoning.langchain_agent.client.make_lead_agent") as mock_make_agent:

            mock_pre.return_value = ""
            mock_mem.return_value = ""

            # Mock model 抛出异常
            mock_model = MagicMock()
            mock_model.bind_tools = MagicMock(return_value=mock_model)
            mock_model.invoke = MagicMock(side_effect=RuntimeError("Model unavailable"))
            mock_model.ainvoke = AsyncMock(side_effect=RuntimeError("Model unavailable"))
            mock_model_fn.return_value = mock_model

            mock_tool = MagicMock()
            mock_tool.name = "get_kline"
            mock_tool.description = "获取K线"
            mock_tool.invoke = MagicMock(return_value="数据")
            mock_tools.return_value = [mock_tool]

            class FailingAgent:
                async def astream(self, state, config=None, stream_mode=None):
                    raise RuntimeError("Model unavailable")
                    yield {}

            mock_make_agent.return_value = FailingAgent()

            with pytest.raises(RuntimeError):
                await run_lead_agent(
                    question="测试错误处理",
                    thread_id="test-error",
                    model_name="test-model",
                    max_turns=2,
                    emit_fn=emit_fn,
                )

        # 验证 error 事件
        event_types = [e[0] for e in emitted]
        assert "error" in event_types, \
            f"应有 error 事件，实际：{event_types}"


# ══════════════════════════════════════════════════════════════════════════════
# 测试 7: SSE 事件 JSON 可序列化
# ══════════════════════════════════════════════════════════════════════════════


class TestSSEEventSerialization:
    """验证所有 SSE 事件可被 JSON 序列化（前端 EventSource 需要）"""

    def test_all_events_json_serializable(self):
        """
        场景：完整 ReAct 循环产生的所有事件
        期望：每个事件的 data 字典可被 json.dumps 序列化
        """
        import json

        mock_llm = MockLLM(responses=[
            AIMessage(content="", tool_calls=[
                {"id": "tc_1", "name": "get_kline", "args": {"ts_code": "300308.SZ"}}
            ]),
            AIMessage(content="K线分析完成。"),
        ])

        emitted = _run_agent_stream(mock_llm)

        for event_type, data in emitted:
            try:
                serialized = json.dumps(data, ensure_ascii=False, default=str)
            except (TypeError, ValueError) as e:
                pytest.fail(
                    f"事件 {event_type} 无法 JSON 序列化：{e}\n"
                    f"data: {data}"
                )

    def test_stream_end_report_json_serializable(self):
        """
        场景：stream_end 中的 report_json
        期望：可被 JSON 序列化
        """
        import json

        mock_llm = MockLLM(responses=[
            AIMessage(content="分析结论。"),
        ])

        emitted = _run_agent_stream(mock_llm)

        stream_end_events = [e for e in emitted if e[0] == "stream_end"]
        assert len(stream_end_events) >= 1

        report_json = stream_end_events[0][1]["report_json"]
        try:
            serialized = json.dumps(report_json, ensure_ascii=False, default=str)
        except (TypeError, ValueError) as e:
            pytest.fail(f"report_json 无法 JSON 序列化：{e}")
