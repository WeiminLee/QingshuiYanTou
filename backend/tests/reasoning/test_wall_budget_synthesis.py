# backend/tests/reasoning/test_wall_budget_synthesis.py
"""截断后收尾合成：消息清洗 + best-effort 合成。"""
from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage


def test_sanitize_strips_unfulfilled_tool_calls():
    from app.reasoning.langchain_agent.client import _sanitize_messages_for_final_answer

    msg = AIMessage(
        content="我来查询数据。",
        tool_calls=[
            {"id": "call-1", "name": "compare_metric", "args": {}},
            {"id": "call-2", "name": "fetch_evidence", "args": {}},
        ],
    )
    tool_msg = ToolMessage(content="{}", tool_call_id="call-1", name="compare_metric")
    out = _sanitize_messages_for_final_answer([HumanMessage(content="Q"), msg, tool_msg])

    # 未兑现 call-2 → 该 AIMessage 退化为纯文本，不再携带 tool_calls
    ai = [m for m in out if isinstance(m, AIMessage)]
    assert len(ai) == 1
    assert not ai[0].tool_calls
    assert ai[0].content == "我来查询数据。"
    assert any(isinstance(m, ToolMessage) for m in out)


def test_sanitize_keeps_fully_fulfilled_tool_calls():
    from app.reasoning.langchain_agent.client import _sanitize_messages_for_final_answer

    msg = AIMessage(
        content="",
        tool_calls=[{"id": "call-1", "name": "compare_metric", "args": {}}],
    )
    tool_msg = ToolMessage(content="{}", tool_call_id="call-1", name="compare_metric")
    out = _sanitize_messages_for_final_answer([msg, tool_msg])

    ai = [m for m in out if isinstance(m, AIMessage)]
    assert ai and ai[0].tool_calls  # 全部兑现 → 原样保留


class _FakeModel:
    def __init__(self, text: str = "最终结论：300861.SZ 口径存疑，剔除。"):
        self.captured: list = []
        self._text = text

    async def ainvoke(self, messages):
        self.captured = messages
        return AIMessage(content=self._text)


@pytest.mark.asyncio
async def test_synthesize_returns_text_and_injects_instruction():
    from app.reasoning.langchain_agent.client import _synthesize_final_answer

    fake = _FakeModel()
    got = await _synthesize_final_answer(fake, [HumanMessage(content="Q")], timeout=5.0)
    assert got == fake._text
    # 收尾调用必须带上「不要再调用工具」的指令
    assert any("不要再调用工具" in str(m.content) for m in fake.captured)


@pytest.mark.asyncio
async def test_synthesize_failure_returns_empty():
    from app.reasoning.langchain_agent.client import _synthesize_final_answer

    class _Boom:
        async def ainvoke(self, messages):
            raise RuntimeError("llm down")

    assert await _synthesize_final_answer(_Boom(), [HumanMessage(content="Q")], timeout=5.0) == ""
