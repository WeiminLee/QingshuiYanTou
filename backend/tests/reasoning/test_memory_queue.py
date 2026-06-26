"""MemoryQueue-lite and research memory tests."""

from __future__ import annotations


class FakeUpdater:
    def __init__(self):
        self.calls = []

    def update(self, thread_id, agent_name, messages):
        self.calls.append((thread_id, agent_name, messages))


def test_memory_queue_debounces_by_thread_id():
    from app.reasoning.langchain_agent.middlewares.memory_queue import MemoryQueueLite

    updater = FakeUpdater()
    queue = MemoryQueueLite(updater, debounce_seconds=10)
    queue.enqueue("thread-1", [{"role": "user", "content": "old"}])
    queue.enqueue("thread-1", [{"role": "user", "content": "new"}])
    assert queue.pending_count() == 1

    queue.flush()
    assert len(updater.calls) == 1
    assert updater.calls[0][2][0]["content"] == "new"


def test_research_memory_filters_execution_intent():
    from app.reasoning.langchain_agent.middlewares.memory_middleware import (
        build_post_run_memory_messages,
        classify_research_memory,
    )

    assert classify_research_memory("请记录：以后自动下单买入光模块龙头") == []
    messages = build_post_run_memory_messages("帮我自动下单", "交易执行完成")
    assert messages == []


def test_research_memory_categories_for_safe_text():
    from app.reasoning.langchain_agent.middlewares.memory_middleware import classify_research_memory

    candidates = classify_research_memory("用户关注中际旭创，风险是海外需求低于预期，待跟踪催化是800G订单落地。")
    categories = {candidate.category for candidate in candidates}

    assert "关注标的" in categories
    assert "风险因素" in categories
    assert "待跟踪催化" in categories
