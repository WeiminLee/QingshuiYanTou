"""
write_todos — 待办列表工具（DeerFlow plan mode）

参考 DeerFlow langchain/agents/middleware/todo.py：
- 模型通过 write_todos 工具更新待办列表状态
- 状态变更通过 SSE todo_update 事件推送给前端

数据结构（与 DeerFlow 一致）：
    content: str          任务描述
    status: pending | in_progress | completed
"""

from __future__ import annotations

import logging
from typing import Annotated, Literal

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

# ── 类型定义 ──────────────────────────────────────────────────────────

TodoStatus = Literal["pending", "in_progress", "completed"]

TodoItem = dict | None  # None 表示清空列表


# ── 工具 ─────────────────────────────────────────────────────────────


@tool("write_todos")
def write_todos(
    todos: Annotated[
        list[dict],
        (
            "待办列表，每项包含：\n"
            "  content: str — 任务描述\n"
            "  status: 'pending' | 'in_progress' | 'completed'\n"
            "空列表 [] 表示清空所有待办项"
        ),
    ],
) -> str:
    """
    更新待办列表状态。模型在执行过程中调用此工具记录进度。

    用法示例：
    - 初始化：write_todos([{"content": "搜索相关信息", "status": "pending"}])
    - 开始执行：write_todos([{"content": "搜索相关信息", "status": "in_progress"}])
    - 完成：write_todos([{"content": "搜索相关信息", "status": "completed"}])
    - 全部清空：write_todos([])
    """
    if not todos:
        logger.info("[write_todos] 清空待办列表")
        return "待办列表已清空。"

    lines = []
    for i, item in enumerate(todos, 1):
        status = item.get("status", "pending")
        content = item.get("content", "")
        status_icon = {"pending": "○", "in_progress": "●", "completed": "✓"}[status]
        lines.append(f"{i}. {status_icon} [{status}] {content}")

    summary = "\n".join(lines)
    logger.info(f"[write_todos] 更新 {len(todos)} 项待办：{summary[:100]}")
    return f"待办列表已更新（共 {len(todos)} 项）：\n{summary}"
