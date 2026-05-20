"""
tests/reasoning/test_task_events.py

Bug C4 TDD: task_events.py 全局队列在多 task 并发时互相覆盖

Bug 描述：
  task_events.py 使用全局变量 `_task_events_queue` 存储队列。
  当多个 task 并发运行时，它们会共享同一个队列，导致事件互相覆盖。

修复方案：
  改用 `dict[task_id, queue.Queue]` 按 task_id 隔离队列。

Run: uv run --directory backend python -m pytest tests/reasoning/test_task_events.py -v
"""
import pytest
import queue
import threading
import time
import concurrent.futures


class TestTaskEventsQueueIsolation:
    """多 task 并发时队列隔离测试"""

    def test_single_task_queue_works(self):
        """单个 task 的队列正常工作"""
        from app.reasoning.langchain_agent.task_events import (
            get_task_events_queue,
            reset_task_events_queue,
            enqueue_task_event,
            drain_task_events,
            TaskEvent,
            TaskEventType,
        )

        reset_task_events_queue(task_id="task-1")
        enqueue_task_event(TaskEvent(
            type=TaskEventType.TASK_STARTED,
            task_id="task-1",
            data={"message": "started"},
        ))
        events = drain_task_events(task_id="task-1")

        assert len(events) == 1
        assert events[0].task_id == "task-1"

    def test_concurrent_tasks_have_isolated_queues(self):
        """
        并发运行的多个 task 应有独立的队列（修复后 PASS）

        修复后每个 task_id 有独立队列，不会互相覆盖。
        """
        from app.reasoning.langchain_agent.task_events import (
            get_task_events_queue,
            reset_task_events_queue,
            enqueue_task_event,
            drain_task_events,
            TaskEvent,
            TaskEventType,
        )

        results = {"task1": [], "task2": []}

        def task1_workflow():
            """Task 1 工作流程"""
            enqueue_task_event(TaskEvent(
                type=TaskEventType.TASK_STARTED,
                task_id="task-1",
                data={"seq": 1},
            ))
            enqueue_task_event(TaskEvent(
                type=TaskEventType.TASK_RUNNING,
                task_id="task-1",
                data={"seq": 2},
            ))
            time.sleep(0.1)  # 给 task-2 更多时间
            # drain task-1 的队列
            events = drain_task_events(task_id="task-1")
            results["task1"] = events

        def task2_workflow():
            """Task 2 工作流程"""
            time.sleep(0.01)  # 让 task-1 先开始
            enqueue_task_event(TaskEvent(
                type=TaskEventType.TASK_STARTED,
                task_id="task-2",
                data={"seq": 1},
            ))
            enqueue_task_event(TaskEvent(
                type=TaskEventType.TASK_RUNNING,
                task_id="task-2",
                data={"seq": 2},
            ))
            time.sleep(0.1)
            # drain task-2 的队列
            events = drain_task_events(task_id="task-2")
            results["task2"] = events

        reset_task_events_queue()  # 清理所有队列

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            f1 = executor.submit(task1_workflow)
            f2 = executor.submit(task2_workflow)
            f1.result()
            f2.result()

        # 修复后：每个 task 只看到自己的 2 个事件
        assert len(results["task1"]) == 2, f"task-1 应有 2 个事件，实际: {len(results['task1'])}"
        assert len(results["task2"]) == 2, f"task-2 应有 2 个事件，实际: {len(results['task2'])}"

        # 验证 task_id 正确
        assert all(e.task_id == "task-1" for e in results["task1"])
        assert all(e.task_id == "task-2" for e in results["task2"])

    def test_reset_clears_specific_task_queue(self):
        """reset_task_events_queue(task_id) 应清空指定 task 的队列"""
        from app.reasoning.langchain_agent.task_events import (
            get_task_events_queue,
            reset_task_events_queue,
            enqueue_task_event,
            drain_task_events,
            TaskEvent,
            TaskEventType,
        )

        enqueue_task_event(TaskEvent(
            type=TaskEventType.TASK_STARTED,
            task_id="task-x",
            data={},
        ))

        reset_task_events_queue(task_id="task-x")
        events = drain_task_events(task_id="task-x")

        assert len(events) == 0, "指定 task 队列应为空"

    def test_reset_clears_all_queues(self):
        """reset_task_events_queue(None) 应清空所有队列"""
        from app.reasoning.langchain_agent.task_events import (
            get_task_events_queue,
            reset_task_events_queue,
            enqueue_task_event,
            drain_task_events,
            TaskEvent,
            TaskEventType,
        )

        # 添加两个 task 的事件
        enqueue_task_event(TaskEvent(
            type=TaskEventType.TASK_STARTED,
            task_id="task-a",
            data={},
        ))
        enqueue_task_event(TaskEvent(
            type=TaskEventType.TASK_STARTED,
            task_id="task-b",
            data={},
        ))

        reset_task_events_queue(None)  # 清理所有
        events_a = drain_task_events(task_id="task-a")
        events_b = drain_task_events(task_id="task-b")

        assert len(events_a) == 0
        assert len(events_b) == 0


class TestTaskEventsAPI:
    """task_events 模块 API 测试"""

    def test_task_event_type_enum(self):
        """TaskEventType 枚举值正确"""
        from app.reasoning.langchain_agent.task_events import TaskEventType

        assert TaskEventType.TASK_STARTED == "task_started"
        assert TaskEventType.TASK_RUNNING == "task_running"
        assert TaskEventType.TASK_COMPLETED == "task_completed"
        assert TaskEventType.TASK_FAILED == "task_failed"
        assert TaskEventType.TASK_TIMED_OUT == "task_timed_out"

    def test_task_event_dataclass(self):
        """TaskEvent 数据类字段正确"""
        from app.reasoning.langchain_agent.task_events import TaskEvent, TaskEventType

        event = TaskEvent(
            type=TaskEventType.TASK_STARTED,
            task_id="test-123",
            data={"key": "value"},
        )

        assert event.type == TaskEventType.TASK_STARTED
        assert event.task_id == "test-123"
        assert event.data == {"key": "value"}

    def test_enqueue_full_queue_handled(self):
        """队列满时 enqueue 不抛异常"""
        from app.reasoning.langchain_agent.task_events import (
            get_task_events_queue,
            reset_task_events_queue,
            enqueue_task_event,
            TaskEvent,
            TaskEventType,
        )

        reset_task_events_queue(task_id="test-queue")
        q = get_task_events_queue(task_id="test-queue")

        for i in range(100):
            try:
                enqueue_task_event(TaskEvent(
                    type=TaskEventType.TASK_RUNNING,
                    task_id="test-queue",
                    data={"i": i},
                ))
            except Exception as e:
                pytest.fail(f"enqueue 不应抛异常: {e}")