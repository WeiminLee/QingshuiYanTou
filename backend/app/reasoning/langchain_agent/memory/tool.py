"""manage_memory tool — LLM-facing interface for memory operations."""

from __future__ import annotations

import logging
from typing import Annotated

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

# Global reference — set by MemoryManager during initialization
_memory_manager: object | None = None


def set_memory_manager(mgr: object) -> None:
    global _memory_manager
    _memory_manager = mgr


def get_memory_manager():
    return _memory_manager


@tool("manage_memory", return_direct=True)
async def manage_memory(
    action: Annotated[str, "操作类型: add（新增）/ replace（替换）/ remove（删除）"],
    target: Annotated[str, "目标: notes（笔记）/ profile（用户画像）"],
    content: Annotated[str, "内容文本"],
    old_text: Annotated[str | None, "replace/remove 时需要匹配的旧文本，用于定位要替换或删除的条目"] = None,
) -> str:
    """管理持久记忆：记录笔记或更新用户画像。

    笔记（notes）用于记录分析中发现的用户偏好、关注方向、重要观点。
    用户画像（profile）用于记录用户的投资风格、风险偏好等长期属性。

    【重要】内容必须简洁清晰，不超过200字。
    使用场景：
    - 用户说「我主要关注科技股」→ add to profile
    - 用户说「帮我看看中际旭创」→ add to notes: "用户关注中际旭创"
    - 用户的偏好发生变化 → replace old note with new content
    - 某个关注点不再重要 → remove the note
    """
    mgr = get_memory_manager()
    if mgr is None:
        return "Error: 记忆系统未初始化"

    result = await mgr.handle_tool_call("manage_memory", {
        "action": action,
        "target": target,
        "content": content,
        "old_text": old_text,
    })
    return result
