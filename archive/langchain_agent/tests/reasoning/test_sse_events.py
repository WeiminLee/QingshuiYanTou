"""SSE event protocol regression tests for the current LangChain agent path."""

from __future__ import annotations

import asyncio
from unittest.mock import patch


def test_filter_maps_reasoning_started_to_canonical_reasoning_start():
    from app.reasoning.api.agent import _filter_sse_event

    visible, mapped = _filter_sse_event("reasoning_started", {"question": "test"})

    assert visible is True
    assert mapped == "reasoning_start"


def test_filter_maps_thinking_delta_to_frontend_thinking():
    from app.reasoning.api.agent import _filter_sse_event

    visible, mapped = _filter_sse_event("thinking_delta", {"delta": "分析中"})

    assert visible is True
    assert mapped == "thinking"


def test_event_type_contains_task_and_terminal_events():
    from app.reasoning.api.agent_events import EventType

    assert EventType.REASONING_START == "reasoning_start"
    assert EventType.TASK_STARTED == "task_started"
    assert EventType.TASK_RUNNING == "task_running"
    assert EventType.TASK_COMPLETED == "task_completed"
    assert EventType.TASK_FAILED == "task_failed"
    assert EventType.STREAM_END == "stream_end"


def test_emit_reasoning_started_uses_canonical_event_name():
    from app.reasoning.api.agent_events import _task_manager, emit_reasoning_started

    task_id = "canonical-reasoning-start"
    _task_manager.create_task(task_id, "thread", "问题")
    asyncio.run(emit_reasoning_started(task_id, "问题", 3))

    events = _task_manager.get_events(task_id)
    assert events[-1].type == "reasoning_start"
    _task_manager.clear_task(task_id)


def test_v2_stream_does_not_add_extra_stream_end():
    """Regression for duplicate stream_end in /v2/stream."""
    import app.reasoning.api.agent as agent_module
    from app.reasoning.api.agent import V2StreamRequest, v2_stream

    class FakeResponse:
        def __init__(self, generator):
            self.generator = generator

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        async def run(self, question, emit_fn=None):
            await emit_fn("thinking_delta", {"delta": "分析", "turn": 1})
            await emit_fn("stream_end", {"content": "完成", "report_content": "完成"})
            return {"content": "完成"}

    async def collect():
        request = V2StreamRequest(question="分析光模块")
        with (
            patch.object(agent_module, "EventSourceResponse", FakeResponse),
            patch("app.reasoning.langchain_agent.client.LangChainAgentClient", FakeClient),
        ):
            response = await v2_stream(request, api_key="test")
            chunks = []
            async for chunk in response.generator:
                chunks.append(chunk)
            return chunks

    chunks = asyncio.run(collect())
    stream_end_count = sum('"type": "stream_end"' in chunk for chunk in chunks)
    assert stream_end_count == 1


def test_ping_interval_constant_exists():
    from app.reasoning.api import agent_events as ae_module

    assert ae_module.PING_INTERVAL == 60
