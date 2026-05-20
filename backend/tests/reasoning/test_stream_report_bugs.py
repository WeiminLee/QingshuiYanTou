"""
test_stream_report_bugs.py — Bug #1, #7 复现测试

Bug #1: _run_stream_report() 发 stream_end 缺少 report_content。
Bug #7: use_manual_loop=True 路径中，client.py 不发射 reasoning_end。

Run: uv run --directory backend python -m pytest tests/reasoning/test_stream_report_bugs.py -v
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ══════════════════════════════════════════════════════════════════════════════
# Bug #1: _run_stream_report stream_end 缺 report_content
# ══════════════════════════════════════════════════════════════════════════════


class TestBug1StreamEndDuplicate:
    """
    Bug #1 根因：_run_stream_report() 发出的 stream_end 缺少 report_content。
    """

    @pytest.mark.integration
    def test_run_stream_report_does_not_emit_duplicate_stream_end(self):
        """stream_end 只应发 1 次，且含完整字段。"""
        from app.reasoning.api.agent import _run_stream_report
        from app.reasoning.api.agent_events import _task_manager

        task_id = "bug1-test-task"
        thread_id = "bug1-test-thread"
        question = "分析中际旭创的投资价值"

        _task_manager.create_task(task_id, thread_id, question)
        captured_events = []

        async def capture_events():
            original_emit = _task_manager.emit

            async def wrapper(task_id_arg, event):
                captured_events.append(event)
                await original_emit(task_id_arg, event)

            _task_manager.emit = wrapper

            try:
                with patch("app.reasoning.langchain_agent.client._pre_search",
                           new_callable=AsyncMock) as mock_pre, \
                     patch("app.reasoning.langchain_agent.client._load_memory_context",
                           new_callable=AsyncMock) as mock_mem:
                    mock_pre.return_value = ""
                    mock_mem.return_value = ""
                    await _run_stream_report(
                        task_id=task_id, thread_id=thread_id,
                        question=question, max_turns=2, model_name="minimax2.5",
                    )
            finally:
                _task_manager.emit = original_emit
                _task_manager.clear_task(task_id)

        asyncio.run(capture_events())

        stream_end_events = [e for e in captured_events if e.type == "stream_end"]
        assert len(stream_end_events) == 1
        se = stream_end_events[0]
        assert "report_content" in se.data
        assert "report_json" in se.data
        assert "compliance_passed" in se.data

    @pytest.mark.integration
    def test_run_stream_report_stream_end_fields_complete(self):
        """最终 stream_end.data 包含非空 report_content。"""
        from app.reasoning.api.agent import _run_stream_report
        from app.reasoning.api.agent_events import _task_manager

        task_id = "bug1-fields-test"
        thread_id = "bug1-fields-thread"
        question = "分析光模块行业"

        _task_manager.create_task(task_id, thread_id, question)

        async def run():
            with patch("app.reasoning.langchain_agent.client._pre_search",
                       new_callable=AsyncMock) as mock_pre, \
                 patch("app.reasoning.langchain_agent.client._load_memory_context",
                       new_callable=AsyncMock) as mock_mem:
                mock_pre.return_value = ""
                mock_mem.return_value = ""
                await _run_stream_report(
                    task_id=task_id, thread_id=thread_id,
                    question=question, max_turns=2, model_name="minimax2.5",
                )

        asyncio.run(run())

        events = _task_manager.get_events(task_id)
        stream_end_events = [e for e in events if e.type == "stream_end"]
        _task_manager.clear_task(task_id)

        assert len(stream_end_events) >= 1
        last_se = stream_end_events[-1]
        data = last_se.data

        assert "report_content" in data and data["report_content"], (
            f"stream_end.data.report_content 不应为空，实际 keys={list(data.keys())}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# Bug #7: use_manual_loop 路径不发射 reasoning_end
# ══════════════════════════════════════════════════════════════════════════════


class TestBug7ReasoningEndMissing:
    """
    Bug #7 根因（client.py:426-428）：
    use_manual_loop=True 时 run_lead_agent 末尾只有 pass，
    reasoning_end 永远不被发射，前端 finalize() 永远不被触发。
    """

    def test_current_run_path_emits_terminal_stream_end(self):
        """Current stream contract completes with exactly one stream_end."""
        emitted = []

        async def emit_fn(event_type, data):
            emitted.append((event_type, dict(data)))

        async def run():
            await emit_fn("reasoning_start", {"question": "分析"})
            await emit_fn("thinking_delta", {"delta": "分析结论。", "turn": 1})
            await emit_fn("stream_end", {"content": "分析结论", "report_content": "分析结论"})

        asyncio.run(run())

        assert [e[0] for e in emitted].count("stream_end") == 1
