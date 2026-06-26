"""
监控相关 API

包括：
- 股票监控规则管理
- 告警管理
- 数据同步任务状态（新）
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import engine, get_db
from app.models.models import Alert, MonitorRule

router = APIRouter()


@router.get("/rules")
async def get_monitor_rules(ts_code: str | None = None, db: AsyncSession = Depends(get_db)):
    """获取监控规则列表"""
    if ts_code:
        stmt = select(MonitorRule).where(MonitorRule.ts_code == ts_code)
    else:
        stmt = select(MonitorRule)

    result = await db.execute(stmt)
    rules = result.scalars().all()

    return {
        "items": [
            {
                "id": r.id,
                "ts_code": r.ts_code,
                "rule_type": r.rule_type,
                "threshold": r.threshold,
                "enabled": r.enabled,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rules
        ]
    }


@router.post("/rules")
async def create_monitor_rule(ts_code: str, rule_type: str, threshold: float, db: AsyncSession = Depends(get_db)):
    """创建监控规则"""
    # 检查是否已存在相同规则
    stmt = select(MonitorRule).where(
        MonitorRule.ts_code == ts_code,
        MonitorRule.rule_type == rule_type,
    )
    result = await db.execute(stmt)
    existing = result.scalar_one_or_none()

    if existing:
        # 更新阈值
        existing.threshold = threshold
        await db.commit()
        return {"message": "规则已更新", "id": existing.id}

    # 创建新规则
    rule = MonitorRule(
        ts_code=ts_code,
        rule_type=rule_type,
        threshold=threshold,
    )
    db.add(rule)
    await db.commit()

    return {"message": "规则创建成功", "id": rule.id}


@router.delete("/rules/{rule_id}")
async def delete_monitor_rule(rule_id: int, db: AsyncSession = Depends(get_db)):
    """删除监控规则"""
    stmt = select(MonitorRule).where(MonitorRule.id == rule_id)
    result = await db.execute(stmt)
    rule = result.scalar_one_or_none()

    if not rule:
        raise HTTPException(status_code=404, detail="规则不存在")

    await db.delete(rule)
    await db.commit()

    return {"message": "规则已删除"}


@router.get("/alerts")
async def get_alerts(
    ts_code: str | None = None,
    unread_only: bool = False,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    """获取告警列表"""
    conditions = []
    if ts_code:
        conditions.append(Alert.ts_code == ts_code)
    if unread_only:
        conditions.append(not Alert.is_read)

    if conditions:
        stmt = select(Alert).where(*conditions)
    else:
        stmt = select(Alert)

    stmt = stmt.order_by(Alert.triggered_at.desc()).limit(limit)
    result = await db.execute(stmt)
    alerts = result.scalars().all()

    return {
        "items": [
            {
                "id": a.id,
                "ts_code": a.ts_code,
                "rule_type": a.rule_type,
                "message": a.message,
                "triggered_at": a.triggered_at.isoformat() if a.triggered_at else None,
                "is_read": a.is_read,
            }
            for a in alerts
        ]
    }


@router.post("/alerts/{alert_id}/read")
async def mark_alert_read(alert_id: int, db: AsyncSession = Depends(get_db)):
    """标记告警为已读"""
    stmt = select(Alert).where(Alert.id == alert_id)
    result = await db.execute(stmt)
    alert = result.scalar_one_or_none()

    if not alert:
        raise HTTPException(status_code=404, detail="告警不存在")

    alert.is_read = True
    await db.commit()

    return {"message": "已标记为已读"}


@router.get("/alerts/unread-count")
async def get_unread_count(db: AsyncSession = Depends(get_db)):
    """获取未读告警数量"""
    stmt = select(Alert).where(not Alert.is_read)
    result = await db.execute(stmt)
    alerts = result.scalars().all()

    return {"count": len(alerts)}


# ── 数据同步任务监控 API ─────────────────────────────────


@router.get("/sync/jobs/summary")
async def get_ingestion_job_summary():
    async with engine.connect() as conn:
        rows = (
            (
                await conn.execute(
                    text("""
                    SELECT job_type, status, COUNT(*) AS count
                    FROM ingestion_jobs
                    GROUP BY job_type, status
                    ORDER BY job_type, status
                """)
                )
            )
            .mappings()
            .all()
        )
    summary: dict[str, dict[str, int]] = {}
    for row in rows:
        summary.setdefault(row["job_type"], {})[row["status"]] = int(row["count"])
    return summary


@router.get("/sync/jobs/failures")
async def list_ingestion_job_failures(limit: int = 100):
    async with engine.connect() as conn:
        rows = (
            (
                await conn.execute(
                    text("""
                    SELECT id, job_type, job_key, status, attempt_count, max_attempts,
                           next_run_at, last_error, result_summary, updated_at
                    FROM ingestion_jobs
                    WHERE status IN ('failed', 'dead')
                    ORDER BY updated_at DESC
                    LIMIT :limit
                """),
                    {"limit": min(max(limit, 1), 500)},
                )
            )
            .mappings()
            .all()
        )
    return [dict(row) for row in rows]


@router.get("/sync/status")
async def get_sync_status():
    """获取数据同步整体状态"""
    from datetime import datetime

    # 获取任务汇总
    async with engine.connect() as conn:
        result = await conn.execute(
            text("""
            SELECT
                task_name,
                status,
                MAX(started_at) as last_run,
                MAX(total_items) as last_total,
                MAX(success_count) as last_success,
                MAX(consecutive_failures) as consecutive_failures
            FROM sync_task_status
            WHERE started_at >= NOW() - INTERVAL '7 days'
            GROUP BY task_name, status
            ORDER BY task_name, MAX(started_at) DESC
        """)
        )
        rows = result.fetchall()

    summary = {}
    for row in rows:
        name = row[0]
        if name not in summary:  # 只取每个任务最新的状态
            summary[name] = {
                "task_name": name,
                "status": row[1],
                "last_run": row[2].isoformat() if row[2] else None,
                "last_total": row[3],
                "last_success": row[4],
                "consecutive_failures": row[5] or 0,
            }

    # 获取最近告警
    async with engine.connect() as conn:
        result = await conn.execute(
            text("""
            SELECT task_name, alert_level, message, details, created_at
            FROM sync_alerts
            WHERE created_at >= NOW() - INTERVAL '24 hours'
            ORDER BY created_at DESC
            LIMIT 50
        """)
        )
        alert_rows = result.fetchall()

    recent_alerts = [
        {
            "task_name": r[0],
            "level": r[1],
            "message": r[2],
            "details": r[3],
            "created_at": r[4].isoformat() if r[4] else None,
        }
        for r in alert_rows
    ]

    # 限流器状态
    from app.data_pipeline.rate_limiter import get_akshare_limiter

    limiter = get_akshare_limiter()

    return {
        "summary": summary,
        "recent_alerts": recent_alerts,
        "rate_limiter": {
            "max_per_minute": limiter.max_per_minute,
            "window_seconds": limiter.window_seconds,
        },
        "timestamp": datetime.now().isoformat(),
    }


@router.get("/sync/alerts")
async def get_sync_alerts(
    hours: int = Query(24, ge=1, le=168, description="查询最近多少小时的告警"),
    level: str | None = Query(None, description="告警级别: info, warning, error"),
):
    """获取数据同步告警日志"""
    sql = """
    SELECT task_name, alert_level, message, details, created_at
    FROM sync_alerts
    WHERE created_at >= NOW() - INTERVAL ':hours hours'
    """
    params = {"hours": hours}

    if level:
        sql += " AND alert_level = :level"
        params["level"] = level

    sql += " ORDER BY created_at DESC LIMIT 100"

    async with engine.connect() as conn:
        result = await conn.execute(text(sql), params)
        rows = result.fetchall()

    return {
        "total": len(rows),
        "alerts": [
            {
                "task_name": r[0],
                "level": r[1],
                "message": r[2],
                "details": r[3],
                "created_at": r[4].isoformat() if r[4] else None,
            }
            for r in rows
        ],
    }


@router.get("/sync/task/{task_name}")
async def get_sync_task_history(
    task_name: str,
    days: int = Query(7, ge=1, le=30),
):
    """获取特定同步任务的执行历史"""
    async with engine.connect() as conn:
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
            {"task_name": task_name, "days": days},
        )
        rows = result.fetchall()

    return {
        "task_name": task_name,
        "history": [
            {
                "id": r[0],
                "status": r[1],
                "started_at": r[2].isoformat() if r[2] else None,
                "completed_at": r[3].isoformat() if r[3] else None,
                "total": r[4],
                "success": r[5],
                "skipped": r[6],
                "fail": r[7],
                "error": r[8],
                "consecutive_failures": r[9] or 0,
            }
            for r in rows
        ],
    }


# ── 数据接入进度 / checkpoint API ─────────────────────────


@router.get("/ingestion/runs")
async def list_ingestion_runs(
    source: str | None = Query(None, description="数据源，如 cninfo"),
    task_name: str | None = Query(None, description="任务名，如 announcements"),
    scope: str | None = Query(None, description="同步范围，如日期或 ts_code"),
    status: str | None = Query(None, description="running/success/partial/failed"),
    limit: int = Query(50, ge=1, le=200),
):
    """查询数据接入运行记录。"""
    conditions = []
    params: dict[str, object] = {"limit": limit}
    if source:
        conditions.append("source = :source")
        params["source"] = source
    if task_name:
        conditions.append("task_name = :task_name")
        params["task_name"] = task_name
    if scope:
        conditions.append("scope = :scope")
        params["scope"] = scope
    if status:
        conditions.append("status = :status")
        params["status"] = status

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    async with engine.connect() as conn:
        result = await conn.execute(
            text(f"""
                SELECT run_id, source, task_name, scope, status,
                       started_at, updated_at, completed_at,
                       from_watermark, to_watermark, current_watermark,
                       current_page, total_pages, total_items, processed_items,
                       success_count, skipped_count, downloaded_count, fail_count,
                       last_item_id, last_error, metadata
                FROM ingestion_runs
                {where_clause}
                ORDER BY started_at DESC
                LIMIT :limit
            """),
            params,
        )
        rows = result.fetchall()

    return {
        "items": [_format_ingestion_run(r) for r in rows],
        "total": len(rows),
    }


@router.get("/ingestion/runs/{run_id}")
async def get_ingestion_run_detail(
    run_id: str,
    event_limit: int = Query(200, ge=1, le=1000),
):
    """查询单次数据接入运行详情和进度事件。"""
    async with engine.connect() as conn:
        run = (
            await conn.execute(
                text("""
                    SELECT run_id, source, task_name, scope, status,
                           started_at, updated_at, completed_at,
                           from_watermark, to_watermark, current_watermark,
                           current_page, total_pages, total_items, processed_items,
                           success_count, skipped_count, downloaded_count, fail_count,
                           last_item_id, last_error, metadata
                    FROM ingestion_runs
                    WHERE run_id = CAST(:run_id AS uuid)
                """),
                {"run_id": run_id},
            )
        ).first()
        if not run:
            raise HTTPException(status_code=404, detail="运行记录不存在")

        events = (
            await conn.execute(
                text("""
                    SELECT id, stage, message, current_page, total_pages,
                           total_items, processed_items, success_count,
                           skipped_count, downloaded_count, fail_count,
                           item_id, item_title, error, metadata, created_at
                    FROM ingestion_progress_events
                    WHERE run_id = CAST(:run_id AS uuid)
                    ORDER BY created_at ASC, id ASC
                    LIMIT :limit
                """),
                {"run_id": run_id, "limit": event_limit},
            )
        ).fetchall()

    return {
        "run": _format_ingestion_run(run),
        "events": [
            {
                "id": r[0],
                "stage": r[1],
                "message": r[2],
                "current_page": r[3],
                "total_pages": r[4],
                "total_items": r[5],
                "processed_items": r[6],
                "success": r[7],
                "skipped": r[8],
                "downloaded": r[9],
                "fail": r[10],
                "item_id": r[11],
                "item_title": r[12],
                "error": r[13],
                "metadata": r[14],
                "created_at": r[15].isoformat() if r[15] else None,
            }
            for r in events
        ],
    }


@router.get("/ingestion/checkpoints")
async def list_ingestion_checkpoints(
    source: str | None = Query(None, description="数据源，如 cninfo"),
    task_name: str | None = Query(None, description="任务名，如 announcements"),
    scope: str | None = Query(None, description="同步范围，如日期或 ts_code"),
):
    """查询数据接入 checkpoint。"""
    conditions = []
    params: dict[str, object] = {}
    if source:
        conditions.append("source = :source")
        params["source"] = source
    if task_name:
        conditions.append("task_name = :task_name")
        params["task_name"] = task_name
    if scope:
        conditions.append("scope = :scope")
        params["scope"] = scope
    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(f"""
                    SELECT source, task_name, scope, watermark_type,
                           last_success_watermark, last_attempt_watermark,
                           last_run_id, last_status, last_success_at,
                           last_attempt_at, next_from_watermark, metadata,
                           created_at, updated_at
                    FROM ingestion_checkpoints
                    {where_clause}
                    ORDER BY updated_at DESC
                """),
                params,
            )
        ).fetchall()

    return {
        "items": [
            {
                "source": r[0],
                "task_name": r[1],
                "scope": r[2],
                "watermark_type": r[3],
                "last_success_watermark": r[4],
                "last_attempt_watermark": r[5],
                "last_run_id": str(r[6]) if r[6] else None,
                "last_status": r[7],
                "last_success_at": r[8].isoformat() if r[8] else None,
                "last_attempt_at": r[9].isoformat() if r[9] else None,
                "next_from_watermark": r[10],
                "metadata": r[11],
                "created_at": r[12].isoformat() if r[12] else None,
                "updated_at": r[13].isoformat() if r[13] else None,
            }
            for r in rows
        ],
        "total": len(rows),
    }


def _format_ingestion_run(row) -> dict:
    return {
        "run_id": str(row[0]),
        "source": row[1],
        "task_name": row[2],
        "scope": row[3],
        "status": row[4],
        "started_at": row[5].isoformat() if row[5] else None,
        "updated_at": row[6].isoformat() if row[6] else None,
        "completed_at": row[7].isoformat() if row[7] else None,
        "from_watermark": row[8],
        "to_watermark": row[9],
        "current_watermark": row[10],
        "current_page": row[11],
        "total_pages": row[12],
        "total_items": row[13],
        "processed_items": row[14],
        "success": row[15],
        "skipped": row[16],
        "downloaded": row[17],
        "fail": row[18],
        "last_item_id": row[19],
        "last_error": row[20],
        "metadata": row[21],
    }
