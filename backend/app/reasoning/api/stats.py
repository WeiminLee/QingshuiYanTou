"""
Tool 使用量统计 API
"""

import logging

from fastapi import APIRouter, Query

from app.reasoning.middleware.tracking import ToolUsageTracker

logger = logging.getLogger(__name__)
router = APIRouter(tags=["stats"])


@router.get("/tool_usage")
async def get_tool_usage(
    thread_id: str | None = Query(None, description="会话 ID，查询该会话的统计"),
    session_id: str | None = Query(None, description="会话 ID（MongoDB 存储用）"),
    date: str | None = Query(None, description="日期，YYYY-MM-DD 格式，查询历史统计"),
    include_global: bool = Query(False, description="是否包含全局统计"),
) -> dict:
    """
    获取工具使用量统计。

    - 无参数：返回当前会话统计（来自 ToolUsageTracker 内存）
    - 有 thread_id：查询 MongoDB 中该会话的历史统计
    - 有 date：聚合查询该日期的所有会话
    - include_global=True：同时返回全局累计统计
    """
    # 当前会话内存统计
    current = ToolUsageTracker.get_summary()

    result = {
        "current_session": {
            "tool_usage": current,
            "total_calls": sum(current.values()),
        },
    }

    if include_global:
        result["global"] = {
            "tool_usage": ToolUsageTracker.get_global_stats(),
        }

    # 从 MongoDB 查询历史记录
    if thread_id or date:
        try:
            from app.core.mongodb import get_mongodb

            db = await get_mongodb()
            if db:
                collection = db["tool_usage"]
                query: dict = {}
                if thread_id:
                    query["thread_id"] = thread_id
                if date:
                    query["date"] = date

                cursor = collection.find(query).sort("created_at", -1).limit(100)
                records = await cursor.to_list(length=100)

                if records:
                    result["history"] = [
                        {
                            "thread_id": r.get("thread_id"),
                            "date": r.get("date"),
                            "usage": r.get("usage"),
                            "total_calls": r.get("total_calls", 0),
                            "created_at": r.get("created_at", "").isoformat() if r.get("created_at") else None,
                        }
                        for r in records
                    ]
        except Exception as e:
            logger.warning(f"[Stats] MongoDB query failed: {e}")

    return result
