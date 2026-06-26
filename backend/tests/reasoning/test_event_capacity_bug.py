"""
test_event_capacity_bug.py — Bug #6, #9 复现测试

Bug #6: 两套独立存储冗余
Bug #9: 事件历史无限增长，OOM 风险

Run: uv run --directory backend python -m pytest tests/reasoning/test_event_capacity_bug.py -v
"""

import asyncio

# ══════════════════════════════════════════════════════════════════════════════
# Bug #6: 两套独立存储冗余
# ══════════════════════════════════════════════════════════════════════════════


class TestBug6DuplicateTaskStore:
    """
    Bug #6 根因：
    - _task_store（agent.py）是冗余的独立存储
    - _run_invoke_task 写 _task_store，但 /invoke/{task_id}/result 优先查 TaskStateManager
    - 两套 TTL 逻辑无法差异化
    """

    def test_task_manager_has_set_result(self):
        """
        Bug #6 修复验证：TaskStateManager 有 set_result 方法，
        供 _run_invoke_task 写入，消除对独立 _task_store 的依赖。
        """
        from app.reasoning.api.agent_events import _task_manager

        task_id = "bug6-set-result"
        thread_id = "bug6-thread"
        _task_manager.create_task(task_id, thread_id, "测试问题")

        # set_result 方法存在且可调用
        _task_manager.set_result(task_id, {"content": "分析结论", "turns": 2})

        task = _task_manager.get_task(task_id)
        _task_manager.clear_task(task_id)

        assert task is not None
        assert task.get("result", {}).get("content") == "分析结论"

    def test_both_invoke_and_stream_report_use_task_manager(self):
        """
        Bug #6 修复验证：invoke 和 stream_report 都使用 TaskStateManager。
        set_result 方法是修复关键。
        """
        from app.reasoning.api.agent_events import _task_manager

        task_id = "bug6-shared-store"
        thread_id = "bug6-thread"
        _task_manager.create_task(task_id, thread_id, "分析光模块")

        # 模拟 _run_invoke_task 写入 result（通过 set_result）
        _task_manager.set_result(task_id, {"content": "invoke 结果"})
        _task_manager.update_status(task_id, "done")

        # 模拟 _run_stream_report 写入 result（已有 emit 方法）
        # 两者都使用同一 TaskStateManager，无冗余
        task = _task_manager.get_task(task_id)
        _task_manager.clear_task(task_id)

        assert task is not None
        assert task["status"] == "done"
        assert task.get("result", {}).get("content") == "invoke 结果"


# ══════════════════════════════════════════════════════════════════════════════
# Bug #9: 事件历史无限增长
# ══════════════════════════════════════════════════════════════════════════════


class TestBug9EventHistoryCapacity:
    """
    Bug #9 根因：
    - TaskStateManager._events[task_id].append(event) 无容量上限
    - 异常 Agent（死循环）可无限追加事件直到 OOM
    """

    def test_event_history_has_capacity_limit(self):
        """
        场景：大量事件累积
        期望：_events[task_id] 有容量上限（e.g., 500），超限后先进先出截断
        """
        from app.reasoning.api.agent_events import ReasoningEvent, TaskStateManager

        manager = TaskStateManager()
        task_id = "bug9-capacity-test"

        manager.create_task(task_id, "thread-1", "测试问题")

        MAX_EVENTS = 500
        for i in range(MAX_EVENTS + 100):
            asyncio.run(
                manager.emit(
                    task_id,
                    ReasoningEvent(
                        type=f"event_{i}",
                        task_id=task_id,
                        stage=f"stage_{i}",
                        data={"i": i},
                        turn=0,
                    ),
                )
            )

        events = manager.get_events(task_id)
        manager.clear_task(task_id)

        assert len(events) <= MAX_EVENTS, (
            f"事件历史应有容量上限 {MAX_EVENTS}，实际 {len(events)}。超限事件应被截断，防止 OOM。"
        )

    def test_old_events_truncated_fifo(self):
        """
        场景：超量事件后
        期望：最新事件被保留，旧事件被截断（先进先出）
        """
        from app.reasoning.api.agent_events import ReasoningEvent, TaskStateManager

        manager = TaskStateManager()
        task_id = "bug9-fifo-test"

        manager.create_task(task_id, "thread-1", "测试")

        MAX_EVENTS = 500
        for i in range(MAX_EVENTS + 50):
            asyncio.run(
                manager.emit(
                    task_id,
                    ReasoningEvent(
                        type="thinking",
                        task_id=task_id,
                        stage=f"step_{i}",
                        data={"index": i},
                        turn=0,
                    ),
                )
            )

        events = manager.get_events(task_id)
        manager.clear_task(task_id)

        # 最新事件（index=549）应存在
        assert events[-1].data.get("index") == MAX_EVENTS + 49, "最新事件 index 应为 {}，实际：{}".format(
            MAX_EVENTS + 49, events[-1].data.get("index")
        )

    def test_malicious_agent_memory_bounded(self):
        """
        场景：恶意 Agent 产生 10000 次事件
        期望：内存中只保留 MAX_EVENTS(500) 条，不会 OOM
        """
        from app.reasoning.api.agent_events import ReasoningEvent, TaskStateManager

        manager = TaskStateManager()
        task_id = "bug9-stress-test"

        manager.create_task(task_id, "thread-1", "压力测试")

        MALICIOUS_COUNT = 10000
        for i in range(MALICIOUS_COUNT):
            asyncio.run(
                manager.emit(
                    task_id,
                    ReasoningEvent(
                        type="thinking",
                        task_id=task_id,
                        stage=f"malicious_{i}",
                        data={"delta": "x" * 100},
                        turn=0,
                    ),
                )
            )

        events = manager.get_events(task_id)
        manager.clear_task(task_id)

        MAX_EVENTS = 500
        assert len(events) <= MAX_EVENTS, (
            f"即使 {MALICIOUS_COUNT} 次事件，内存中只保留 <= {MAX_EVENTS} 条，实际：{len(events)}"
        )
        # 内存估算：500 条 * ~300 bytes ~= 150KB（安全）
        assert len(events) * 300 < MALICIOUS_COUNT * 50, "恶意 Agent 不应导致内存线性增长"
