"""
task_events.py — task_tool SSE 事件总线

每个 task_id 有独立的队列，实现线程安全的隔离。
避免多 task 并发时事件互相覆盖的问题。

旧实现（Bug #4）：全局单一队列 `_task_events_queue`
新实现：`dict[task_id, queue.Queue]` 按 task_id 隔离
"""
from __future__ import annotations

import queue
import threading
from dataclasses import dataclass, field
from enum import Enum


class TaskEventType(str, Enum):
    """Task SSE 事件类型"""
    TASK_STARTED = "task_started"
    TASK_RUNNING = "task_running"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    TASK_TIMED_OUT = "task_timed_out"


@dataclass
class TaskEvent:
    """单个 task 事件"""
    type: TaskEventType
    task_id: str
    data: dict = field(default_factory=dict)


# ── 按 task_id 隔离的队列 ───────────────────────────────────────────────────

_task_queues: dict[str, queue.Queue] = {}
_queue_lock = threading.Lock()


def _get_queue_for_task(task_id: str) -> queue.Queue:
    """获取或创建指定 task_id 的队列（线程安全）"""
    with _queue_lock:
        if task_id not in _task_queues:
            _task_queues[task_id] = queue.Queue()
        return _task_queues[task_id]


def get_task_events_queue(task_id: str = "default") -> queue.Queue:
    """获取当前 task 的事件队列"""
    return _get_queue_for_task(task_id)


def reset_task_events_queue(task_id: str | None = None) -> None:
    """
    重置队列。

    Args:
        task_id: 如果提供，只重置该 task 的队列。
               如果为 None，重置所有队列（清理时用）。
    """
    if task_id:
        # 重置单个 task 的队列
        with _queue_lock:
            if task_id in _task_queues:
                _task_queues[task_id] = queue.Queue()
    else:
        # 重置所有队列
        with _queue_lock:
            _task_queues.clear()


def cleanup_all_queues() -> None:
    """清理所有队列（session 结束时调用）"""
    reset_task_events_queue(None)


def enqueue_task_event(event: TaskEvent) -> None:
    """向对应 task 的队列中添加事件（线程安全）"""
    try:
        q = _get_queue_for_task(event.task_id)
        q.put_nowait(event)
    except queue.Full:
        pass  # 队列满时跳过，不阻断任务


def drain_task_events(task_id: str = "default") -> list[TaskEvent]:
    """
    从当前 task 的队列中取出所有事件。

    Args:
        task_id: 指定要 drain 的 task_id。
    """
    events = []
    q = get_task_events_queue(task_id)
    while True:
        try:
            event = q.get_nowait()
            if event is None:
                break
            events.append(event)
        except queue.Empty:
            break
    return events


def drain_all_task_events() -> list[TaskEvent]:
    """从所有 task 的队列中取出所有事件（清理时用）"""
    events = []
    with _queue_lock:
        task_ids = list(_task_queues.keys())
    for tid in task_ids:
        events.extend(drain_task_events(tid))
    return events


# ── 向后兼容别名 ─────────────────────────────────���──────────────────

# 旧 API 兼容性：get_task_events_queue() 不带参数时使用 "default" task_id
# 这可能导致多 task 场景下事件混淆，因此修复后不再推荐使用
# 但保留兼容避免现有代码崩溃
