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
