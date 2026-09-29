"""
TodoListMiddleware — 待办列表状态管理（DeerFlow plan mode）

参考 DeerFlow agents/middlewares/todo_middleware.py：
- 追踪 write_todos 工具调用后的列表状态
- 通过 SSE todo_update 事件推送给前端
- per-thread 隔离

SSE 事件格式：
    type: "todo_update"
    data: {
        "todos": [
            {"content": "搜索相关信息", "status": "in_progress"},
            ...
        ]
    }
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Literal

logger = logging.getLogger(__name__)

TodoStatus = Literal["pending", "in_progress", "completed"]
TodoItem = dict  # {"content": str, "status": TodoStatus}


class TodoListMiddleware:
    """
    管理待办列表状态，提供 SSE 推送接口。

    用法（create_agent middleware）：
        todos_mw = TodoListMiddleware()
        # 每次工具执行后检查
        todos_mw.on_tool_result("write_todos", tool_result_str, emit_fn)
    """

    def __init__(self, max_tracked_threads: int = 100):
        self._lock = threading.Lock()
        # thread_id -> list[TodoItem]
        self._states: dict[str, list[TodoItem]] = {}
        self._max_tracked = max_tracked_threads

    def _get_todos(self, thread_id: str) -> list[TodoItem]:
        with self._lock:
            if thread_id not in self._states:
                self._states[thread_id] = []
            # 驱逐过多线程
            if len(self._states) > self._max_tracked:
                oldest = next(iter(self._states))
                self._states.pop(oldest, None)
            return self._states[thread_id]

    def _set_todos(self, thread_id: str, todos: list[TodoItem]) -> None:
        with self._lock:
            self._states[thread_id] = list(todos)

    def parse_todos_from_result(self, result_str: str) -> list[TodoItem] | None:
        """
        从 write_todos 工具返回字符串中解析 todo 列表。

        返回 None 表示不是 write_todos 调用或解析失败。
        """
        if "待办列表已更新" not in result_str and "待办列表已清空" not in result_str:
            return None

        if "已清空" in result_str:
            return []

        todos: list[TodoItem] = []
        for line in result_str.split("\n"):
            line = line.strip()
            if not line or line.startswith("待办列表"):
                continue
            # 格式: "1. ○ [pending] 搜索相关信息"
            # 或 "2. ✓ [completed] ..."
            import re

            m = re.match(r"^\d+\.\s*[○●✓]\s*\[(\w+)\]\s*(.+)$", line)
            if m:
                status = m.group(1).strip()
                content = m.group(2).strip()
                todos.append({"content": content, "status": status})
        return todos if todos else None

    def on_tool_result(
        self,
        tool_name: str,
        result_str: str,
        thread_id: str,
        emit_fn: Callable | None,
    ) -> None:
        """
        工具执行完成后调用，更新 todo 状态并推送 SSE。

        Args:
            tool_name: 工具名称
            result_str: 工具返回字符串
            thread_id: 会话 ID（用于 per-thread 隔离）
            emit_fn: SSE 推送函数
        """
        if tool_name != "write_todos":
            return

        todos = self.parse_todos_from_result(result_str)
        if todos is None:
            return

        self._set_todos(thread_id, todos)

        if emit_fn:
            import asyncio

            try:
                asyncio.get_running_loop()
                asyncio.create_task(emit_fn("todo_update", {"todos": todos}))
            except RuntimeError:
                pass  # 无 running loop，同步上下文

        logger.info(f"[TodoList] 更新 {len(todos)} 项，thread={thread_id}")

    def get_todos(self, thread_id: str) -> list[TodoItem]:
        """获取当前待办列表（用于前端初始状态）"""
        return list(self._get_todos(thread_id))

    def reset(self, thread_id: str | None = None) -> None:
        """清理追踪状态"""
        with self._lock:
            if thread_id:
                self._states.pop(thread_id, None)
            else:
                self._states.clear()
