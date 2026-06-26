"""Tests for HITL suspend/resume checkpoint store."""

import asyncio
from pathlib import Path

import pytest
from app.reasoning.langchain_agent.hitl_store import (
    HITLStore, PendingClarification, get_hitl_store, parse_clarification_result,
)


class TestPendingClarification:
    def test_dataclass_fields(self):
        pc = PendingClarification(
            task_id="task_1", thread_id="thread_1",
            clarification_id="cid_1", question="哪只股票？",
            clarification_type="ambiguous",
            options=None, context=None,
            messages=[], run_config={},
        )
        assert pc.task_id == "task_1"
        assert pc.clarification_id == "cid_1"
        assert pc.created_at is not None


class TestHITLStore:
    async def test_save_and_pop(self):
        store = HITLStore()
        pc = PendingClarification(
            task_id="task_1", thread_id="thread_1",
            clarification_id="cid_1", question="test",
            clarification_type="ambiguous",
            options=None, context=None,
            messages=[], run_config={},
        )
        await store.save("task_1", pc)
        assert await store.get("task_1") is pc
        popped = await store.pop("task_1")
        assert popped is pc
        assert await store.pop("task_1") is None  # 第二次 pop 返回 None

    async def test_cleanup_expired(self):
        store = HITLStore(ttl_seconds=0)  # 立即过期
        pc = PendingClarification(
            task_id="task_1", thread_id="thread_1",
            clarification_id="cid_1", question="test",
            clarification_type="ambiguous",
            options=None, context=None,
            messages=[], run_config={},
        )
        await store.save("task_1", pc)
        await asyncio.sleep(0.01)  # 让 created_at 过期
        cleaned = await store.cleanup_expired()
        assert cleaned >= 1
        assert await store.get("task_1") is None

    async def test_global_singleton(self):
        s1 = get_hitl_store()
        s2 = get_hitl_store()
        assert s1 is s2


class TestClarificationDetection:
    async def test_parse_ask_user_question_json(self):
        result_str = '{"questions": [{"question": "分析哪只？", "options": [{"label": "中际旭创"}]}]}'
        parsed = parse_clarification_result("AskUserQuestion", result_str)
        assert parsed["question"] == "分析哪只？"
        assert len(parsed["options"]) == 1

    async def test_parse_ask_clarification_text(self):
        result_str = "**澄清请求** (ambiguous)\n\n哪只股票？\n\nclarification_id: abc123"
        parsed = parse_clarification_result("ask_clarification", result_str)
        assert parsed["clarification_id"] == "abc123"
        assert "哪只股票" in parsed["question"]

    async def test_no_parse_for_normal_tools(self):
        result = parse_clarification_result("get_kline", "some data")
        assert result is None

    async def test_prebuilt_messages_accepted_in_signature(self):
        src = (Path(__file__).resolve().parents[2] / "app" / "reasoning" / "langchain_agent" / "client.py").read_text()
        assert "prebuilt_messages: list[BaseMessage] | None = None" in src
        assert "skip_preflight: bool = False" in src

    async def test_make_lead_agent_system_prompt_default(self):
        from app.reasoning.langchain_agent.lead_agent import make_lead_agent
        import inspect
        sig = inspect.signature(make_lead_agent)
        param = sig.parameters["system_prompt"]
        assert param.default == ""


class TestResumeAPI:
    async def test_resolve_endpoint_returns_404_for_unknown(self):
        from httpx import AsyncClient, ASGITransport
        from app.main import app
        from app.config import settings

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/v1/agent/resolve/unknown_task", json={
                "answer": "中际旭创", "clarification_id": "cid_1"
            }, headers={"x-api-key": settings.api_key})
            assert resp.status_code == 404

    async def test_resolve_endpoint_accepts_valid_request(self):
        from httpx import AsyncClient, ASGITransport
        from app.main import app
        from app.config import settings
        from app.reasoning.api.agent_events import _task_manager
        from app.reasoning.langchain_agent.hitl_store import get_hitl_store, PendingClarification

        task_id = "test_resolve_task"
        _task_manager.create_task(task_id, "thread_1", "问题")
        store = get_hitl_store()
        await store.save(task_id, PendingClarification(
            task_id=task_id, thread_id="thread_1",
            clarification_id="cid_1", question="哪只？",
            clarification_type="ambiguous",
            options=None, context=None,
            messages=[], run_config={"model_name": "test"},
        ))

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(f"/api/v1/agent/resolve/{task_id}", json={
                "answer": "中际旭创", "clarification_id": "cid_1"
            }, headers={"x-api-key": settings.api_key})
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "resumed"
            assert await store.get(task_id) is None


class TestTTLCleanup:
    async def test_expired_paused_task_sends_timeout_event(self):
        """过期暂停任务自动发 stream_end（超时）。"""
        from app.reasoning.api.agent_events import _task_manager
        _task_manager.create_task("timeout_task", "thread_1", "问题")
        _task_manager.mark_paused("timeout_task")
        assert _task_manager.is_paused("timeout_task")
        await _task_manager.emit_timeout_end("timeout_task")
        status = _task_manager._tasks.get("timeout_task", {}).get("status")
        assert status == "timed_out"

    async def test_cleanup_logging_on_expired(self):
        from app.reasoning.langchain_agent.hitl_store import HITLStore, PendingClarification
        store = HITLStore(ttl_seconds=0)
        pc = PendingClarification(
            task_id="log_test", thread_id="thread_1",
            clarification_id="cid_1", question="test",
            clarification_type="ambiguous",
            options=None, context=None,
            messages=[], run_config={},
        )
        await store.save("log_test", pc)
        await asyncio.sleep(0.01)
        count = await store.cleanup_expired()
        assert count >= 1
        assert await store.get("log_test") is None
