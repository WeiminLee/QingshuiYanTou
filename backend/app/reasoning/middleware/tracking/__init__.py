"""
ToolUsageTracker — 工具使用量追踪

使用 contextvars 存储每个会话的 tool 调用统计，
参考 LangAlpha src/tools/decorators.py 的设计。
"""
from __future__ import annotations

import contextvars
import logging
import threading
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.mongodb import AsyncMongoDB

logger = logging.getLogger(__name__)

# 上下文变量：每个协程/线程独立统计
_tool_usage_ctx: contextvars.ContextVar[dict[str, int]] = contextvars.ContextVar(
    "tool_usage"
)

# 内存中汇总（跨会话，用于 API 查询）
_global_stats: dict[str, int] = {}
_global_lock = threading.RLock()


class ToolUsageTracker:
    """
    Tool 使用量追踪器。

    使用 contextvars 确保每个会话的统计隔离，
    支持嵌套调用（subagent 等）。
    """

    @staticmethod
    def record_usage(tool_name: str, count: int = 1) -> None:
        """记录一次 tool 调用"""
        try:
            ctx = dict(_tool_usage_ctx.get())
        except LookupError:
            ctx = {}
        ctx[tool_name] = ctx.get(tool_name, 0) + count
        _tool_usage_ctx.set(ctx)

        with _global_lock:
            _global_stats[tool_name] = _global_stats.get(tool_name, 0) + count

    @staticmethod
    def get_summary() -> dict[str, int]:
        """获取当前会话的调用统计"""
        try:
            return dict(_tool_usage_ctx.get())
        except LookupError:
            return {}

    @staticmethod
    def get_total_calls() -> int:
        """获取当前会话总调用次数"""
        try:
            return sum(_tool_usage_ctx.get().values())
        except LookupError:
            return 0

    @staticmethod
    def reset() -> None:
        """重置当前会话统计"""
        try:
            _tool_usage_ctx.set({})
        except LookupError:
            pass

    @staticmethod
    def get_global_stats() -> dict[str, int]:
        """获取全局（所有会话累计）统计"""
        with _global_lock:
            return dict(_global_stats)

    @staticmethod
    def reset_global() -> None:
        """清零全局统计"""
        with _global_lock:
            _global_stats.clear()

    @staticmethod
    async def persist(
        thread_id: str,
        session_id: str | None = None,
    ) -> None:
        """
        将当前会话统计持久化到 MongoDB（tool_usage collection）。
        失败时降级到内存，不阻断主流程。
        """
        summary = ToolUsageTracker.get_summary()
        if not summary:
            return

        try:
            from app.core.mongodb import get_mongodb
            db = await get_mongodb()
            if db is None:
                return
            collection = db["tool_usage"]
            await collection.insert_one({
                "thread_id": thread_id,
                "session_id": session_id,
                "usage": summary,
                "total_calls": sum(summary.values()),
                "date": datetime.now().date().isoformat(),
                "created_at": datetime.now(),
            })
            logger.debug(f"[ToolUsage] Persisted: {summary}")
        except Exception as e:
            logger.warning(f"[ToolUsage] Persist to MongoDB failed: {e}")
