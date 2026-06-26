"""
数据同步监控模块

功能：
1. 任务状态追踪（PostgreSQL 表）
2. 失败告警（连续失败 N 次触发）
3. 数据量异常检测
4. 结构化日志输出
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from enum import StrEnum

from sqlalchemy import text

from app.core.database import engine

logger = logging.getLogger(__name__)


class TaskStatus(StrEnum):
    """任务状态"""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    PARTIAL = "partial"  # 部分成功


class AlertLevel(StrEnum):
    """告警级别"""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


# ── 告警规则配置 ──────────────────────────────────────────
ALERT_RULES = {
    "irm": {
        "consecutive_fail_threshold": 3,  # 连续失败 3 次告警
        "fail_rate_threshold": 0.5,  # 失败率超过 50% 告警
        "data_drop_threshold": 0.8,  # 数据量比上次下降 80% 告警
    },
    "reports": {
        "consecutive_fail_threshold": 2,
        "fail_rate_threshold": 0.3,
        "data_drop_threshold": 0.5,
    },
    "kline": {
        "consecutive_fail_threshold": 2,
        "fail_rate_threshold": 0.3,
        "data_drop_threshold": 0.7,
    },
}


# ── 数据库操作 ─────────────────────────────────────────────


async def init_sync_status_table() -> None:
    """确保同步状态表存在"""
    statements = [
        """
        CREATE TABLE IF NOT EXISTS sync_task_status (
            id SERIAL PRIMARY KEY,
            task_name VARCHAR(50) NOT NULL,
            status VARCHAR(20) NOT NULL,
            started_at TIMESTAMP,
            completed_at TIMESTAMP,
            total_items INTEGER DEFAULT 0,
            success_count INTEGER DEFAULT 0,
            skipped_count INTEGER DEFAULT 0,
            fail_count INTEGER DEFAULT 0,
            error_message TEXT,
            consecutive_failures INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT now(),
            updated_at TIMESTAMP DEFAULT now()
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_sync_task_name ON sync_task_status(task_name)",
        "CREATE INDEX IF NOT EXISTS idx_sync_status ON sync_task_status(status)",
    ]
    async with engine.begin() as conn:
        for sql in statements:
            await conn.execute(text(sql))


async def init_alert_log_table() -> None:
    """确保告警日志表存在"""
    statements = [
        """
        CREATE TABLE IF NOT EXISTS sync_alerts (
            id SERIAL PRIMARY KEY,
            task_name VARCHAR(50) NOT NULL,
            alert_level VARCHAR(20) NOT NULL,
            message TEXT NOT NULL,
            details JSONB,
            created_at TIMESTAMP DEFAULT now()
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_alert_task ON sync_alerts(task_name)",
        "CREATE INDEX IF NOT EXISTS idx_alert_level ON sync_alerts(alert_level)",
        "CREATE INDEX IF NOT EXISTS idx_alert_created ON sync_alerts(created_at)",
    ]
    async with engine.begin() as conn:
        for sql in statements:
            await conn.execute(text(sql))


async def record_task_start(task_name: str) -> int:
    """记录任务开始，返回任务 ID"""
    # 先查询上次的连续失败次数
    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT consecutive_failures FROM sync_task_status WHERE task_name = :name ORDER BY id DESC LIMIT 1"),
            {"name": task_name},
        )
        prev_fail = 0
        row = result.fetchone()
        if row:
            prev_fail = row[0] or 0

    sql = """
    INSERT INTO sync_task_status (task_name, status, started_at, consecutive_failures)
    VALUES (:task_name, :status, :started_at, :consecutive_failures)
    RETURNING id
    """
    async with engine.begin() as conn:
        result = await conn.execute(
            text(sql),
            {
                "task_name": task_name,
                "status": TaskStatus.RUNNING.value,
                "started_at": datetime.now(),
                "consecutive_failures": prev_fail,
            },
        )
        row = result.fetchone()
        return row[0] if row else 0


async def record_task_result(
    task_name: str,
    status: TaskStatus,
    total: int = 0,
    success: int = 0,
    skipped: int = 0,
    fail: int = 0,
    error_message: str = "",
) -> None:
    """记录任务结果"""
    now = datetime.now()

    # 获取上次的连续失败次数
    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT consecutive_failures FROM sync_task_status WHERE task_name = :name ORDER BY id DESC LIMIT 1"),
            {"name": task_name},
        )
        prev_fail = 0
        row = result.fetchone()
        if row:
            prev_fail = row[0] or 0

    # 计算新的连续失败次数
    consecutive_failures = (prev_fail + 1) if status == TaskStatus.FAILED else 0

    sql = """
    INSERT INTO sync_task_status (task_name, status, started_at, completed_at,
                                  total_items, success_count, skipped_count, fail_count,
                                  error_message, consecutive_failures)
    VALUES (:task_name, :status, :started_at, :completed_at,
            :total, :success, :skipped, :fail, :error, :consecutive_failures)
    """
    async with engine.begin() as conn:
        await conn.execute(
            text(sql),
            {
                "task_name": task_name,
                "status": status.value,
                "started_at": now,
                "completed_at": now,
                "total": total,
                "success": success,
                "skipped": skipped,
                "fail": fail,
                "error": error_message,
                "consecutive_failures": consecutive_failures,
            },
        )

    # 检查是否需要告警
    await check_and_send_alerts(task_name, status, total, success, fail, consecutive_failures)


async def check_and_send_alerts(
    task_name: str,
    status: TaskStatus,
    total: int,
    success: int,
    fail: int,
    consecutive_failures: int,
) -> None:
    """检查告警规则并发送告警"""
    rules = ALERT_RULES.get(task_name, {})

    alerts_to_send = []

    # 1. 连续失败告警
    threshold = rules.get("consecutive_fail_threshold", 3)
    if consecutive_failures >= threshold:
        alerts_to_send.append(
            {
                "level": AlertLevel.ERROR,
                "message": f"[{task_name}] 连续失败 {consecutive_failures} 次",
                "details": {"consecutive_failures": consecutive_failures},
            }
        )

    # 2. 失败率告警
    if total > 0:
        fail_rate = fail / total
        rate_threshold = rules.get("fail_rate_threshold", 0.5)
        if fail_rate >= rate_threshold:
            alerts_to_send.append(
                {
                    "level": AlertLevel.WARNING,
                    "message": f"[{task_name}] 失败率 {fail_rate:.1%} 超过阈值 {rate_threshold:.1%}",
                    "details": {"total": total, "fail": fail, "fail_rate": fail_rate},
                }
            )

    # 3. 数据量骤降告警（需要对比上次）
    if status in (TaskStatus.SUCCESS, TaskStatus.PARTIAL) and success > 0:
        last_count = await get_last_success_count(task_name)
        if last_count and last_count > 0:
            drop_rate = 1 - (success / last_count)
            drop_threshold = rules.get("data_drop_threshold", 0.8)
            if drop_rate >= drop_threshold:
                alerts_to_send.append(
                    {
                        "level": AlertLevel.WARNING,
                        "message": f"[{task_name}] 数据量下降 {drop_rate:.1%}（{last_count} → {success}）",
                        "details": {
                            "last_count": last_count,
                            "current_count": success,
                            "drop_rate": drop_rate,
                        },
                    }
                )

    # 写入告警日志
    for alert in alerts_to_send:
        await log_alert(task_name, alert["level"], alert["message"], alert.get("details"))
        logger.log(
            logging.WARNING if alert["level"] == AlertLevel.WARNING else logging.ERROR,
            f"[ALERT] {alert['message']}",
        )

        # 发送钉钉通知
        try:
            from app.data_pipeline.dingtalk import notify_alert

            notify_alert(alert["level"], task_name, alert["message"])
        except Exception as e:
            logger.debug("钉钉通知失败: %s", e)


async def get_last_success_count(task_name: str) -> int | None:
    """获取上次成功的数据量"""
    sql = """
    SELECT success_count FROM sync_task_status
    WHERE task_name = :name AND status IN ('success', 'partial')
    ORDER BY id DESC LIMIT 1
    """
    async with engine.connect() as conn:
        result = await conn.execute(text(sql), {"name": task_name})
        row = result.fetchone()
        return row[0] if row else None


async def log_alert(task_name: str, level: AlertLevel, message: str, details: dict = None) -> None:
    """写入告警日志"""
    import json

    sql = """
    INSERT INTO sync_alerts (task_name, alert_level, message, details)
    VALUES (:task_name, :level, :message, :details)
    """
    async with engine.begin() as conn:
        await conn.execute(
            text(sql),
            {
                "task_name": task_name,
                "level": level.value,
                "message": message,
                "details": json.dumps(details) if details else None,
            },
        )


async def get_recent_alerts(hours: int = 24, level: AlertLevel = None) -> list[dict]:
    """获取最近的告警"""
    since = datetime.now() - timedelta(hours=hours)
    sql = """
    SELECT task_name, alert_level, message, details, created_at
    FROM sync_alerts
    WHERE created_at >= :since
    """
    params = {"since": since}
    if level:
        sql += " AND alert_level = :level"
        params["level"] = level.value
    sql += " ORDER BY created_at DESC LIMIT 100"

    async with engine.connect() as conn:
        result = await conn.execute(text(sql), params)
        return [
            {
                "task_name": row[0],
                "level": row[1],
                "message": row[2],
                "details": row[3],
                "created_at": row[4],
            }
            for row in result.fetchall()
        ]


async def get_task_status_summary() -> dict:
    """获取任务状态汇总"""
    sql = """
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
    """
    async with engine.connect() as conn:
        result = await conn.execute(text(sql))
        return {
            row[0]: {
                "status": row[1],
                "last_run": row[2],
                "last_total": row[3],
                "last_success": row[4],
                "consecutive_failures": row[5],
            }
            for row in result.fetchall()
        }


# ── 监视装饰器 ─────────────────────────────────────────────


def monitor_task(task_name: str):
    """监控任务执行的装饰器"""

    def decorator(func):
        async def wrapper(*args, **kwargs):
            await init_sync_status_table()
            await init_alert_log_table()

            logger.info(f"[{task_name}] 任务开始")
            await record_task_start(task_name)

            try:
                result = await func(*args, **kwargs)

                # 解析结果
                if isinstance(result, dict):
                    total = result.get("total", 0)
                    success = result.get("success", 0)
                    skipped = result.get("skipped", 0)
                    fail = result.get("fail", 0)

                    if fail == 0 and skipped == 0:
                        status = TaskStatus.SUCCESS
                    elif success > 0:
                        status = TaskStatus.PARTIAL
                    else:
                        status = TaskStatus.FAILED
                else:
                    total = success = skipped = fail = 0
                    status = TaskStatus.SUCCESS

                await record_task_result(task_name, status, total, success, skipped, fail)
                logger.info(f"[{task_name}] 任务完成: {status.value}, 成功 {success}, 失败 {fail}")

                return result

            except Exception as e:
                await record_task_result(task_name, TaskStatus.FAILED, error_message=str(e))
                logger.error(f"[{task_name}] 任务失败: {e}")
                raise

        return wrapper

    return decorator


# ── 初始化 ─────────────────────────────────────────────────


async def init_monitor() -> None:
    """初始化监控模块"""
    await init_sync_status_table()
    await init_alert_log_table()
    logger.info("监控模块已初始化")
