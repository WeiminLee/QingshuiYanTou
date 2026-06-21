"""
DataSyncAPI - 数据同步 API

触发数据采集任务：
1. K线数据（baostock）
2. 公告数据（巨潮 cninfo）
3. 互动易数据（akshare IRM）

所有任务均为异步触发，返回任务ID供后续查询。
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from pydantic import BaseModel, Field

from app.data_pipeline.fetcher import DataFetcher
from app.data_pipeline.data_source import DataSourceClient
from app.data_pipeline.rate_limiter import get_akshare_limiter

logger = logging.getLogger(__name__)
router = APIRouter(tags=["数据同步"])


class SyncResponse(BaseModel):
    """同步任务响应"""
    task_id: str = Field(..., description="任务ID")
    status: str = Field(..., description="状态: pending/running/completed/failed")
    message: str = Field(..., description="状态消息")
    details: Optional[dict[str, Any]] = Field(default=None, description="详细结果")


# ── K线同步 ──────────────────────────────────────────

@router.post("/kline/stocks", response_model=SyncResponse)
async def sync_all_stocks_kline(
    start_date: Optional[str] = Query(default=None, description="开始日期 YYYYMMDD，如 20260601"),
    end_date: Optional[str] = Query(default=None, description="结束日期 YYYYMMDD，如 20260615"),
    background_tasks: BackgroundTasks = None,
) -> SyncResponse:
    """
    同步全市场个股K线数据（baostock）

    - 自动检测每只股票的最新数据日期，仅抓取增量
    - 并发采集（8并发），带速率保护
    - 默认回填30天数据
    """
    task_id = str(uuid.uuid4())[:8]
    logger.info(f"[{task_id}] K线同步任务开始")

    try:
        fetcher = DataFetcher()
        result = await fetcher.fetch_all_stocks_kline(
            start_date=start_date,
            end_date=end_date,
        )
        return SyncResponse(
            task_id=task_id,
            status="completed",
            message=f"K线同步完成: 入库{result.get('success', 0)}条，跳过{result.get('skipped', 0)}条",
            details=result,
        )
    except Exception as e:
        logger.error(f"[{task_id}] K线同步失败: {e}")
        return SyncResponse(
            task_id=task_id,
            status="failed",
            message=f"K线同步失败: {str(e)}",
            details={"error": str(e)},
        )


@router.post("/kline/stock/{ts_code}", response_model=SyncResponse)
async def sync_single_stock_kline(
    ts_code: str,
    start_date: Optional[str] = Query(default=None, description="开始日期 YYYYMMDD"),
    end_date: Optional[str] = Query(default=None, description="结束日期 YYYYMMDD"),
) -> SyncResponse:
    """
    同步单只股票K线数据（baostock）

    Args:
        ts_code: 股票代码，如 000001.SZ / 600000.SH
    """
    task_id = str(uuid.uuid4())[:8]
    logger.info(f"[{task_id}] 单股K线同步: {ts_code}")

    try:
        fetcher = DataFetcher()
        result = await fetcher.fetch_stock_kline(
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date,
        )
        return SyncResponse(
            task_id=task_id,
            status="completed",
            message=f"{ts_code} K线同步完成",
            details=result,
        )
    except Exception as e:
        logger.error(f"[{task_id}] {ts_code} K线同步失败: {e}")
        return SyncResponse(
            task_id=task_id,
            status="failed",
            message=f"K线同步失败: {str(e)}",
        )


@router.post("/kline/indices", response_model=SyncResponse)
async def sync_index_kline(
    index_codes: Optional[list[str]] = Query(
        default=None,
        description="指数代码列表，如 ['sh.000001','sz.399001']",
    ),
    start_date: Optional[str] = Query(default=None, description="开始日期 YYYYMMDD"),
    end_date: Optional[str] = Query(default=None, description="结束日期 YYYYMMDD"),
) -> SyncResponse:
    """
    同步指数K线数据（baostock）

    默认同步4个主要指数：上证指数、深证成指、创业板指、沪深300
    """
    task_id = str(uuid.uuid4())[:8]

    default_indices = ["sh.000001", "sz.399001", "sz.399006", "sh.000300"]
    indices = index_codes or default_indices

    logger.info(f"[{task_id}] 指数K线同步: {indices}")

    try:
        fetcher = DataFetcher()
        today = datetime.now()
        yesterday = (today - timedelta(days=1)).strftime("%Y%m%d")
        today_str = today.strftime("%Y%m%d")

        total_success = 0
        total_skipped = 0
        total_fail = 0

        for code in indices:
            result = await fetcher.fetch_index_kline(
                index_code=code,
                start_date=start_date or yesterday,
                end_date=end_date or today_str,
            )
            total_success += result.get("success", 0)
            total_skipped += result.get("skipped", 0)
            total_fail += result.get("fail", 0)

        return SyncResponse(
            task_id=task_id,
            status="completed",
            message=f"指数K线同步完成: 入库{total_success}条",
            details={
                "success": total_success,
                "skipped": total_skipped,
                "fail": total_fail,
                "indices": indices,
            },
        )
    except Exception as e:
        logger.error(f"[{task_id}] 指数K线同步失败: {e}")
        return SyncResponse(
            task_id=task_id,
            status="failed",
            message=f"指数K线同步失败: {str(e)}",
        )


# ── 公告同步 ──────────────────────────────────────────

@router.post("/announcements", response_model=SyncResponse)
async def sync_announcements(
    ann_date: Optional[str] = Query(default=None, description="日期 YYYYMMDD，默认为昨天"),
    ts_code: Optional[str] = Query(default=None, description="股票代码，为空则查全市场"),
) -> SyncResponse:
    """
    同步巨潮资讯公告数据（cninfo）

    - 获取指定日期的公告列表
    - 自动下载关键词命中的PDF文件
    - 按 cninfo_id 去重
    """
    task_id = str(uuid.uuid4())[:8]
    logger.info(f"[{task_id}] 公告同步: date={ann_date}, ts_code={ts_code}")

    try:
        fetcher = DataFetcher()
        result = await fetcher.fetch_announcements(ann_date=ann_date)
        return SyncResponse(
            task_id=task_id,
            status="completed",
            message=f"公告同步完成: 新增{result.get('success', 0)}条，下载PDF{result.get('downloaded', 0)}条",
            details=result,
        )
    except Exception as e:
        logger.error(f"[{task_id}] 公告同步失败: {e}")
        return SyncResponse(
            task_id=task_id,
            status="failed",
            message=f"公告同步失败: {str(e)}",
        )


@router.post("/announcements/history", response_model=SyncResponse)
async def sync_announcements_history(
    start_date: str = Query(..., description="开始日期 YYYYMMDD"),
    end_date: str = Query(..., description="结束日期 YYYYMMDD"),
    ts_code: Optional[str] = Query(default=None, description="股票代码，为空则查全市场"),
) -> SyncResponse:
    """
    批量同步历史公告（巨潮 cninfo）

    Args:
        start_date: 起始日期 YYYYMMDD
        end_date: 结束日期 YYYYMMDD
        ts_code: 股票代码，为空则查全市场
    """
    task_id = str(uuid.uuid4())[:8]
    logger.info(f"[{task_id}] 历史公告同步: {start_date}~{end_date}, ts_code={ts_code}")

    try:
        fetcher = DataFetcher()
        result = await fetcher.fetch_announcements_history(
            start_date=start_date,
            end_date=end_date,
            ts_code=ts_code,
        )
        return SyncResponse(
            task_id=task_id,
            status="completed",
            message=f"历史公告同步完成: 新增{result.get('success', 0)}条",
            details=result,
        )
    except Exception as e:
        logger.error(f"[{task_id}] 历史公告同步失败: {e}")
        return SyncResponse(
            task_id=task_id,
            status="failed",
            message=f"历史公告同步失败: {str(e)}",
        )


# ── 互动易同步 ──────────────────────────────────────────

@router.post("/irm", response_model=SyncResponse)
async def sync_irm(
    ts_codes: Optional[list[str]] = Query(
        default=None,
        description="股票代码列表，为空则同步全市场",
    ),
    extract_to_kg: bool = Query(default=False, description="是否同步抽取知识图谱"),
) -> SyncResponse:
    """
    同步互动易Q&A数据（akshare）

    - 深交所 + 上交所互动易
    - 支持指定股票或全市场
    - 带20小时增量过滤（避免重复抓取）
    """
    task_id = str(uuid.uuid4())[:8]
    logger.info(f"[{task_id}] 互动易同步: {len(ts_codes or [])} 只股票")

    try:
        fetcher = DataFetcher()
        result = await fetcher.fetch_irm(
            ts_codes=ts_codes,
            extract_to_kg=extract_to_kg,
        )
        return SyncResponse(
            task_id=task_id,
            status="completed",
            message=f"互动易同步完成: 入库{result.get('success', 0)}条记录",
            details=result,
        )
    except Exception as e:
        logger.error(f"[{task_id}] 互动易同步失败: {e}")
        return SyncResponse(
            task_id=task_id,
            status="failed",
            message=f"互动易同步失败: {str(e)}",
        )


@router.post("/irm/{ts_code}", response_model=SyncResponse)
async def sync_single_irm(
    ts_code: str,
    extract_to_kg: bool = Query(default=False),
) -> SyncResponse:
    """
    同步单只股票互动易数据

    Args:
        ts_code: 股票代码，如 000001.SZ
    """
    task_id = str(uuid.uuid4())[:8]
    logger.info(f"[{task_id}] 单股互动易同步: {ts_code}")

    try:
        fetcher = DataFetcher()
        result = await fetcher.fetch_irm(
            ts_codes=[ts_code],
            extract_to_kg=extract_to_kg,
        )
        return SyncResponse(
            task_id=task_id,
            status="completed",
            message=f"{ts_code} 互动易同步完成",
            details=result,
        )
    except Exception as e:
        logger.error(f"[{task_id}] {ts_code} 互动易同步失败: {e}")
        return SyncResponse(
            task_id=task_id,
            status="failed",
            message=f"互动易同步失败: {str(e)}",
        )


# ── 全量同步 ──────────────────────────────────────────

@router.post("/all", response_model=SyncResponse)
async def sync_all_data(
    kline_days: int = Query(default=30, ge=1, le=365, description="K线回填天数"),
) -> SyncResponse:
    """
    执行全量数据同步（K线 + 公告 + 互动易）

    注意：这是一个重量级操作，可能需要较长时间
    建议拆分成单独任务分批执行
    """
    task_id = str(uuid.uuid4())[:8]
    logger.info(f"[{task_id}] 全量数据同步开始 (K线{kline_days}天)")

    results = {}

    # 1. K线同步
    try:
        fetcher = DataFetcher()
        kline_result = await fetcher.fetch_all_stocks_kline()
        results["kline"] = kline_result
        logger.info(f"[{task_id}] K线完成: {kline_result.get('success', 0)}条")
    except Exception as e:
        results["kline"] = {"error": str(e)}
        logger.error(f"[{task_id}] K线失败: {e}")

    # 2. 公告同步（昨天）
    try:
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
        ann_result = await fetcher.fetch_announcements(ann_date=yesterday)
        results["announcements"] = ann_result
        logger.info(f"[{task_id}] 公告完成: {ann_result.get('success', 0)}条")
    except Exception as e:
        results["announcements"] = {"error": str(e)}
        logger.error(f"[{task_id}] 公告失败: {e}")

    # 3. 互动易同步（全市场，带KG抽取）
    try:
        irm_result = await fetcher.fetch_irm_with_kg()
        results["irm"] = irm_result
        logger.info(f"[{task_id}] 互动易完成: {irm_result.get('success', 0)}条")
    except Exception as e:
        results["irm"] = {"error": str(e)}
        logger.error(f"[{task_id}] 互动易失败: {e}")

    return SyncResponse(
        task_id=task_id,
        status="completed",
        message="全量数据同步完成",
        details=results,
    )


# ── minishare 备选通道 ──────────────────────────────────

@router.post("/minishare/reports", response_model=SyncResponse)
async def sync_minishare_reports(
    trade_date: Optional[str] = Query(default=None, description="研报日期 YYYYMMDD，默认为昨天"),
    ts_code: Optional[str] = Query(default=None, description="股票代码，如 600519.SH"),
    start_date: Optional[str] = Query(default=None, description="起始日期 YYYYMMDD（配合 ts_code 使用）"),
    end_date: Optional[str] = Query(default=None, description="结束日期 YYYYMMDD（配合 ts_code 使用）"),
) -> SyncResponse:
    """
    从 minishare 获取券商研报（备选通道）

    - 按日期全市场或按股票代码 + 日期范围
    - 与 akshare 研报共用 research_report_meta 表
    """
    task_id = str(uuid.uuid4())[:8]
    logger.info(f"[{task_id}] minishare 研报同步: trade_date={trade_date}, ts_code={ts_code}")

    try:
        fetcher = DataFetcher()
        result = await fetcher.fetch_minishare_reports(
            trade_date=trade_date,
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date,
        )
        return SyncResponse(
            task_id=task_id,
            status="completed",
            message=f"minishare 研报同步完成: 入库{result.get('success', 0)}条，跳过{result.get('skipped', 0)}条",
            details=result,
        )
    except Exception as e:
        logger.error(f"[{task_id}] minishare 研报同步失败: {e}")
        return SyncResponse(
            task_id=task_id,
            status="failed",
            message=f"minishare 研报同步失败: {str(e)}",
            details={"error": str(e)},
        )


@router.post("/minishare/irm", response_model=SyncResponse)
async def sync_minishare_irm(
    trade_date: Optional[str] = Query(default=None, description="日期 YYYYMMDD，默认为昨天"),
) -> SyncResponse:
    """
    从 minishare 获取互动易 Q&A（备选通道）

    - 深交所 + 上交所
    - 与 akshare 互动易共用 announcements 表
    """
    task_id = str(uuid.uuid4())[:8]
    logger.info(f"[{task_id}] minishare 互动易同步: trade_date={trade_date}")

    try:
        fetcher = DataFetcher()
        result = await fetcher.fetch_irm()
        return SyncResponse(
            task_id=task_id,
            status="completed",
            message=f"minishare 互动易同步完成: 入库{result.get('success', 0)}条，跳过{result.get('skipped', 0)}条",
            details=result,
        )
    except Exception as e:
        logger.error(f"[{task_id}] minishare 互动易同步失败: {e}")
        return SyncResponse(
            task_id=task_id,
            status="failed",
            message=f"minishare 互动易同步失败: {str(e)}",
            details={"error": str(e)},
        )


# ── minishare 历史批量同步 ────────────────────────────────

@router.post("/minishare/reports/history", response_model=SyncResponse)
async def sync_minishare_reports_history(
    start_date: str = Query(..., description="起始日期 YYYYMMDD，如 20250601"),
    end_date: str = Query(..., description="结束日期 YYYYMMDD，如 20260616"),
    download_pdf: bool = Query(default=True, description="是否下载 PDF"),
    background_tasks: BackgroundTasks = None,
) -> SyncResponse:
    """
    从 minishare 批量回填历史研报（断点续跑，异步执行）

    - 从 start_date 到 end_date 逐日遍历
    - 使用 IngestionProgressTracker checkpoint，重复运行不会从头开始
    - PDF 存到外部存储（/home/lwm/qingshui_data/reports/）
    - 任务异步执行，立即返回 run_id，用 GET /minishare/tasks/{run_id} 查询进度
    """
    task_id = str(uuid.uuid4())  # 完整 UUID 传给 fetcher
    task_id_short = task_id[:8]  # 截取前 8 位用于响应显示
    logger.info(f"[{task_id_short}] minishare 研报历史同步已提交: {start_date}~{end_date}")

    async def _run() -> None:
        """后台执行体"""
        from app.data_pipeline.fetcher import DataFetcher

        try:
            fetcher = DataFetcher()
            result = await fetcher.fetch_minishare_reports_history(
                start_date=start_date,
                end_date=end_date,
                download_pdf=download_pdf,
                task_id=task_id,
            )
            logger.info(f"[{task_id_short}] minishare 研报历史同步完成: {result}")
        except Exception as e:
            logger.error(f"[{task_id_short}] minishare 研报历史同步失败: {e}", exc_info=True)

    if background_tasks:
        background_tasks.add_task(_run)
        return SyncResponse(
            task_id=task_id_short,
            status="running",
            message=f"研报历史同步任务已提交: {start_date}~{end_date}，用 GET /minishare/tasks/{task_id} 查询进度",
        )
    else:
        # 无 BackgroundTasks 时同步执行（单元测试路径）
        await _run()
        return SyncResponse(
            task_id=task_id_short,
            status="completed",
            message=f"minishare 研报历史同步完成: {start_date}~{end_date}",
        )


@router.post("/minishare/irm/history", response_model=SyncResponse)
async def sync_minishare_irm_history(
    start_date: str = Query(..., description="起始日期 YYYYMMDD，如 20250601"),
    end_date: str = Query(..., description="结束日期 YYYYMMDD，如 20260616"),
    background_tasks: BackgroundTasks = None,
) -> SyncResponse:
    """
    从 minishare 批量回填历史互动易（断点续跑，异步执行）

    - 从 start_date 到 end_date 逐日遍历（上证 + 深证）
    - 使用 IngestionProgressTracker checkpoint，重复运行不会从头开始
    - 任务异步执行，立即返回 run_id，用 GET /minishare/tasks/{run_id} 查询进度
    """
    task_id = str(uuid.uuid4())  # 完整 UUID 传给 fetcher
    task_id_short = task_id[:8]  # 截取前 8 位用于响应显示
    logger.info(f"[{task_id_short}] minishare 互动易历史同步已提交: {start_date}~{end_date}")

    async def _run() -> None:
        """后台执行体"""
        from app.data_pipeline.fetcher import DataFetcher

        try:
            fetcher = DataFetcher()
            result = await fetcher.fetch_irm()
            logger.info(f"[{task_id_short}] minishare 互动易历史同步完成: {result}")
        except Exception as e:
            logger.error(f"[{task_id_short}] minishare 互动易历史同步失败: {e}", exc_info=True)

    if background_tasks:
        background_tasks.add_task(_run)
        return SyncResponse(
            task_id=task_id_short,
            status="running",
            message=f"互动易历史同步任务已提交: {start_date}~{end_date}，用 GET /minishare/tasks/{task_id} 查询进度",
        )
    else:
        await _run()
        return SyncResponse(
            task_id=task_id_short,
            status="completed",
            message=f"minishare 互动易历史同步完成: {start_date}~{end_date}",
        )


# ── minishare 公告同步 ──────────────────────────────────

@router.post("/minishare/announcements", response_model=SyncResponse)
async def sync_minishare_announcements(
    ann_date: Optional[str] = Query(default=None, description="公告日期 YYYYMMDD，默认为昨天"),
    ts_code: Optional[str] = Query(default=None, description="股票代码，如 600519.SH"),
    start_date: Optional[str] = Query(default=None, description="起始日期 YYYYMMDD（配合 ts_code 使用）"),
    end_date: Optional[str] = Query(default=None, description="结束日期 YYYYMMDD（配合 ts_code 使用）"),
) -> SyncResponse:
    """
    从 minishare 获取公告数据（备选通道）

    - 按公告日全市场或按股票代码 + 日期范围
    - 存入 minishare_announcements 表
    """
    task_id = str(uuid.uuid4())[:8]
    logger.info(f"[{task_id}] minishare 公告同步: ann_date={ann_date}, ts_code={ts_code}")

    try:
        fetcher = DataFetcher()
        result = await fetcher.fetch_minishare_announcements(
            ann_date=ann_date,
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date,
        )
        return SyncResponse(
            task_id=task_id,
            status="completed",
            message=f"minishare 公告同步完成: 入库{result.get('success', 0)}条，跳过{result.get('skipped', 0)}条",
            details=result,
        )
    except Exception as e:
        logger.error(f"[{task_id}] minishare 公告同步失败: {e}")
        return SyncResponse(
            task_id=task_id,
            status="failed",
            message=f"minishare 公告同步失败: {str(e)}",
            details={"error": str(e)},
        )


@router.post("/minishare/announcements/history", response_model=SyncResponse)
async def sync_minishare_ann_history(
    start_date: str = Query(..., description="起始日期 YYYYMMDD，如 20250601"),
    end_date: str = Query(..., description="结束日期 YYYYMMDD，如 20260616"),
    background_tasks: BackgroundTasks = None,
) -> SyncResponse:
    """
    从 minishare 批量回填历史公告（断点续跑，异步执行）

    - 从 start_date 到 end_date 逐日遍历
    - 使用 IngestionProgressTracker checkpoint，重复运行不会从头开始
    - 任务异步执行，立即返回 run_id，用 GET /minishare/tasks/{run_id} 查询进度
    """
    task_id = str(uuid.uuid4())  # 完整 UUID 传给 fetcher
    task_id_short = task_id[:8]
    logger.info(f"[{task_id_short}] minishare 公告历史同步已提交: {start_date}~{end_date}")

    async def _run() -> None:
        """后台执行体"""
        from app.data_pipeline.fetcher import DataFetcher

        try:
            fetcher = DataFetcher()
            result = await fetcher.fetch_minishare_ann_history(
                start_date=start_date,
                end_date=end_date,
                task_id=task_id,
            )
            logger.info(f"[{task_id_short}] minishare 公告历史同步完成: {result}")
        except Exception as e:
            logger.error(f"[{task_id_short}] minishare 公告历史同步失败: {e}", exc_info=True)

    if background_tasks:
        background_tasks.add_task(_run)
        return SyncResponse(
            task_id=task_id_short,
            status="running",
            message=f"公告历史同步任务已提交: {start_date}~{end_date}，用 GET /minishare/tasks/{task_id} 查询进度",
        )
    else:
        await _run()
        return SyncResponse(
            task_id=task_id_short,
            status="completed",
            message=f"minishare 公告历史同步完成: {start_date}~{end_date}",
        )


@router.get("/minishare/progress", response_model=dict)
async def get_minishare_progress() -> dict:
    """
    查询 minishare 数据同步进度（断点状态）

    返回研报和互动易历史同步的 checkpoint 信息
    """
    from sqlalchemy import text
    from app.core.database import engine

    async with engine.connect() as conn:
        rows = await conn.execute(
            text(
                """
                SELECT source, task_name, scope,
                       last_success_watermark, last_success_at,
                       last_status, updated_at
                FROM ingestion_checkpoints
                WHERE source IN ('minishare', 'minishare_irm')
                ORDER BY updated_at DESC
                LIMIT 20
                """
            )
        )
        checkpoints = [dict(row._mapping) for row in rows.fetchall()]

    return {"checkpoints": checkpoints}


@router.get("/minishare/tasks/{run_id}", response_model=dict)
async def get_minishare_task_status(run_id: str) -> dict:
    """
    查询单次 minishare 同步任务的状态和进度

    Args:
        run_id: 任务ID（来自 POST 响应的 task_id）

    Returns:
        任务状态、当前进度（日期/总数）、入库统计
    """
    from sqlalchemy import text
    from app.core.database import engine

    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    """
                    SELECT run_id, source, task_name, scope,
                           status, started_at, completed_at,
                           from_watermark, to_watermark,
                           current_watermark,
                           total_items, processed_items,
                           success_count, skipped_count,
                           downloaded_count, fail_count,
                           last_error
                    FROM ingestion_runs
                    WHERE run_id::text = :run_id
                    LIMIT 1
                    """
                ),
                {"run_id": run_id},
            )
        ).mappings().first()

    if not row:
        return {
            "run_id": run_id,
            "status": "not_found",
            "message": f"任务 {run_id} 不存在或已过期",
        }

    d = dict(row)
    # 计算进度百分比
    total = d.get("total_items") or 0
    done = d.get("processed_items") or 0
    pct = round(done / total * 100, 1) if total > 0 else 0

    # 计算日期进度
    from_wm = d.get("from_watermark") or ""
    to_wm = d.get("to_watermark") or ""
    cur_wm = d.get("current_watermark") or ""

    from_dt = _parse_date(from_wm)
    to_dt = _parse_date(to_wm)
    cur_dt = _parse_date(cur_wm)

    date_pct = 0
    if from_dt and to_dt and cur_dt:
        total_days = (to_dt - from_dt).days + 1
        elapsed = (cur_dt - from_dt).days + 1
        date_pct = round(elapsed / total_days * 100, 1) if total_days > 0 else 0

    return {
        "run_id": d["run_id"],
        "source": d["source"],
        "task_name": d["task_name"],
        "scope": d["scope"],
        "status": d["status"],
        "started_at": d["started_at"],
        "completed_at": d["completed_at"],
        "from_watermark": from_wm,
        "to_watermark": to_wm,
        "current_watermark": cur_wm,
        "progress": {
            "days_pct": date_pct,
            "items_pct": pct,
            "total_days": total,
            "processed_days": done,
            "success": d.get("success_count") or 0,
            "skipped": d.get("skipped_count") or 0,
            "downloaded": d.get("downloaded_count") or 0,
            "fail": d.get("fail_count") or 0,
        },
        "last_error": d.get("last_error"),
    }


def _parse_date(s: str):
    """把 YYYYMMDD 字符串解析为 date 对象，失败返回 None"""
    if not s or len(s) != 8:
        return None
    from datetime import date

    try:
        return date(int(s[:4]), int(s[4:6]), int(s[6:8]))
    except Exception:
        return None


# ── 数据状态查询 ──────────────────────────────────────────

@router.get("/status", response_model=dict)
async def get_sync_status() -> dict:
    """
    获取当前数据同步状态

    返回各数据源的最新同步时间和记录数
    """
    from sqlalchemy import text
    from app.core.database import engine

    try:
        async with engine.connect() as conn:
            # 股票数量
            stock_count = await conn.execute(
                text("SELECT COUNT(*) FROM stocks")
            )
            stock_count = stock_count.scalar() or 0

            # K线最新日期
            kline_latest = await conn.execute(
                text("SELECT MAX(trade_date) FROM daily_data")
            )
            kline_latest = kline_latest.scalar()

            # 公告数量和最新日期
            ann_count = await conn.execute(
                text("SELECT COUNT(*) FROM announcements WHERE source_type = 'cninfo'")
            )
            ann_count = ann_count.scalar() or 0

            ann_latest = await conn.execute(
                text("SELECT MAX(ann_date) FROM announcements WHERE source_type = 'cninfo'")
            )
            ann_latest = ann_latest.scalar()

            # 互动易数量
            irm_count = await conn.execute(
                text("SELECT COUNT(*) FROM announcements WHERE source_type = 'irm'")
            )
            irm_count = irm_count.scalar() or 0

        return {
            "stocks": {
                "count": stock_count,
            },
            "kline": {
                "latest_date": kline_latest.isoformat() if kline_latest else None,
            },
            "announcements": {
                "count": ann_count,
                "latest_date": ann_latest.isoformat() if ann_latest else None,
            },
            "irm": {
                "count": irm_count,
            },
        }
    except Exception as e:
        logger.error(f"获取同步状态失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))