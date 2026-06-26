"""
TaskStore — 纯内存任务存储

存储所有后台 SubAgent 任务的状态，供轮询 API 使用。
进程重启后数据丢失（纯内存设计）。
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class TaskStatus(StrEnum):
    """任务状态枚举"""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"


@dataclass
class TaskRecord:
    """任务记录"""

    task_id: str
    agent_name: str
    prompt: str
    status: TaskStatus = TaskStatus.PENDING
    result: Any = None
    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "agent_name": self.agent_name,
            "status": self.status.value,
            "result": self.result,
            "error": self.error,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "created_at": self.created_at.isoformat(),
        }


class TaskStore:
    """
    纯内存任务存储。

    线程安全，支持多任务并发存储。
    """

    def __init__(self) -> None:
        self._tasks: dict[str, TaskRecord] = {}
        self._lock = threading.RLock()

    def create(self, agent_name: str, prompt: str) -> str:
        """创建新任务，返回 task_id"""
        task_id = str(uuid.uuid4())[:12]
        with self._lock:
            self._tasks[task_id] = TaskRecord(
                task_id=task_id,
                agent_name=agent_name,
                prompt=prompt,
            )
        return task_id

    def get(self, task_id: str) -> TaskRecord | None:
        """获取任务记录"""
        with self._lock:
            return self._tasks.get(task_id)

    def update(
        self,
        task_id: str,
        status: TaskStatus,
        result: Any = None,
        error: str | None = None,
    ) -> bool:
        """更新任务状态"""
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return False
            task.status = status
            task.result = result
            task.error = error
            if status == TaskStatus.RUNNING and task.started_at is None:
                task.started_at = datetime.now()
            if status in (
                TaskStatus.COMPLETED,
                TaskStatus.FAILED,
                TaskStatus.TIMED_OUT,
                TaskStatus.CANCELLED,
            ):
                task.completed_at = datetime.now()
            return True

    def list_by_status(self, status: TaskStatus) -> list[TaskRecord]:
        """列出指定状态的所有任务"""
        with self._lock:
            return [t for t in self._tasks.values() if t.status == status]

    def cleanup(self, max_age_seconds: int = 3600) -> int:
        """清理已完成超过 max_age_seconds 的任务"""
        cutoff = datetime.now().timestamp() - max_age_seconds
        removed = 0
        with self._lock:
            to_remove = []
            for task_id, task in self._tasks.items():
                if task.completed_at and task.completed_at.timestamp() < cutoff:
                    to_remove.append(task_id)
            for task_id in to_remove:
                del self._tasks[task_id]
                removed += 1
        return removed


# 全局单例
_task_store: TaskStore | None = None
_store_lock = threading.RLock()


def get_task_store() -> TaskStore:
    global _task_store
    if _task_store is None:
        with _store_lock:
            if _task_store is None:
                _task_store = TaskStore()
    return _task_store
