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


def _memory_args(
    *,
    action: str,
    target: str,
    content: str = "",
    old_text: str | None = None,
    subject: str | None = None,
    stance: str | None = None,
    subject_type: str | None = None,
    reason: str | None = None,
) -> dict:
    return {
        "action": action,
        "target": target,
        "content": content,
        "old_text": old_text,
        "subject": subject,
        "stance": stance,
        "subject_type": subject_type,
        "reason": reason,
    }


def create_manage_memory_tool(memory_manager: object):
    """Create a run-scoped memory tool bound to one MemoryManager instance."""

    @tool("manage_memory", return_direct=False)
    async def _run_scoped_manage_memory(
        action: Annotated[str, "操作类型: add / replace / remove"],
        target: Annotated[str, "目标: notes / profile / preference"],
        content: Annotated[str, "notes/profile 的内容文本"] = "",
        old_text: Annotated[str | None, "notes replace/remove 时定位旧文本"] = None,
        subject: Annotated[str | None, "preference 的板块/概念/个股名"] = None,
        stance: Annotated[str | None, "preference 立场: 看好/看空/关注/回避"] = None,
        subject_type: Annotated[str | None, "preference 类型: sector/concept/stock"] = None,
        reason: Annotated[str | None, "preference 依据，可选"] = None,
    ) -> str:
        """管理用户长期记忆。写入后继续完成用户原始分析任务。"""
        return await memory_manager.handle_tool_call(
            "manage_memory",
            _memory_args(
                action=action,
                target=target,
                content=content,
                old_text=old_text,
                subject=subject,
                stance=stance,
                subject_type=subject_type,
                reason=reason,
            ),
        )

    return _run_scoped_manage_memory


@tool("manage_memory", return_direct=False)
async def manage_memory(
    action: Annotated[str, "操作类型: add / replace / remove"],
    target: Annotated[str, "目标: notes / profile / preference"],
    content: Annotated[str, "notes/profile 的内容文本"] = "",
    old_text: Annotated[str | None, "notes replace/remove 时定位旧文本"] = None,
    subject: Annotated[str | None, "preference 的板块/概念/个股名"] = None,
    stance: Annotated[str | None, "preference 立场: 看好/看空/关注/回避"] = None,
    subject_type: Annotated[str | None, "preference 类型: sector/concept/stock"] = None,
    reason: Annotated[str | None, "preference 依据，可选"] = None,
) -> str:
    """管理用户长期记忆。

    - preference：用户对某板块/概念/个股表达看好/看空/关注/回避时，记录 subject+stance。
    - profile：用户长期投资风格/风险偏好。
    - notes：其他值得记住的信息。
    内容需简洁（≤200字）。
    """
    mgr = get_memory_manager()
    if mgr is None:
        return "Error: 记忆系统未初始化"
    return await mgr.handle_tool_call(
        "manage_memory",
        _memory_args(
            action=action,
            target=target,
            content=content,
            old_text=old_text,
            subject=subject,
            stance=stance,
            subject_type=subject_type,
            reason=reason,
        ),
    )
