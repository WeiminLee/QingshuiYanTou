"""
数据同步监控 API

提供任务状态、告警日志、数据量统计等接口
"""
from fastapi import APIRouter, Query
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

from app.data_pipeline.monitor import (
    get_task_status_summary,
    get_recent_alerts,
    AlertLevel,
)

router = APIRouter(prefix="/api/v1/monitor", tags=["监控"])


class TaskStatusResponse(BaseModel):
    task_name: str
    status: str
    last_run: Optional[datetime]
    last_total: Optional[int]
    last_success: Optional[int]
    consecutive_failures: int


class AlertResponse(BaseModel):
    task_name: str
    level: str
    message: str
    details: Optional[dict]
    created_at: datetime


class SyncStatsResponse(BaseModel):
    summary: dict[str, TaskStatusResponse]
    recent_alerts: list[AlertResponse]
    rate_limiter_status: dict


@router.get("/status", response_model=SyncStatsResponse)
async def get_sync_status():
    """获取数据同步整体状态"""
    # 获取任务汇总
    summary_raw = await get_task_status_summary()
    summary = {
        name: TaskStatusResponse(
            task_name=name,
            status=info.get("status", "unknown"),
            last_run=info.get("last_run"),
            last_total=info.get("last_total"),
            last_success=info.get("last_success"),
            consecutive_failures=info.get("consecutive_failures", 0),
        )
        for name, info in summary_raw.items()
    }

    # 获取最近告警
    alerts_raw = await get_recent_alerts(hours=24)
    recent_alerts = [
        AlertResponse(
            task_name=a["task_name"],
            level=a["level"],
            message=a["message"],
            details=a["details"],
            created_at=a["created_at"],
        )
        for a in alerts_raw
    ]

    # 限流器状态
    from app.data_pipeline.rate_limiter import get_akshare_limiter
    limiter = get_akshare_limiter()
    rate_limiter_status = {
        "requests_per_minute": limiter.max_per_minute,
        "current_count": limiter.count,
        "reset_at": limiter._window_start.isoformat() if hasattr(limiter, '_window_start') else None,
    }

    return SyncStatsResponse(
        summary=summary,
        recent_alerts=recent_alerts,
        rate_limiter_status=rate_limiter_status,
    )


@router.get("/alerts")
async def list_alerts(
    hours: int = Query(24, ge=1, le=168, description="查询最近多少小时的告警"),
    level: Optional[str] = Query(None, description="告警级别: info, warning, error"),
):
    """获取告警日志"""
    alert_level = AlertLevel(level) if level else None
    alerts = await get_recent_alerts(hours=hours, level=alert_level)
    return {
        "total": len(alerts),
        "alerts": alerts,
    }


@router.get("/task/{task_name}")
async def get_task_detail(
    task_name: str,
    days: int = Query(7, ge=1, le=30),
):
    """获取特定任务的详细执行历史"""
    from sqlalchemy import text

    async with (await import('app.core.database')).engine.connect() as conn:
        result = await conn.execute(
            text("""
                SELECT id, status, started_at, completed_at,
                       total_items, success_count, skipped_count, fail_count,
                       error_message, consecutive_failures
                FROM sync_task_status
                WHERE task_name = :task_name
                  AND started_at >= NOW() - INTERVAL ':days days'
                ORDER BY started_at DESC
                LIMIT 50
            """),
            {"task_name": task_name, "days": days}
        )
        rows = result.fetchall()

    return {
        "task_name": task_name,
        "history": [
            {
                "id": r[0],
                "status": r[1],
                "started_at": r[2],
                "completed_at": r[3],
                "total": r[4],
                "success": r[5],
                "skipped": r[6],
                "fail": r[7],
                "error": r[8],
                "consecutive_failures": r[9],
            }
            for r in rows
        ]
    }
