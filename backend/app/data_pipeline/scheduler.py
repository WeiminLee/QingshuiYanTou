"""
Scheduler - 定时任务调度器（APScheduler 版）

负责协调本地数据采集：研报 / K线 / 互动易 / 概念 / 股票同步。
- 数据采集 fetcher 全部是 async，本调度器使用 AsyncIOScheduler。
- 时间统一为 Asia/Shanghai；任务以 cron 风格触发。
- 失败重试通过 tenacity 风格的简易退避在任务内做（每个任务 1 次重试足够，避免错过下一个窗口）。
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Awaitable, Callable
from datetime import date, datetime, time, timedelta
from typing import Any

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import text

from app.config import settings
from app.core.database import engine
from app.data_pipeline.job_producers import enqueue_irm_company_jobs, enqueue_recent_cninfo_jobs
from app.data_pipeline.job_worker import IngestionJobWorker

logger = logging.getLogger(__name__)


TIMEZONE = "Asia/Shanghai"

# ── Phase 31 H: 交易时段判断（concept_hourly guard） ──────
TRADING_TZ = pytz.timezone("Asia/Shanghai")
TRADING_HOURS = [(time(9, 0), time(11, 30)), (time(13, 0), time(15, 0))]


def _is_trading_hours() -> bool:
    """判断当前是否在 A 股交易时段（工作日 9:00-11:30 或 13:00-15:00）。

    注意：未处理法定节假日（春节/国庆等），P0 仅防周末/夜间空跑。
    未来如需节假日准确度可引入 akshare.tool_trade_date_hist_sina() 缓存。
    """
    now = datetime.now(TRADING_TZ)
    if now.weekday() >= 5:  # 周六周日
        return False
    t = now.time()
    return any(start <= t <= end for start, end in TRADING_HOURS)


def _is_extraction_window() -> bool:
    """判断当前是否在抽取窗口。

    - 工作日：22:00 ~ 次日 08:00（避开 pjlab 白天高负载）
    - 周末（周六/周日）：全天可抽取
    """
    now = datetime.now(TRADING_TZ)
    if now.weekday() >= 5:  # 周六(5) / 周日(6)
        return True
    t = now.time()
    return t >= time(22, 0) or t < time(8, 0)


def _last_expected_trade_date(now: datetime | None = None) -> date:
    """返回按周末规则计算的最近一个已结束交易日。"""
    current = now or datetime.now(TRADING_TZ)
    candidate = current.date() - timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate -= timedelta(days=1)
    return candidate


async def _kline_catchup_needed() -> bool:
    """判断数据库是否落后于最近一个工作日，供服务启动补漏使用。"""
    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT MAX(trade_date) FROM daily_data"))
        latest = result.scalar()
    if latest is None:
        return True
    if isinstance(latest, str):
        latest = date.fromisoformat(latest)
    return latest < _last_expected_trade_date()


REPORT_FETCH_HOUR = 3
KLINE_FETCH_HOUR = 17
KLINE_FETCH_MINUTE = 30
CONCEPT_FETCH_MINUTE = 0
# 收盘后 concept 补写：A 股涨停列表（tinyshare limit_list_d）当日数据收盘后才发布，
# concept_hourly 交易时段内（最晚 15:00 整点）与发布时序冲突，系统性漏写当日数据。
# 2026-10-15 实测：17:44 未发布、18:04 已发布（≈18:00），故首跑默认 18:30；
# env 可覆盖首跑时刻（CONCEPT_EOD_HOUR/MINUTE）。
CONCEPT_EOD_HOUR_ENV = "CONCEPT_EOD_HOUR"
CONCEPT_EOD_MINUTE_ENV = "CONCEPT_EOD_MINUTE"
CONCEPT_EOD_DEFAULT_HOUR = 18
CONCEPT_EOD_DEFAULT_MINUTE = 30
# 0 行重试档位（HH:MM 逗号分隔；每档先查当日是否已入库，命中即停且不再请求数据源）
CONCEPT_EOD_RETRIES_ENV = "CONCEPT_EOD_RETRIES"
CONCEPT_EOD_DEFAULT_RETRIES = "19:30,20:30,21:30"
# 次日补昨日时刻（条件执行：昨日数据缺失才拉取，避免每日无条件请求数据源引发授权码竞态）
CONCEPT_EOD_CATCHUP_ENV = "CONCEPT_EOD_CATCHUP_TIME"
CONCEPT_EOD_DEFAULT_CATCHUP = "09:15"
IRM_HOUR = 22
SYNC_STOCKS_WEEKDAY = "mon"
SYNC_STOCKS_HOUR = 7

# Phase 03 plan 03-03 / D-05：巨潮公告每日 23:00 收盘后抓取
CNINFO_FETCH_HOUR = 23
PDF_ROTATION_WEEKDAY = "sun"
PDF_ROTATION_HOUR = 2

NEWS_FETCH_MINUTE = "*/5"  # 每 5 分钟
NEWS_FETCH_HISTORY_DAYS = 7  # 首次全量拉取历史天数


MAX_ATTEMPTS = 3  # Phase 31 E 修复：总执行次数（= 1 原始 + 2 次重试）
RETRY_BASE_DELAY = 30  # 秒
# IRM 每晚 force_requeue ~1.6k 家；5×12×24=1440/天清不完会堆 pending。
# 20≈5760/天，约数小时吃完当晚批次；ingestion 是外部采集，不入 GPU。
INGESTION_WORKER_DRAIN_LIMIT = 20
INGESTION_WORKER_TIMEOUT_SECONDS = 300
# PDF 下载 drain：专用 worker（通用 ingestion worker 不处理 pdf_download，
# 见 job_handlers.SUPPORTED_INGESTION_JOB_TYPES）。每轮上限小、周期短，
# 下载耗时通过 request_timeout 约束，避免长占调度线程。
PDF_DOWNLOAD_DRAIN_LIMIT = 5
PDF_DOWNLOAD_REQUEST_TIMEOUT_SECONDS = 90
ENABLE_EVIDENCE_SCHEDULER_ENV = "ENABLE_EVIDENCE_SCHEDULER"


def _evidence_scheduler_enabled() -> bool:
    value = os.getenv(ENABLE_EVIDENCE_SCHEDULER_ENV, "false").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _concept_eod_time() -> tuple[int, int]:
    """收盘后 concept 补写首跑时刻（Asia/Shanghai），env 可配，默认 18:30。"""
    hour = int(os.getenv(CONCEPT_EOD_HOUR_ENV, str(CONCEPT_EOD_DEFAULT_HOUR)))
    minute = int(os.getenv(CONCEPT_EOD_MINUTE_ENV, str(CONCEPT_EOD_DEFAULT_MINUTE)))
    return hour, minute


def _concept_eod_retries() -> list[tuple[int, int]]:
    """0 行重试档位（HH:MM 逗号分隔，默认 19:30,20:30,21:30），env 可配。"""
    raw = os.getenv(CONCEPT_EOD_RETRIES_ENV, CONCEPT_EOD_DEFAULT_RETRIES)
    slots: list[tuple[int, int]] = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        hour_s, minute_s = token.split(":")
        slots.append((int(hour_s), int(minute_s)))
    return slots


def _concept_eod_catchup_time() -> tuple[int, int]:
    """次日补昨日时刻（Asia/Shanghai），env 可配，默认 09:15。"""
    raw = os.getenv(CONCEPT_EOD_CATCHUP_ENV, CONCEPT_EOD_DEFAULT_CATCHUP)
    hour_s, minute_s = raw.strip().split(":")
    return int(hour_s), int(minute_s)


async def _concept_limit_has_date(d: date) -> bool:
    """concept_limit 是否已有指定交易日数据（重试命中即停 / 次日回补条件判定）。"""
    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT 1 FROM concept_limit WHERE trade_date = :d LIMIT 1"),
            {"d": d},
        )
        return result.scalar_one_or_none() is not None


def latest_weekday_without_kline(
    today: date,
    dates_with_kline: set[date],
    *,
    include_today: bool,
    lookback_days: int = 4,
) -> date | None:
    """近窗里最晚一个没有日线的工作日。

    窗口内完全没有日线（长假）返回 None，避免把休市叫成故障。
    窗口内已有行情、却缺某个工作日时返回该日：这是 K 线失败被当成休市的口子。
    """
    end = today if include_today else today - timedelta(days=1)
    start = today - timedelta(days=lookback_days)
    if end < start:
        return None
    window: list[date] = []
    cursor = start
    while cursor <= end:
        window.append(cursor)
        cursor += timedelta(days=1)
    if not any(day in dates_with_kline for day in window):
        return None
    missing = [day for day in window if day.weekday() < 5 and day not in dates_with_kline]
    if not missing:
        return None
    return max(missing)


async def _recent_kline_dates(today: date, lookback_days: int) -> set[date]:
    start = today - timedelta(days=lookback_days)
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                """
                SELECT DISTINCT trade_date
                FROM daily_data
                WHERE trade_date >= :start AND trade_date <= :today
                """
            ),
            {"start": start, "today": today},
        )
        found: set[date] = set()
        for row in result:
            value = row[0]
            if isinstance(value, datetime):
                value = value.date()
            if isinstance(value, date):
                found.add(value)
        return found


async def _weekday_kline_gap(today: date, *, include_today: bool) -> date | None:
    dates = await _recent_kline_dates(today, 4)
    return latest_weekday_without_kline(
        today,
        dates,
        include_today=include_today,
        lookback_days=4,
    )


async def _alert_concept_kline_gap(gap: date, task_name: str) -> None:
    """工作日无日线时记失败。单日休市也会响一次，消息里写明可以忽略。"""
    from app.data_pipeline.dingtalk import notify_task_failed
    from app.data_pipeline.monitor import (
        TaskStatus,
        init_monitor,
        record_task_result,
        record_task_start,
    )

    message = (
        f"工作日 {gap.isoformat()} 无日线，概念作业已跳过。"
        "若当天休市可忽略；若是交易日，则是 K 线失败导致概念数据缺失。"
    )
    logger.error("[concept_eod] %s", message)
    await init_monitor()
    run_id = await record_task_start(task_name)
    await record_task_result(
        task_name,
        TaskStatus.FAILED,
        error_message=message,
        **_run_id_kwarg(run_id),
    )
    await notify_task_failed("概念热度", message)


async def _is_trading_day_by_daily_data(d: date) -> bool:
    """以 daily_data 作交易日历：当日有日线行即视为交易日。

    当日 kline 作业 17:30 先入库，18:30 EOD 首跑时可用（2026-10-15 实测 18:17
    已含当日）；周末/法定节假日无日线行 → 天然排除，避免非交易日空跑与误告警。
    """
    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT 1 FROM daily_data WHERE trade_date = :d LIMIT 1"),
            {"d": d},
        )
        return result.scalar_one_or_none() is not None


async def _concept_eod_missing_trade_date(lookback_days: int = 10) -> date | None:
    """最近缺少概念数据的交易日（daily_data 有、concept_limit 无），供次日条件补漏。

    用 daily_data 作交易日历时，周末/节假日天然不在候选集；只对「确认缺数据的真实
    交易日」发 fetch_concept 请求——没数据才去要数据。
    """
    from_d = datetime.now(TRADING_TZ).date() - timedelta(days=lookback_days)
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                """
                SELECT d.trade_date
                FROM daily_data d
                WHERE d.trade_date >= :from
                  AND NOT EXISTS (
                      SELECT 1 FROM concept_limit c WHERE c.trade_date = d.trade_date
                  )
                ORDER BY d.trade_date DESC
                LIMIT 1
                """
            ),
            {"from": from_d},
        )
        row = result.fetchone()
    return row[0] if row else None


def _run_id_kwarg(run_id: object) -> dict[str, int]:
    return {"run_id": run_id} if isinstance(run_id, int) else {}


async def _run_with_retry(
    coro_factory: Callable[[], Awaitable[object]],
    task_name: str,
) -> bool:
    """带指数退避的协程执行器。最多 MAX_ATTEMPTS 次，每次重新构造协程。"""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            result = await coro_factory()
            logger.info("[%s] 执行成功: %s", task_name, result)
            return True
        except Exception as exc:
            if attempt < MAX_ATTEMPTS:
                delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))
                logger.warning(
                    "[%s] 第 %d/%d 次失败: %s，%ds 后重试",
                    task_name,
                    attempt,
                    MAX_ATTEMPTS,
                    exc,
                    delay,
                )
                await asyncio.sleep(delay)
            else:
                logger.error(
                    "[%s] %d 次尝试全部失败: %s",
                    task_name,
                    MAX_ATTEMPTS,
                    exc,
                )
    return False


async def _run_report_job() -> None:
    from app.data_pipeline.dingtalk import (
        notify_task_failed,
        notify_task_start,
        notify_task_success,
    )
    from app.data_pipeline.fetcher import DataFetcher
    from app.data_pipeline.monitor import (
        TaskStatus,
        init_monitor,
        record_task_result,
        record_task_start,
    )

    await init_monitor()
    run_id = await record_task_start("reports")
    await notify_task_start("研报同步")

    try:
        # 使用 minishare 接口（无研报授权码时优雅跳过）
        result = await DataFetcher().fetch_minishare_reports()
        await record_task_result(
            "reports",
            TaskStatus.SUCCESS if result.get("fail", 0) == 0 else TaskStatus.PARTIAL,
            total=result.get("total", 0),
            success=result.get("success", 0),
            skipped=result.get("skipped", 0),
            fail=result.get("fail", 0),
            **_run_id_kwarg(run_id),
        )
        await notify_task_success(
            "研报同步",
            result.get("total", 0),
            result.get("success", 0),
            result.get("fail", 0),
        )
    except Exception as e:
        await record_task_result("reports", TaskStatus.FAILED, error_message=str(e), **_run_id_kwarg(run_id))
        await notify_task_failed("研报同步", str(e))
        raise


async def _run_concept_job() -> None:
    if not _is_trading_hours():
        logger.debug("非交易时段，跳过概念热度同步")
        return
    from app.data_pipeline.dingtalk import (
        notify_task_failed,
        notify_task_start,
        notify_task_success,
    )
    from app.data_pipeline.fetcher import fetch_concept as _fetch_concept_fn
    from app.data_pipeline.monitor import (
        TaskStatus,
        init_monitor,
        record_task_result,
        record_task_start,
    )

    try:
        result = await _fetch_concept_fn()
    except Exception as e:
        await init_monitor()
        run_id = await record_task_start("concept")
        await record_task_result("concept", TaskStatus.FAILED, error_message=str(e), **_run_id_kwarg(run_id))
        await notify_task_failed("概念热度同步", str(e))
        raise

    success = result.get("success", 0)
    fail = result.get("fail", 0)
    # 涨停列表约 18:00 才发布。盘中 0 行是常态，记 SUCCESS 会把「没数据」看成健康。
    if success == 0 and fail == 0:
        logger.info("[concept] 盘中写入 0 行（涨停列表收盘后才发布），不记成功")
        return

    await init_monitor()
    run_id = await record_task_start("concept")
    await notify_task_start("概念热度同步")
    await record_task_result(
        "concept",
        TaskStatus.SUCCESS if fail == 0 else TaskStatus.PARTIAL,
        total=success + fail,
        success=success,
        fail=fail,
        **_run_id_kwarg(run_id),
    )
    await notify_task_success("概念热度同步", success + fail, success, fail)


async def _run_concept_eod_job() -> None:
    """收盘后概念热度补写（首跑/重试共用核心）：**不受交易时段 guard 约束**。

    交易时段内 concept_hourly 拿不到当日数据（limit_list_d 收盘后才发布，
    实测 ≈18:00），本作业在首跑 18:30 + 重试档位补跑；**当日已入库则直接跳过**
    （重试命中即停，且不向数据源发重复请求，规避 tinyshare 授权码并发占用）。
    写入 0 行时记 FAILED 并告警，不再把空跑记成成功。
    """
    today = datetime.now(TRADING_TZ).date()
    if await _concept_limit_has_date(today):
        logger.info("[concept_eod] 今日 %s 概念热度已入库，跳过本次执行", today)
        return
    if not await _is_trading_day_by_daily_data(today):
        # 周末和长假没有日线，静默跳过。近窗已有行情、唯独缺某个工作日时告警：
        # 那是 K 线失败被当成休市，不是正常休市。
        gap = await _weekday_kline_gap(today, include_today=True)
        if gap is not None:
            await _alert_concept_kline_gap(gap, "concept_eod")
            return
        logger.info(
            "[concept_eod] 今日 %s 无日线数据（非交易日或行情未到），跳过且不告警", today
        )
        return

    from app.data_pipeline.dingtalk import (
        notify_task_failed,
        notify_task_start,
        notify_task_success,
    )
    from app.data_pipeline.fetcher import fetch_concept as _fetch_concept_fn
    from app.data_pipeline.monitor import (
        TaskStatus,
        init_monitor,
        record_task_result,
        record_task_start,
    )

    await init_monitor()
    run_id = await record_task_start("concept_eod")
    await notify_task_start("概念热度收盘后补写")

    try:
        result = await _fetch_concept_fn()
        success = result.get("success", 0)
        fail = result.get("fail", 0)
        empty = success == 0 and fail == 0
        await record_task_result(
            "concept_eod",
            TaskStatus.FAILED if empty else (TaskStatus.SUCCESS if fail == 0 else TaskStatus.PARTIAL),
            total=success + fail,
            success=success,
            fail=fail,
            error_message="写入 0 行：当日涨停列表未发布或当日无涨停" if empty else "",
            **_run_id_kwarg(run_id),
        )
        if empty:
            logger.warning(
                "[concept_eod] 写入 0 行：当日涨停列表未发布或当日无涨停，今日概念热度未入库"
            )
            await notify_task_failed(
                "概念热度收盘后补写",
                "写入 0 行：当日涨停列表未发布或当日无涨停",
            )
        else:
            await notify_task_success("概念热度收盘后补写", success + fail, success, fail)
            logger.info(
                "[concept_eod] 概念热度补写完成: 入库 %d, 失败 %d", success, fail
            )
    except Exception as e:
        await record_task_result("concept_eod", TaskStatus.FAILED, error_message=str(e), **_run_id_kwarg(run_id))
        await notify_task_failed("概念热度收盘后补写", str(e))
        raise


async def _run_concept_eod_catchup() -> None:
    """次日开盘前补漏：**条件执行**——查最近缺少概念数据的真实交易日再拉取。

    交易日历 = daily_data（有日线行即交易日）：周末/长假静默。
    近窗已有行情、却缺某个工作日的日线时记失败（K 线失败被当成休市）。
    只对「daily_data 有、concept_limit 无」的缺数据日调 fetch_concept(trade_date=...)，
    覆盖整晚未发布 / 数据源异常 / 当日 EOD 因行情缺失而跳过的漏日。没数据才去要数据，
    防止 tinyshare 授权码并发占用常态化。lookback 默认 10 天。
    """
    from app.data_pipeline.fetcher import fetch_concept as _fetch_concept_fn
    from app.data_pipeline.monitor import (
        TaskStatus,
        init_monitor,
        record_task_result,
        record_task_start,
    )

    today = datetime.now(TRADING_TZ).date()
    missing = await _concept_eod_missing_trade_date()
    gap = await _weekday_kline_gap(today, include_today=False)
    if gap is not None:
        await _alert_concept_kline_gap(gap, "concept_eod_catchup")
    if missing is None:
        if gap is None:
            logger.info("[concept_eod_catchup] 无缺失交易日，跳过")
        return
    await init_monitor()
    run_id = await record_task_start("concept_eod_catchup")
    logger.info("[concept_eod_catchup] 交易日 %s 概念数据缺失，补拉", missing)
    try:
        result = await _fetch_concept_fn(trade_date=missing.strftime("%Y%m%d"))
        success = result.get("success", 0)
        fail = result.get("fail", 0)
        empty = success == 0 and fail == 0
        logger.info("[concept_eod_catchup] 补写交易日 %s: %s", missing, result)
        await record_task_result(
            "concept_eod_catchup",
            TaskStatus.FAILED if empty else (TaskStatus.SUCCESS if fail == 0 else TaskStatus.PARTIAL),
            total=success + fail,
            success=success,
            fail=fail,
            error_message="写入 0 行：涨停列表未发布或当日无涨停" if empty else "",
            **_run_id_kwarg(run_id),
        )
        if empty:
            from app.data_pipeline.dingtalk import notify_task_failed

            logger.warning("[concept_eod_catchup] 交易日 %s 写入 0 行", missing)
            await notify_task_failed("概念热度次日补漏", f"{missing.isoformat()} 写入 0 行")
    except Exception as e:
        await record_task_result("concept_eod_catchup", TaskStatus.FAILED, error_message=str(e), **_run_id_kwarg(run_id))
        raise


async def _run_irm_job() -> None:
    from app.data_pipeline.dingtalk import (
        notify_task_failed,
        notify_task_start,
        notify_task_success,
    )
    from app.data_pipeline.fetcher import DataFetcher
    from app.data_pipeline.monitor import (
        TaskStatus,
        init_monitor,
        record_task_result,
        record_task_start,
    )

    await init_monitor()
    run_id = await record_task_start("irm")
    await notify_task_start("互动易同步")

    try:
        # 优先使用 minishare 接口
        result = await DataFetcher().fetch_irm()
        await record_task_result(
            "irm",
            TaskStatus.SUCCESS if result.get("fail", 0) == 0 else TaskStatus.PARTIAL,
            total=result.get("total", 0),
            success=result.get("success", 0),
            skipped=result.get("skipped", 0),
            fail=result.get("fail", 0),
            **_run_id_kwarg(run_id),
        )
        await notify_task_success(
            "互动易同步",
            result.get("total", 0),
            result.get("success", 0),
            result.get("fail", 0),
        )
    except Exception as e:
        await record_task_result("irm", TaskStatus.FAILED, error_message=str(e), **_run_id_kwarg(run_id))
        await notify_task_failed("互动易同步", str(e))
        raise


async def _run_cninfo_job() -> None:
    """巨潮公告每日同步任务（Phase 03 plan 03-03，D-05 23:00 触发）。

    优先使用 minishare 接口回补；只抓昨天的全市场公告，
    入库时按 cninfo_id 去重；命中关键词的公告在线下载 PDF。
    """
    from app.data_pipeline.dingtalk import (
        notify_task_failed,
        notify_task_start,
        notify_task_success,
    )
    from app.data_pipeline.fetcher import DataFetcher
    from app.data_pipeline.monitor import (
        TaskStatus,
        init_monitor,
        record_task_result,
        record_task_start,
    )

    await init_monitor()
    run_id = await record_task_start("cninfo")
    await notify_task_start("巨潮公告同步")

    try:
        # 优先使用 minishare 接口
        result = await DataFetcher().fetch_minishare_announcements()
        await record_task_result(
            "cninfo",
            TaskStatus.SUCCESS if result.get("fail", 0) == 0 else TaskStatus.PARTIAL,
            total=result.get("total", 0),
            success=result.get("success", 0),
            skipped=result.get("skipped", 0),
            fail=result.get("fail", 0),
            **_run_id_kwarg(run_id),
        )
        # notify_task_success 第三个位置参数语义是"成功数"，第四个是"失败数"。
        # 这里把 PDF 下载条数作为附加观测：通过 notify 仍传 success/fail；
        # downloaded 仅记录到 monitor / log，不改变 dingtalk 通知结构。
        await notify_task_success(
            "巨潮公告同步",
            result.get("total", 0),
            result.get("success", 0),
            result.get("fail", 0),
        )
        logger.info(
            "[cninfo] 巨潮公告完成: 总 %d 新增 %d 跳过 %d 下载 %d 失败 %d",
            result.get("total", 0),
            result.get("success", 0),
            result.get("skipped", 0),
            result.get("downloaded", 0),
            result.get("fail", 0),
        )
    except Exception as e:
        await record_task_result("cninfo", TaskStatus.FAILED, error_message=str(e), **_run_id_kwarg(run_id))
        await notify_task_failed("巨潮公告同步", str(e))
        raise


async def _run_cninfo_enqueue_job() -> None:
    from app.data_pipeline.monitor import (
        TaskStatus,
        init_monitor,
        record_task_result,
        record_task_start,
    )

    await init_monitor()
    run_id = await record_task_start("cninfo_enqueue")
    try:
        result = await enqueue_recent_cninfo_jobs(days=7)
        enqueued = result.get("enqueued", 0)
        await record_task_result(
            "cninfo_enqueue",
            TaskStatus.SUCCESS,
            total=enqueued,
            success=enqueued,
            fail=0,
            **_run_id_kwarg(run_id),
        )
    except Exception as exc:
        await record_task_result("cninfo_enqueue", TaskStatus.FAILED, error_message=str(exc), **_run_id_kwarg(run_id))
        raise


async def _run_irm_enqueue_job() -> None:
    from app.data_pipeline.monitor import (
        TaskStatus,
        init_monitor,
        record_task_result,
        record_task_start,
    )

    await init_monitor()
    run_id = await record_task_start("irm_enqueue")
    try:
        result = await enqueue_irm_company_jobs()
        enqueued = result.get("enqueued", 0)
        await record_task_result(
            "irm_enqueue",
            TaskStatus.SUCCESS,
            total=enqueued,
            success=enqueued,
            fail=0,
            **_run_id_kwarg(run_id),
        )
    except Exception as exc:
        await record_task_result("irm_enqueue", TaskStatus.FAILED, error_message=str(exc), **_run_id_kwarg(run_id))
        raise


async def _run_ingestion_worker_job() -> None:
    result = await IngestionJobWorker(
        job_timeout_seconds=INGESTION_WORKER_TIMEOUT_SECONDS,
    ).run_once(limit=INGESTION_WORKER_DRAIN_LIMIT)
    logger.info("[ingestion_worker] drain result: %s", result)


async def _run_pdf_download_job() -> None:
    """PDF 下载 drain（专用 worker）。

    通用 ingestion worker 只处理 cninfo/irm（SUPPORTED_INGESTION_JOB_TYPES），
    故 pdf_download 必须由本 job 处理；否则 191 条公告 PDF 永不被下载，公告
    evidence 断流。过渡期落云侧（本地 storage），P4 迁移到 H 集群 shared storage。
    """
    from app.knowledge.pdf_download_service import PdfDownloadWorker

    result = await PdfDownloadWorker(
        request_timeout_seconds=PDF_DOWNLOAD_REQUEST_TIMEOUT_SECONDS,
    ).run_once(limit=PDF_DOWNLOAD_DRAIN_LIMIT)
    if result.get("claimed", 0) > 0:
        logger.info("[pdf_download] drain result: %s", result)


async def _run_news_job() -> None:
    """多源快讯定时同步（每 5 分钟）：东财、华尔街见闻、同花顺、新浪滚动。"""
    from app.data_pipeline.monitor import (
        TaskStatus,
        init_monitor,
        record_task_result,
        record_task_start,
    )
    from app.data_pipeline.services.news_service import get_news_service

    await init_monitor()
    run_id = await record_task_start("news_sync")
    service = get_news_service()
    try:
        result = await service.fetch_and_save()
        await record_task_result(
            "news_sync",
            TaskStatus.SUCCESS,
            total=result.get("fetched", 0),
            success=result.get("inserted", 0),
            skipped=result.get("skipped", 0),
            fail=0,
            **_run_id_kwarg(run_id),
        )
        logger.info(
            "[news_sync] 同步结果: fetched=%d inserted=%d skipped=%d",
            result.get("fetched", 0),
            result.get("inserted", 0),
            result.get("skipped", 0),
        )
    except Exception as exc:
        await record_task_result("news_sync", TaskStatus.FAILED, error_message=str(exc), **_run_id_kwarg(run_id))
        raise


async def _run_evidence_worker_job() -> None:
    """知识层证据提取定时任务（每 30 秒，全天 24h 运行）。

    并发按时段分级，尽量避免 pjlab 白天高负载的 504：
    - 抽取窗口（工作日 22:00~08:00 / 周末全天）：EVIDENCE_CONCURRENCY（默认 8）
      pjlab 流控 60RPM/5000万TPM 余量巨大，夜间单条 ~30s 时 8 并发仅占 ~16 RPM
    - 白天（非窗口）：EVIDENCE_CONCURRENCY_DAY（默认 2），pjlab 白天单条 45~120s，
      低并发 + _call_llm_async 三次退避重试把 504 概率压到最低
    """
    from app.knowledge.evidence_worker import EvidenceExtractionWorker

    try:
        if _is_extraction_window():
            concurrency = int(os.getenv("EVIDENCE_CONCURRENCY", "8"))
        else:
            concurrency = int(os.getenv("EVIDENCE_CONCURRENCY_DAY", "2"))
        worker = EvidenceExtractionWorker(batch_size=10, max_concurrency=concurrency)
        result = await worker.run_once(limit=200, job_type="combined")
        if result.get("claimed", 0) > 0:
            logger.info("[evidence_worker] combined: %s", result)
        result = await worker.run_once(limit=200, job_type="vector")
        if result.get("claimed", 0) > 0:
            logger.info("[evidence_worker] vector: %s", result)
        result = await worker.run_once(limit=200, job_type="signal")
        if result.get("claimed", 0) > 0:
            logger.info("[evidence_worker] signal: %s", result)
        result = await worker.run_once(limit=200, job_type="link")
        if result.get("claimed", 0) > 0:
            logger.info("[evidence_worker] link: %s", result)
    except Exception as exc:
        logger.warning("[evidence_worker] 执行异常: %s", exc)


async def finalize_announcement_batch(
    records: list[dict[str, Any]],
    execute: Callable[[str, dict[str, Any]], Awaitable[Any]],
) -> int:
    """标记一批公告已完成 evidence 构建，返回标记条数。

    只改状态、保留 ``file_path``，**不触碰文件系统**：保留 PDF 是有意为之
    （见设计稿 §4.2）—— 文本虽已进 mongo evidence，原文 PDF 仍是产物阅读器的
    取数来源，不能随抽取一起删除。
    """
    ids = [rec["id"] for rec in records]
    if not ids:
        return 0
    await execute(
        "UPDATE minishare_announcements SET evidence_at = now(), download_status = 'stored' "
        "WHERE id = ANY(:ids)",
        {"ids": ids},
    )
    return len(ids)


async def _run_announcement_ingestion_job() -> None:
    """公告 PDF → evidence 切分 + 入队（幂等，抽取窗口前夜跑）。"""
    from app.knowledge.evidence import stable_evidence_id
    from app.knowledge.evidence_service import EvidenceService
    from scripts.ingest_announcements_to_kg import build_announcement_evidence, get_announcements

    service = EvidenceService()
    batch = 200
    processed = evidence_created = jobs_queued = 0
    while True:
        # 始终 offset=0：靠 evidence_at IS NULL 过滤已处理，避免 offset 分页与就地标记冲突
        records = await get_announcements(limit=batch, offset=0)
        if not records:
            break
        all_inputs = []
        for rec in records:
            try:
                # 线程 + 超时：坏 PDF 可能让 pymupdf 卡死，60s 超时跳过，避免阻塞整个切割
                result = await asyncio.wait_for(
                    asyncio.to_thread(build_announcement_evidence, rec),
                    timeout=60,
                )
                all_inputs.extend(result)
            except asyncio.TimeoutError:
                logger.warning("公告 evidence 构建超时(60s)跳过 [%s]", str(rec.get("title", ""))[:40])
            except Exception as exc:
                logger.warning("公告 evidence 构建失败 [%s]: %s", str(rec.get("title", ""))[:40], exc)
        if all_inputs:
            written = await service.bulk_upsert_evidence(all_inputs)
            evidence_ids = list({
                stable_evidence_id(i.source_type, i.source_id, 0, i.text_excerpt)
                for i in all_inputs
            })
            enqueued = await service.bulk_enqueue_jobs(evidence_ids)
            evidence_created += written
            jobs_queued += enqueued
        # 标记已 build evidence（记录哪些 PDF 已处理）；PDF 保留在盘上供产物阅读器取原文
        async with engine.begin() as conn:
            await finalize_announcement_batch(
                records,
                lambda sql, params: conn.execute(text(sql), params),
            )
        processed += len(records)
        if processed % 1000 == 0:
            logger.info("[announcement_ingestion] 进度 %d", processed)
    logger.info(
        "[announcement_ingestion] 完成: 处理 %d 条公告, evidence %d, jobs %d",
        processed, evidence_created, jobs_queued,
    )


async def _run_pdf_rotation_job() -> None:
    from app.knowledge.pdf_rotator import rotate_old_pdfs

    logger.info("[pdf_rotation] 开始两年 PDF 轮转")
    result = await rotate_old_pdfs(days_threshold=730, dry_run=False)
    logger.info("[pdf_rotation] 完成: %s", result)


def add_pdf_rotation_job(scheduler: AsyncIOScheduler) -> None:
    """Register weekly local PDF rotation job idempotently.

    默认不注册（``PDF_ROTATION_ENABLED=false``）：PDF 改为长期保留资产后，
    两年期轮转会删掉原文，只作为运维手工手段保留代码，不随调度自动开跑。
    """
    if not settings.pdf_rotation_enabled:
        return
    scheduler.add_job(
        _run_pdf_rotation_job,
        CronTrigger(
            day_of_week=PDF_ROTATION_WEEKDAY,
            hour=PDF_ROTATION_HOUR,
            minute=0,
            timezone=TIMEZONE,
        ),
        id="pdf_rotation_weekly",
        replace_existing=True,
    )


# Phase 06: Batch reindex job
BATCH_REINDEX_HOUR = 3
BATCH_REINDEX_MINUTE = 0


async def _run_batch_reindex_job() -> None:
    """Nightly batch reindex of missing vector embeddings (Phase 06 D-07)."""
    from app.data_pipeline.dingtalk import (
        notify_task_failed,
        notify_task_start,
        notify_task_success,
    )
    from app.data_pipeline.monitor import (
        TaskStatus,
        init_monitor,
        record_task_result,
        record_task_start,
    )
    from app.knowledge.vector_ops import reindex_missing_vectors

    await init_monitor()
    run_id = await record_task_start("batch_reindex")
    await notify_task_start("向量索引批量重刷")

    try:
        count = await reindex_missing_vectors(batch_size=100)
        await record_task_result(
            "batch_reindex",
            TaskStatus.SUCCESS,
            total=count,
            success=count,
            fail=0,
            **_run_id_kwarg(run_id),
        )
        await notify_task_success(
            "向量索引批量重刷",
            count,
            count,
            0,
        )
        logger.info("[BatchReindex] Completed: %d records reindexed", count)
    except Exception as e:
        await record_task_result("batch_reindex", TaskStatus.FAILED, error_message=str(e), **_run_id_kwarg(run_id))
        await notify_task_failed("向量索引批量重刷", str(e))
        raise


def add_batch_reindex_job(scheduler: AsyncIOScheduler) -> None:
    """Register nightly batch reindex job idempotently."""
    scheduler.add_job(
        _run_batch_reindex_job,
        CronTrigger(
            hour=BATCH_REINDEX_HOUR,
            minute=BATCH_REINDEX_MINUTE,
            timezone=TIMEZONE,
        ),
        id="batch_reindex_daily",
        replace_existing=True,
    )


async def _run_kline_job() -> None:
    """K 线日终任务：收盘后同步白名单股票的日线数据（tinyshare + 配置白名单）。"""
    from app.data_pipeline.backfill_config import load_backfill_settings, reset_settings_cache
    from app.data_pipeline.dingtalk import (
        notify_task_failed,
        notify_task_start,
        notify_task_success,
    )
    from app.data_pipeline.monitor import (
        TaskStatus,
        init_monitor,
        record_task_result,
        record_task_start,
    )
    from scripts.sync_daily_tushare import sync_daily

    await init_monitor()
    run_id = await record_task_start("kline")
    await notify_task_start("K线同步")

    # 从配置读取 scope（默认 tech_mvp）
    reset_settings_cache()
    cfg = load_backfill_settings()
    scope = cfg.scope

    try:
        result = await sync_daily(scope=scope)
        from scripts.sync_index_daily import sync_indices

        index_result = await sync_indices()
        result = {
            "total": result.get("total", 0) + index_result.get("total", 0),
            "ok": result.get("ok", 0) + index_result.get("ok", 0),
            "fail": result.get("fail", 0) + index_result.get("fail", 0),
            "saved": result.get("saved", 0) + index_result.get("saved", 0),
        }
        await record_task_result(
            "kline",
            TaskStatus.SUCCESS if result.get("fail", 0) == 0 else TaskStatus.PARTIAL,
            total=result.get("total", 0),
            success=result.get("ok", 0),
            fail=result.get("fail", 0),
            **_run_id_kwarg(run_id),
        )
        await notify_task_success(
            "K线同步",
            result.get("total", 0),
            result.get("ok", 0),
            result.get("fail", 0),
        )
    except Exception as e:
        await record_task_result("kline", TaskStatus.FAILED, error_message=str(e), **_run_id_kwarg(run_id))
        await notify_task_failed("K线同步", str(e))
        raise


async def _run_kline_catchup_job() -> None:
    """服务启动时仅在数据库落后时触发一次 K 线补漏。"""
    if not await _kline_catchup_needed():
        logger.info("[kline] 启动检查：数据库已追平最近交易日")
        return
    logger.info("[kline] 启动检查发现缺口，开始执行增量补跑")
    await _run_kline_job()


async def _run_sync_stocks_job() -> None:
    from app.data_pipeline.dingtalk import (
        notify_task_failed,
        notify_task_start,
        notify_task_success,
    )
    from scripts.sync_stock_basic import sync_stock_basic
    from app.data_pipeline.monitor import (
        TaskStatus,
        init_monitor,
        record_task_result,
        record_task_start,
    )

    await init_monitor()
    run_id = await record_task_start("stocks")
    await notify_task_start("股票列表同步")

    try:
        result = await sync_stock_basic()
        await record_task_result(
            "stocks",
            TaskStatus.SUCCESS if result.get("fail", 0) == 0 else TaskStatus.PARTIAL,
            total=result.get("total", 0),
            success=result.get("success", 0),
            fail=result.get("fail", 0),
            **_run_id_kwarg(run_id),
        )
        await notify_task_success(
            "股票列表同步",
            result.get("total", 0),
            result.get("success", 0),
            result.get("fail", 0),
        )
    except Exception as e:
        await record_task_result("stocks", TaskStatus.FAILED, error_message=str(e), **_run_id_kwarg(run_id))
        await notify_task_failed("股票列表同步", str(e))
        raise


# ── Phase 31 F: 启动期任务异常观测 ──────
def _task_done_callback(task: asyncio.Task) -> None:
    """add_done_callback 回调：把被 asyncio GC 静默吞掉的异常显式 logger.error。"""
    if task.cancelled():
        logger.info("[启动补漏] 任务被取消: %s", task.get_name())
        return
    exc = task.exception()
    if exc is not None:
        logger.error(
            "[启动补漏] 任务异常: %s",
            task.get_name(),
            exc_info=(type(exc), exc, exc.__traceback__),
        )


class Scheduler:
    """定时任务调度器（APScheduler AsyncIOScheduler 封装）"""

    def __init__(self, run_now: bool = False):
        self.run_now = run_now
        self._scheduler = AsyncIOScheduler(timezone=TIMEZONE)

    def start(self) -> None:
        """注册任务并启动调度器。"""
        self._scheduler.add_job(
            _run_report_job,
            CronTrigger(hour=REPORT_FETCH_HOUR, minute=0, timezone=TIMEZONE),
            id="report_daily",
            replace_existing=True,
        )
        self._scheduler.add_job(
            _run_kline_job,
            CronTrigger(
                hour=KLINE_FETCH_HOUR,
                minute=KLINE_FETCH_MINUTE,
                timezone=TIMEZONE,
            ),
            id="kline_daily",
            replace_existing=True,
        )
        self._scheduler.add_job(
            _run_concept_job,
            CronTrigger(minute=CONCEPT_FETCH_MINUTE, timezone=TIMEZONE),
            id="concept_hourly",
            replace_existing=True,
        )
        concept_eod_hour, concept_eod_minute = _concept_eod_time()
        self._scheduler.add_job(
            _run_concept_eod_job,
            CronTrigger(
                hour=concept_eod_hour,
                minute=concept_eod_minute,
                timezone=TIMEZONE,
            ),
            id="concept_eod",
            replace_existing=True,
        )
        for retry_hour, retry_minute in _concept_eod_retries():
            self._scheduler.add_job(
                _run_concept_eod_job,
                CronTrigger(
                    hour=retry_hour,
                    minute=retry_minute,
                    timezone=TIMEZONE,
                ),
                id=f"concept_eod_retry_{retry_hour:02d}_{retry_minute:02d}",
                replace_existing=True,
            )
        concept_eod_catchup_hour, concept_eod_catchup_minute = _concept_eod_catchup_time()
        self._scheduler.add_job(
            _run_concept_eod_catchup,
            CronTrigger(
                hour=concept_eod_catchup_hour,
                minute=concept_eod_catchup_minute,
                day_of_week="mon-fri",
                timezone=TIMEZONE,
            ),
            id="concept_eod_catchup",
            replace_existing=True,
        )
        logger.info(
            "concept_eod 已注册: 首跑 %02d:%02d + 重试 %s + 次日补昨日 %02d:%02d (%s)",
            concept_eod_hour,
            concept_eod_minute,
            ",".join(f"{h:02d}:{m:02d}" for h, m in _concept_eod_retries()),
            concept_eod_catchup_hour,
            concept_eod_catchup_minute,
            TIMEZONE,
        )
        self._scheduler.add_job(
            _run_irm_enqueue_job,
            CronTrigger(hour=IRM_HOUR, minute=0, timezone=TIMEZONE),
            id="irm_enqueue_daily",
            replace_existing=True,
        )
        self._scheduler.add_job(
            _run_cninfo_enqueue_job,
            CronTrigger(hour=CNINFO_FETCH_HOUR, minute=0, timezone=TIMEZONE),
            id="cninfo_enqueue_daily",
            replace_existing=True,
        )
        self._scheduler.add_job(
            _run_ingestion_worker_job,
            CronTrigger(minute="*/5", timezone=TIMEZONE),
            id="ingestion_worker_drain",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        # PDF 下载：P4 已迁 H 集群（qingshui-pdf-worker.service → shared storage）。
        # 默认关闭云侧 drain 避免双跑；H 不可用时置 ENABLE_PDF_DOWNLOAD_DRAIN=true 回退。
        if os.getenv("ENABLE_PDF_DOWNLOAD_DRAIN", "false").strip().lower() in {
            "1", "true", "yes", "on"
        }:
            self._scheduler.add_job(
                _run_pdf_download_job,
                CronTrigger(minute="*/2", timezone=TIMEZONE),
                id="pdf_download_drain",
                replace_existing=True,
                max_instances=1,
                coalesce=True,
            )
        self._scheduler.add_job(
            _run_announcement_ingestion_job,
            CronTrigger(minute="*/15", timezone=TIMEZONE),
            id="announcement_ingestion",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        add_pdf_rotation_job(self._scheduler)
        # batch_reindex 未注册：reindex_missing_vectors 尚未实现（缺 kg_extraction_index.vector_indexed
        # 字段），且现网向量在抽取时已内联写入（evidence_worker / kg_extractor），无"缺失向量待补"场景。
        # 若注册，每晚会向 monitor/钉钉误报 SUCCESS(count=0) 假成功。待 schema 落地后再启用 add_batch_reindex_job。
        # add_batch_reindex_job(self._scheduler)
        self._scheduler.add_job(
            _run_sync_stocks_job,
            CronTrigger(
                day_of_week=SYNC_STOCKS_WEEKDAY,
                hour=SYNC_STOCKS_HOUR,
                minute=0,
                timezone=TIMEZONE,
            ),
            id="sync_stocks_weekly",
            replace_existing=True,
        )
        self._scheduler.add_job(
            _run_news_job,
            CronTrigger(minute=NEWS_FETCH_MINUTE, timezone=TIMEZONE),
            id="news_sync",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        if _evidence_scheduler_enabled():
            self._scheduler.add_job(
                _run_evidence_worker_job,
                "interval",
                seconds=30,
                id="evidence_worker",
                replace_existing=True,
                max_instances=1,
                coalesce=True,
            )
        else:
            logger.info(
                "[evidence_worker] scheduler disabled (%s=false)",
                ENABLE_EVIDENCE_SCHEDULER_ENV,
            )

        self._scheduler.start()
        logger.info("定时任务调度器启动")

        if self.run_now:
            self._fire_all_once()
        else:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                logger.debug("[kline] 当前无运行中的事件循环，跳过启动补漏检查")
            else:
                task = loop.create_task(_run_kline_catchup_job(), name="kline_catchup_startup")
                task.add_done_callback(_task_done_callback)

    def _fire_all_once(self) -> None:
        """启动时各任务立即跑一次（不阻塞调度器主循环）。

        Phase 31 F 修复：每个 task 加 name + add_done_callback，
        异常不再被 asyncio GC 静默吞掉。
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.error("[启动补漏] 无运行中的 asyncio loop，跳过 run_now 补跑")
            return
        task_specs = [
            (_run_report_job(), "report_startup"),
            (_run_concept_job(), "concept_startup"),
            (_run_kline_job(), "kline_startup"),
            (_run_irm_enqueue_job(), "irm_enqueue_startup"),
            (_run_cninfo_enqueue_job(), "cninfo_enqueue_startup"),
            (_run_ingestion_worker_job(), "ingestion_worker_startup"),
            (_run_sync_stocks_job(), "sync_stocks_startup"),
            (_run_news_job(), "news_startup"),
            (_run_announcement_ingestion_job(), "announcement_ingestion_startup"),
        ]
        if _evidence_scheduler_enabled():
            task_specs.append((_run_evidence_worker_job(), "evidence_worker_startup"))
        tasks = []
        for coro, name in task_specs:
            task = loop.create_task(coro, name=name)
            task.add_done_callback(_task_done_callback)
            tasks.append(task)
        logger.info("[启动补漏] 已派发所有任务一次 (tasks=%d)", len(tasks))

    def stop(self) -> None:
        """关闭调度器（保留正在执行的任务自然结束）。"""
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
        logger.info("定时任务调度器停止")


def run_scheduler(run_now: bool = False) -> None:
    """独立进程入口：在 asyncio 事件循环中持续运行调度器。"""

    async def _main() -> None:
        scheduler = Scheduler(run_now=run_now)
        scheduler.start()
        try:
            while True:
                await asyncio.sleep(3600)
        except asyncio.CancelledError:
            pass
        finally:
            scheduler.stop()

    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        logger.info("收到中断信号，退出")


if __name__ == "__main__":
    import sys

    # scheduler 入口的日志配置：root 默认 WARNING 会吞掉 INFO（旧容器此前依赖临时构建态配置），
    # 显式配置后 concept_eod 的写入行数/0 行 warn 才能落 docker logs。
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    run_scheduler(run_now="--now" in sys.argv)
