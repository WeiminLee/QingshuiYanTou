"""Producers that enqueue ingestion jobs without doing external IO."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

import pytz
from sqlalchemy import text

from app.core.database import engine
from app.data_pipeline.job_queue import (
    JOB_CNINFO_ANNOUNCEMENT_DATE,
    JOB_IRM_COMPANY,
    IngestionJobQueue,
)

logger = logging.getLogger(__name__)


SH_TZ = pytz.timezone("Asia/Shanghai")


def _is_company_ts_code(ts_code: str) -> bool:
    if not ts_code or "." not in ts_code:
        return False
    code, exchange = ts_code.split(".", 1)
    if len(code) != 6 or not code.isdigit():
        return False
    if exchange == "SH" and code.startswith("000"):
        return False
    if exchange == "SZ" and code.startswith("399"):
        return False
    return exchange in {"SH", "SZ", "BJ"}


def _ensure_shanghai_datetime(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(SH_TZ)
    if now.tzinfo is None:
        return SH_TZ.localize(now)
    return now.astimezone(SH_TZ)


async def enqueue_recent_cninfo_jobs(
    queue: IngestionJobQueue | None = None,
    days: int = 7,
    now: datetime | None = None,
) -> dict[str, int]:
    queue = queue or IngestionJobQueue()
    current = _ensure_shanghai_datetime(now)
    start_date = current.date() - timedelta(days=max(days, 0) - 1) if days > 0 else current.date()

    count = 0
    for offset in range(max(days, 0)):
        day = start_date + timedelta(days=offset)
        date_key = day.strftime("%Y%m%d")
        await queue.enqueue_job(
            job_type=JOB_CNINFO_ANNOUNCEMENT_DATE,
            job_key=date_key,
            payload={"date": date_key},
            priority=10 + offset,
            max_attempts=8,
        )
        count += 1
    return {"enqueued": count}


async def _list_stock_ts_codes() -> list[str]:
    """从 candidate_pool 读取活跃 target pool 股票（半导体/光模块/AI算力等主题池）。"""
    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT ts_code FROM candidate_pool WHERE is_active = true ORDER BY ts_code"))
        return [row[0] for row in result.fetchall()]


async def enqueue_irm_company_jobs(
    queue: IngestionJobQueue | None = None,
    stock_codes: list[str] | None = None,
    refresh_all: bool = True,
) -> dict[str, int]:
    queue = queue or IngestionJobQueue()
    # 股票列表从 stocks 表读取（tinyshare 写入），不再依赖 baostock get_stocks_basic
    codes = list(stock_codes) if stock_codes is not None else await _list_stock_ts_codes()

    # 白名单过滤：scope=tech_mvp 时仅入队白名单股票
    from app.data_pipeline.backfill_config import load_backfill_settings, require_non_empty_scope

    bf_cfg = load_backfill_settings()
    require_non_empty_scope(bf_cfg)
    if bf_cfg.scope == "tech_mvp" and bf_cfg.ts_codes:
        before = len(codes)
        codes = [c for c in codes if str(c) in bf_cfg.ts_codes]
        logger.info(
            "enqueue_irm_company_jobs: backfill scope=tech_mvp, %d/%d 命中白名单",
            len(codes),
            before,
        )

    count = 0
    for raw_code in codes:
        ts_code = str(raw_code or "").strip()
        if not _is_company_ts_code(ts_code):
            continue
        await queue.enqueue_job(
            job_type=JOB_IRM_COMPANY,
            job_key=ts_code,
            payload={"ts_code": ts_code, "refresh_all": refresh_all},
            priority=50,
            max_attempts=5,
            force_requeue=True,
        )
        count += 1
    return {"enqueued": count}
