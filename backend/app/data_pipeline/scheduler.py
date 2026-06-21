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
from datetime import datetime, time
from typing import Awaitable, Callable

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

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

REPORT_FETCH_HOUR = 3
KLINE_FETCH_HOUR = 17
KLINE_FETCH_MINUTE = 30
CONCEPT_FETCH_MINUTE = 0
IRM_HOUR = 22
SYNC_STOCKS_WEEKDAY = "mon"
SYNC_STOCKS_HOUR = 7

# Phase 03 plan 03-03 / D-05：巨潮公告每日 23:00 收盘后抓取
CNINFO_FETCH_HOUR = 23
PDF_ROTATION_WEEKDAY = "sun"
PDF_ROTATION_HOUR = 2

MONITORED_INDICES = [
    "sh.000001",  # 上证指数
    "sz.399001",  # 深证成指
    "sz.399006",  # 创业板指
    "sh.000300",  # 沪深300
]

MAX_ATTEMPTS = 3  # Phase 31 E 修复：总执行次数（= 1 原始 + 2 次重试）
RETRY_BASE_DELAY = 30  # 秒
INGESTION_WORKER_DRAIN_LIMIT = 5
INGESTION_WORKER_TIMEOUT_SECONDS = 300


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
                    task_name, attempt, MAX_ATTEMPTS, exc, delay,
                )
                await asyncio.sleep(delay)
            else:
                logger.error(
                    "[%s] %d 次尝试全部失败: %s",
                    task_name, MAX_ATTEMPTS, exc,
                )
    return False


async def _run_report_job() -> None:
    from app.data_pipeline.monitor import record_task_start, record_task_result, TaskStatus, init_monitor
    from app.data_pipeline.fetcher import DataFetcher
    from app.data_pipeline.dingtalk import notify_task_start, notify_task_success, notify_task_failed

    await init_monitor()
    await record_task_start("reports")
    notify_task_start("研报同步")

    try:
        result = await DataFetcher().fetch_reports()
        await record_task_result(
            "reports",
            TaskStatus.SUCCESS if result.get("fail", 0) == 0 else TaskStatus.PARTIAL,
            total=result.get("total", 0),
            success=result.get("success", 0),
            skipped=result.get("skipped", 0),
            fail=result.get("fail", 0),
        )
        notify_task_success(
            "研报同步",
            result.get("total", 0),
            result.get("success", 0),
            result.get("fail", 0),
        )
    except Exception as e:
        await record_task_result("reports", TaskStatus.FAILED, error_message=str(e))
        notify_task_failed("研报同步", str(e))
        raise


async def _run_concept_job() -> None:
    if not _is_trading_hours():
        logger.debug("非交易时段，跳过概念热度同步")
        return
    from app.data_pipeline.monitor import record_task_start, record_task_result, TaskStatus, init_monitor
    from app.data_pipeline.fetcher import fetch_concept as _fetch_concept_fn
    from app.data_pipeline.dingtalk import notify_task_start, notify_task_success, notify_task_failed

    await init_monitor()
    await record_task_start("concept")
    notify_task_start("概念热度同步")

    try:
        result = await _fetch_concept_fn()
        await record_task_result(
            "concept",
            TaskStatus.SUCCESS if result.get("fail", 0) == 0 else TaskStatus.PARTIAL,
            total=result.get("success", 0) + result.get("fail", 0),
            success=result.get("success", 0),
            fail=result.get("fail", 0),
        )
        notify_task_success(
            "概念热度同步",
            result.get("success", 0) + result.get("fail", 0),
            result.get("success", 0),
            result.get("fail", 0),
        )
    except Exception as e:
        await record_task_result("concept", TaskStatus.FAILED, error_message=str(e))
        notify_task_failed("概念热度同步", str(e))
        raise


async def _run_irm_job() -> None:
    from app.data_pipeline.monitor import record_task_start, record_task_result, TaskStatus, init_monitor
    from app.data_pipeline.fetcher import DataFetcher
    from app.data_pipeline.dingtalk import notify_task_start, notify_task_success, notify_task_failed

    await init_monitor()
    await record_task_start("irm")
    notify_task_start("互动易同步")

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
        )
        notify_task_success(
            "互动易同步",
            result.get("total", 0),
            result.get("success", 0),
            result.get("fail", 0),
        )
    except Exception as e:
        await record_task_result("irm", TaskStatus.FAILED, error_message=str(e))
        notify_task_failed("互动易同步", str(e))
        raise


async def _run_cninfo_job() -> None:
    """巨潮公告每日同步任务（Phase 03 plan 03-03，D-05 23:00 触发）。

    优先使用 minishare 接口回补；只抓昨天的全市场公告，
    入库时按 cninfo_id 去重；命中关键词的公告在线下载 PDF。
    """
    from app.data_pipeline.monitor import record_task_start, record_task_result, TaskStatus, init_monitor
    from app.data_pipeline.fetcher import DataFetcher
    from app.data_pipeline.dingtalk import notify_task_start, notify_task_success, notify_task_failed

    await init_monitor()
    await record_task_start("cninfo")
    notify_task_start("巨潮公告同步")

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
        )
        # notify_task_success 第三个位置参数语义是"成功数"，第四个是"失败数"。
        # 这里把 PDF 下载条数作为附加观测：通过 notify 仍传 success/fail；
        # downloaded 仅记录到 monitor / log，不改变 dingtalk 通知结构。
        notify_task_success(
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
        await record_task_result("cninfo", TaskStatus.FAILED, error_message=str(e))
        notify_task_failed("巨潮公告同步", str(e))
        raise


async def _run_cninfo_enqueue_job() -> None:
    from app.data_pipeline.monitor import record_task_start, record_task_result, TaskStatus, init_monitor

    await init_monitor()
    await record_task_start("cninfo_enqueue")
    try:
        result = await enqueue_recent_cninfo_jobs(days=7)
        enqueued = result.get("enqueued", 0)
        await record_task_result(
            "cninfo_enqueue",
            TaskStatus.SUCCESS,
            total=enqueued,
            success=enqueued,
            fail=0,
        )
    except Exception as exc:
        await record_task_result("cninfo_enqueue", TaskStatus.FAILED, error_message=str(exc))
        raise


async def _run_irm_enqueue_job() -> None:
    from app.data_pipeline.monitor import record_task_start, record_task_result, TaskStatus, init_monitor

    await init_monitor()
    await record_task_start("irm_enqueue")
    try:
        result = await enqueue_irm_company_jobs()
        enqueued = result.get("enqueued", 0)
        await record_task_result(
            "irm_enqueue",
            TaskStatus.SUCCESS,
            total=enqueued,
            success=enqueued,
            fail=0,
        )
    except Exception as exc:
        await record_task_result("irm_enqueue", TaskStatus.FAILED, error_message=str(exc))
        raise


async def _run_ingestion_worker_job() -> None:
    result = await IngestionJobWorker(
        job_timeout_seconds=INGESTION_WORKER_TIMEOUT_SECONDS,
    ).run_once(limit=INGESTION_WORKER_DRAIN_LIMIT)
    logger.info("[ingestion_worker] drain result: %s", result)


async def _run_pdf_rotation_job() -> None:
    from app.knowledge.pdf_rotator import rotate_old_pdfs

    logger.info("[pdf_rotation] 开始两年 PDF 轮转")
    result = await rotate_old_pdfs(days_threshold=730, dry_run=False)
    logger.info("[pdf_rotation] 完成: %s", result)


def add_pdf_rotation_job(scheduler: AsyncIOScheduler) -> None:
    """Register weekly local PDF rotation job idempotently."""
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
    from app.data_pipeline.monitor import record_task_start, record_task_result, TaskStatus, init_monitor
    from app.data_pipeline.dingtalk import notify_task_start, notify_task_success, notify_task_failed
    from app.knowledge.vector_ops import reindex_missing_vectors

    await init_monitor()
    await record_task_start("batch_reindex")
    notify_task_start("向量索引批量重刷")

    try:
        count = await reindex_missing_vectors(batch_size=100)
        await record_task_result(
            "batch_reindex",
            TaskStatus.SUCCESS,
            total=count,
            success=count,
            fail=0,
        )
        notify_task_success(
            "向量索引批量重刷",
            count,
            count,
            0,
        )
        logger.info("[BatchReindex] Completed: %d records reindexed", count)
    except Exception as e:
        await record_task_result("batch_reindex", TaskStatus.FAILED, error_message=str(e))
        notify_task_failed("向量索引批量重刷", str(e))
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
    """K 线日终任务（D-A4：先 4 个指数 → 再全市场 5000 只个股）。"""
    from datetime import datetime, timedelta
    from app.data_pipeline.monitor import record_task_start, record_task_result, TaskStatus, init_monitor
    from app.data_pipeline.fetcher import DataFetcher
    from app.data_pipeline.dingtalk import notify_task_start, notify_task_success, notify_task_failed

    await init_monitor()
    await record_task_start("kline")
    notify_task_start("K线同步")

    fetcher = DataFetcher()
    today = datetime.now()
    yesterday = (today - timedelta(days=1)).strftime("%Y%m%d")
    today_str = today.strftime("%Y%m%d")

    grand_success = 0
    grand_skipped = 0
    grand_fail = 0

    # ---- 1) 指数 K 线（4 个） ----
    for code in MONITORED_INDICES:
        try:
            result = await fetcher.fetch_index_kline(
                index_code=code,
                start_date=yesterday,
                end_date=today_str,
            )
            grand_success += int(result.get("success", 0) or 0)
            grand_skipped += int(result.get("skipped", 0) or 0)
            grand_fail += int(result.get("fail", 0) or 0)
        except Exception as exc:
            logger.error("指数 %s K线获取失败: %s", code, exc)
            grand_fail += 1
    logger.info("指数 K 线完成: 入库 %d，跳过 %d，失败 %d", grand_success, grand_skipped, grand_fail)

    # ---- 2) 全市场个股 K 线 ----
    try:
        stock_result = await fetcher.fetch_all_stocks_kline()
        grand_success += int(stock_result.get("success", 0) or 0)
        grand_fail += int(stock_result.get("fail", 0) or 0)
        logger.info(
            "全市场个股 K 线完成: 处理 %s/%s，入库 %s 条",
            stock_result.get("processed", 0),
            stock_result.get("total", 0),
            stock_result.get("success", 0),
        )
    except Exception as exc:
        logger.error("全市场个股 K 线任务失败: %s", exc, exc_info=True)
        await record_task_result("kline", TaskStatus.FAILED, error_message=str(exc))
        notify_task_failed("K线同步", str(exc))
        raise

    await record_task_result(
        "kline",
        TaskStatus.SUCCESS if grand_fail == 0 else TaskStatus.PARTIAL,
        total=grand_success + grand_fail,
        success=grand_success,
        fail=grand_fail,
    )
    notify_task_success(
        "K线同步",
        grand_success + grand_fail,
        grand_success,
        grand_fail,
    )


async def _run_sync_stocks_job() -> None:
    from app.data_pipeline.monitor import record_task_start, record_task_result, TaskStatus, init_monitor
    from app.data_pipeline.fetcher import async_sync_stocks
    from app.data_pipeline.dingtalk import notify_task_start, notify_task_success, notify_task_failed

    await init_monitor()
    await record_task_start("stocks")
    notify_task_start("股票列表同步")

    try:
        result = await async_sync_stocks()
        await record_task_result(
            "stocks",
            TaskStatus.SUCCESS if result.get("fail", 0) == 0 else TaskStatus.PARTIAL,
            total=result.get("total", 0),
            success=result.get("success", 0),
            fail=result.get("fail", 0),
        )
        notify_task_success(
            "股票列表同步",
            result.get("total", 0),
            result.get("success", 0),
            result.get("fail", 0),
        )
    except Exception as e:
        await record_task_result("stocks", TaskStatus.FAILED, error_message=str(e))
        notify_task_failed("股票列表同步", str(e))
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
        add_pdf_rotation_job(self._scheduler)
        add_batch_reindex_job(self._scheduler)
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

        self._scheduler.start()
        logger.info("定时任务调度器启动")

        if self.run_now:
            self._fire_all_once()

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
        ]
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
    run_scheduler(run_now="--now" in sys.argv)
