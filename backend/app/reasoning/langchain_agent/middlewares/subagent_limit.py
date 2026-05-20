"""
SubagentLimitMiddleware V2 — 单轮并发 SubAgent 数量限制

Phase C 实现：追踪 agent.stream() 循环中 task 工具调用次数，
超出 max_concurrent_subagents 限制时：
- 返回 allowed=False 的结果给 agent
- 发射 subagent_limit_exceeded SSE 事件

参考 deer-flow SubagentLimitMiddleware 设计。
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

TOOL_NAME = "task"
DEFAULT_MAX_CONCURRENT = 3


class SubagentLimitMiddleware:
    """
    限制单轮内最大并发 SubAgent task 调用数。

    用法（client.py stream 循环中）：
        subagent_limiter = SubagentLimitMiddleware(max_concurrent=3)
        # 每轮开始：
        subagent_limiter.reset_turn()
        # 每次 tool_call 后：
        result = subagent_limiter.process_tool_call(tool_name, tool_args, emit_fn=emit_fn)
        if not result["allowed"]:
            # 跳过此 task 调用，或返回警告给 agent
    """

    def __init__(self, max_concurrent: int = DEFAULT_MAX_CONCURRENT):
        self.max_concurrent = max_concurrent
        self._count: int = 0

    def reset_turn(self) -> None:
        """重置本轮计数器（新 turn 开始时调用）"""
        self._count = 0

    async def process_tool_call(
        self,
        tool_name: str,
        tool_args: dict,
        emit_fn=None,
    ) -> dict[str, Any]:
        """
        处理一次工具调用。

        Args:
            tool_name: 工具名（如 "task"）
            tool_args: 工具参数
            emit_fn: 可选的 async emit 函数，用于发射 SSE 事件

        Returns:
            {"allowed": bool, "message": str}
            - allowed=True: 正常通过
            - allowed=False: 超出限制，已发射 SSE，结果不可用
        """
        if tool_name != TOOL_NAME:
            return {"allowed": True}

        if self._count >= self.max_concurrent:
            message = (
                f"本轮 SubAgent 并发限制为 {self.max_concurrent} 个，"
                f"当前已达上限，请等待已完成的任务返回后再发起新任务。"
            )
            if emit_fn:
                await emit_fn("subagent_limit_exceeded", {
                    "limit": self.max_concurrent,
                    "message": message,
                    "tool": tool_name,
                })
            return {"allowed": False, "message": message}

        self._count += 1
        return {"allowed": True, "count": self._count, "limit": self.max_concurrent}


async def enforce_subagent_limit(
    tool_name: str,
    tool_args: dict,
    current_count: int,
    max_count: int,
    emit_fn=None,
) -> tuple[bool, int, int]:
    """
    模块级便捷函数。

    Returns:
        (allowed, updated_count, limit)
    """
    if tool_name != TOOL_NAME:
        return True, current_count, max_count

    if current_count >= max_count:
        if emit_fn:
            await emit_fn("subagent_limit_exceeded", {
                "limit": max_count,
                "message": f"SubAgent 并发上限为 {max_count}，已超出。",
                "tool": tool_name,
            })
        return False, current_count, max_count

    return True, current_count + 1, max_count
