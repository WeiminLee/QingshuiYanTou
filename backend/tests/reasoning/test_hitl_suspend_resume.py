"""Tests for HITL suspend/resume checkpoint store."""

import asyncio

import pytest
from app.reasoning.langchain_agent.hitl_store import (
    HITLStore, PendingClarification, get_hitl_store,
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
