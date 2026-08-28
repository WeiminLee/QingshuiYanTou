"""
DataFetcher - 数据获取服务

协调 minishare/tinyshare 数据源抓数 + PostgreSQL 入库 + 文件落盘。
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import math
import random
import re
import uuid
from datetime import UTC, date, datetime, timedelta
from functools import partial
from pathlib import Path
from typing import Any

import pytz
import requests
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.core.database import engine
from app.core.mongodb import get_mongo_db
from app.data_pipeline.announcement_filter import (
    DOC_TYPE_SAVE as ANN_DOC_TYPE_SAVE,
)
from app.data_pipeline.announcement_filter import (
    classify_title as classify_ann_title,
)
from app.data_pipeline.file_storage import FileStorage
from app.data_pipeline.minishare_client import DataSourceClientMinishare
from app.data_pipeline.progress import (
    FAILED,
    PARTIAL,
    SUCCESS,
    IngestionProgressTracker,
)
from app.data_pipeline.report_filter import (
    should_save,
)
from app.logging.logger import AsyncAuditLogger, generate_task_id, set_task_id

logger = logging.getLogger(__name__)

# 下载 PDF 的请求头
HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/pdf,*/*",
}


# ── 常量 ───────────────────────────────────────────────

IRM_CONCURRENCY = 4  # 互动易并发抓取度（保护接口 & 避免被反爬）
IRM_SLEEP_BASE = 1.0  # 每只股票最小间隔（秒）
IRM_SLEEP_JITTER = 1.0  # 附加随机抖动
IRM_PROGRESS_EVERY = 10  # 互动易接入进度事件节流
CONCEPT_CODE_PREFIX = "CN_"  # 自造概念板块代码前缀，避免与 THS TI 代码冲突
CNINFO_PROGRESS_EVERY = 50

# Phase 31 D-A2/A5 — 全市场个股 K 线采集
STOCK_KLINE_CONCURRENCY = 8  # baostock 服务端可承受的并发（保守值，可 4-16 调整）
STOCK_KLINE_SLEEP_BASE = 0.3  # worker 内 sleep 基线（秒）
STOCK_KLINE_SLEEP_JITTER = 0.4  # worker sleep 随机抖动上限
STOCK_KLINE_RECONNECT_EVERY = 500  # 每 N 只重连一次（防 baostock 长连接 broken pipe）
STOCK_KLINE_BACKFILL_DAYS = 30  # 首次回填窗口（D-A5：agent 分析常用窗口）

# Phase 31 I: IRM MongoDB checkpoint
IRM_CHECKPOINT_COLLECTION = "irm_checkpoint"
IRM_CHECKPOINT_WINDOW_HOURS = 20  # 20 小时内成功过的 ts_code 跳过

# 中国时区常量（用于 IRM checkpoint 等时间敏感操作）
SH_TZ = pytz.timezone("Asia/Shanghai")


# ── 工具函数 ────────────────────────────────────────────


def _stable_id(prefix: str, *parts: str) -> str:
    """生成确定性唯一ID（进程重启后不变）。"""
    raw = "".join(str(p) for p in parts).encode("utf-8", errors="replace")
    return f"{prefix}_{hashlib.sha1(raw).hexdigest()[:16]}"


def _norm_ts_code(value: Any) -> str:
    """把 pandas NaN / None / 'nan' 都过滤掉。"""
    if value is None:
        return ""
    if isinstance(value, float) and value != value:  # NaN
        return ""
    text_val = str(value).strip()
    if text_val.lower() in ("nan", "none", ""):
        return ""
    return text_val


def _normalize_ts_code(code: str) -> str:
    """标准化股票代码格式"""
    if not code:
        return ""
    c = code.strip()
    if "." not in c:
        return f"{c}.SH" if c.startswith("6") else f"{c}.SZ"
    prefix, num = c.split(".", 1)
    if prefix.lower() in ("sh", "ss"):
        return f"{num}.SH"
    if prefix.lower() in ("sz",):
        return f"{num}.SZ"
    return c.upper()


def _yyyymmdd_to_date(value: str | None) -> date | None:
    """YYYYMMDD → date；无效值返回 None。"""
    if not value or len(value) < 8 or not value[:8].isdigit():
        return None
    return date(int(value[:4]), int(value[4:6]), int(value[6:8]))


def _safe_float(value: Any) -> float | None:
    if value in (None, "", b""):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _concept_code(concept_name: str) -> str:
    """用概念名 hash 生成稳定的板块代码，避免 B6 中 concept_code 与 concept_name 串台。"""
    digest = hashlib.sha1(concept_name.encode("utf-8", errors="replace")).hexdigest()[:12]
    return f"{CONCEPT_CODE_PREFIX}{digest}"


# ── DataFetcher ────────────────────────────────────────


class DataFetcher:
    """数据获取服务"""

    def __init__(
        self,
        registry: Any | None = None,
    ) -> None:
        self._registry = registry
        self.storage = FileStorage()
        self.audit_logger = AsyncAuditLogger("data_pipeline")
        self.minishare_client = DataSourceClientMinishare()

    # ---------- 研报 ----------

    async def fetch_minishare_reports(
        self,
        trade_date: str | None = None,
        ts_code: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, int]:
        """从 minishare 获取研报并入库（备选通道）。"""
        task_id = generate_task_id()
        set_task_id(task_id)

        if trade_date is None:
            trade_date = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")

        if not self.minishare_client.research_available:
            logger.warning("minishare 研报 token 未配置，跳过")
            return {"total": 0, "success": 0, "skipped": 0, "fail": 0, "source": "minishare"}

        logger.info("开始从 minishare 获取研报: %s", trade_date)
        await self.audit_logger.ainfo(
            "fetcher",
            f"开始从 minishare 获取研报: {trade_date}",
            task_id=task_id,
            trade_date=trade_date,
        )

        reports = await asyncio.to_thread(
            self.minishare_client.get_reports,
            trade_date=trade_date,
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date,
        )

        # 复用 fetch_reports 的 EXISTS 预查询 + 入库逻辑
        candidates: list[dict[str, Any]] = []
        for report in reports:
            title = str(report.get("title") or "")
            # 研报过滤：只保存产业链相关报告
            if not should_save(title):
                continue
            inst_csname = str(report.get("inst_csname") or "")
            author = str(report.get("author") or "")
            url = str(report.get("url") or "")
            ts_code_val = _norm_ts_code(report.get("ts_code"))

            ann_id: str | None = None
            if url:
                try:
                    pdf_part = url.split("/")[-1].split("?")[0]
                    if pdf_part:
                        ann_id = f"ms_report_{pdf_part}"
                except Exception:
                    ann_id = None
            if not ann_id:
                ann_id = _stable_id("ms_report", trade_date, title, inst_csname)

            candidates.append(
                {
                    "ann_id": ann_id,
                    "ts_code": ts_code_val,
                    "title": title,
                    "inst_csname": inst_csname,
                    "author": author,
                    "url": url,
                }
            )

        candidate_ann_ids = [c["ann_id"] for c in candidates]
        existing: set[str] = set()
        if candidate_ann_ids:
            try:
                async with engine.connect() as conn:
                    rows = await conn.execute(
                        text("SELECT file_name FROM research_report_meta WHERE file_name = ANY(:ids)"),
                        {"ids": candidate_ann_ids},
                    )
                    existing = {r[0] for r in rows.fetchall()}
            except Exception as exc:
                logger.warning("研报 EXISTS 预查询失败: %s", exc)

        total = len(candidates)
        success = skipped = fail = 0
        for c in candidates:
            if c["ann_id"] in existing:
                skipped += 1
                continue

            saved = await self._save_report(
                ann_id=c["ann_id"],
                ts_code=c["ts_code"],
                title=c["title"],
                trade_date=trade_date,
                inst_csname=c["inst_csname"],
                author=c["author"],
                source_name="minishare",
            )
            if saved is True:
                success += 1
            elif saved is None:
                skipped += 1
            else:
                fail += 1

        logger.info(
            "minishare 研报获取完成: 总 %d，新增 %d，跳过 %d，失败 %d",
            total,
            success,
            skipped,
            fail,
        )
        return {
            "total": total,
            "success": success,
            "skipped": skipped,
            "fail": fail,
            "source": "minishare",
        }

    async def fetch_minishare_reports_history(
        self,
        start_date: str,
        end_date: str,
        download_pdf: bool = True,
        task_id: str | None = None,
    ) -> dict[str, int]:
        """从 minishare 批量回填历史研报（按日期遍历，断点续跑）。

        断点机制：读取 ingestion_checkpoints.last_success_watermark，
        从断点+1天继续。下次运行自动从上次完成的日期恢复。

        Args:
            start_date: 起始日期 YYYYMMDD
            end_date: 结束日期 YYYYMMDD
            download_pdf: 是否下载 PDF（默认 True）
            task_id: 可选，API 层传入的任务ID，用于关联 ingestion_runs 表
        """
        internal_task_id = task_id or generate_task_id()
        set_task_id(internal_task_id)

        if not self.minishare_client.research_available:
            logger.warning("minishare 研报 token 未配置，跳过")
            return {
                "total_days": 0,
                "success": 0,
                "skipped": 0,
                "downloaded": 0,
                "fail": 0,
                "source": "minishare",
            }

        tracker = IngestionProgressTracker(
            source="minishare",
            task_name="reports_history",
            scope=f"{start_date}_{end_date}",
        )
        await tracker.ensure_tables()

        # 读取 checkpoint，从断点继续
        checkpoint = await tracker.get_checkpoint()
        resume_start = start_date
        if checkpoint and checkpoint.get("last_success_watermark"):
            resume_date = checkpoint["last_success_watermark"]
            resume_next = (datetime.strptime(resume_date, "%Y%m%d") + timedelta(days=1)).strftime("%Y%m%d")
            if resume_next <= end_date:
                resume_start = resume_next
                logger.info(f"研报历史同步断点续跑: 从 {resume_start} 开始（已完成 {resume_date}）")

        # 用传入的 task_id 作为 run_id（方便 API 查询）
        run_uuid: uuid.UUID | None = None
        if task_id:
            try:
                # 补全为完整 UUID（取前8字节拼接）
                run_uuid = uuid.UUID(task_id)
            except ValueError:
                run_uuid = None

        run_ctx = await tracker.start_run(
            from_watermark=resume_start,
            to_watermark=end_date,
            metadata={"download_pdf": download_pdf, "source": "minishare"},
            run_id=run_uuid,
        )

        logger.info("开始 minishare 研报历史同步: %s~%s", resume_start, end_date)
        await self.audit_logger.ainfo(
            "fetcher",
            f"minishare 研报历史同步: {resume_start}~{end_date}",
            task_id=internal_task_id,
        )

        total_success = 0
        total_skipped = 0
        total_fail = 0
        total_downloaded = 0
        total_days = 0
        last_success_date = resume_start

        async for date_str, reports in self.minishare_client.iter_reports_by_date_range_async(resume_start, end_date):
            total_days += 1

            if not reports:
                await tracker.save_checkpoint(
                    last_success_watermark=date_str,
                    last_success_at=datetime.now(UTC),
                    last_status="running",
                )
                await tracker.update_run(
                    run_ctx,
                    current_watermark=date_str,
                    total_items=total_days,
                    processed_items=total_days,
                )
                last_success_date = date_str
                continue

            # EXISTS 预查询
            candidates: list[dict[str, Any]] = []
            for report in reports:
                title = str(report.get("title") or "")
                # 研报过滤：只保存产业链相关报告
                if not should_save(title):
                    continue
                inst_csname = str(report.get("inst_csname") or "")
                author = str(report.get("author") or "")
                url = str(report.get("url") or "")
                ts_code_val = _norm_ts_code(report.get("ts_code"))

                ann_id: str | None = None
                if url:
                    try:
                        pdf_part = url.split("/")[-1].split("?")[0]
                        if pdf_part:
                            ann_id = f"ms_report_{pdf_part}"
                    except Exception:
                        ann_id = None
                if not ann_id:
                    ann_id = _stable_id("ms_report", date_str, title, inst_csname)

                candidates.append(
                    {
                        "ann_id": ann_id,
                        "ts_code": ts_code_val,
                        "title": title,
                        "inst_csname": inst_csname,
                        "author": author,
                        "url": url,
                    }
                )

            candidate_ids = [c["ann_id"] for c in candidates]
            existing: set[str] = set()
            if candidate_ids:
                try:
                    async with engine.connect() as conn:
                        rows = await conn.execute(
                            text("SELECT file_name FROM research_report_meta WHERE file_name = ANY(:ids)"),
                            {"ids": candidate_ids},
                        )
                        existing = {r[0] for r in rows.fetchall()}
                except Exception as exc:
                    logger.warning("研报预查询失败: %s", exc)

            day_success = day_skipped = day_fail = day_downloaded = 0
            for c in candidates:
                if c["ann_id"] in existing:
                    day_skipped += 1
                    continue

                # 下载 PDF 到外部存储
                file_path = None
                if download_pdf and c["url"]:
                    safe_title = c["title"][:50].replace("/", "_").replace(" ", "")
                    if not safe_title.lower().endswith(".pdf"):
                        safe_title += ".pdf"
                    filename = f"{c['ann_id']}_{safe_title}"
                    file_path = await asyncio.to_thread(
                        self.storage.download_report_external,
                        url=c["url"],
                        ts_code=c["ts_code"],
                        inst_csname=c["inst_csname"],
                        trade_date=date_str,
                        filename=filename,
                    )
                    if file_path is not None:
                        day_downloaded += 1

                saved = await self._save_report(
                    ann_id=c["ann_id"],
                    ts_code=c["ts_code"],
                    title=c["title"],
                    trade_date=date_str,
                    inst_csname=c["inst_csname"],
                    author=c["author"],
                    source_name="minishare",
                )
                if saved is True:
                    day_success += 1
                elif saved is None:
                    day_skipped += 1
                else:
                    day_fail += 1

            total_success += day_success
            total_skipped += day_skipped
            total_fail += day_fail
            total_downloaded += day_downloaded
            last_success_date = date_str

            # 保存断点
            await tracker.save_checkpoint(
                last_success_watermark=date_str,
                last_success_at=datetime.now(UTC),
                last_status="running",
            )
            await tracker.update_run(
                run_ctx,
                current_watermark=date_str,
                total_items=total_days,
                processed_items=total_days,
                success_count=total_success,
                skipped_count=total_skipped,
                downloaded_count=total_downloaded,
                fail_count=total_fail,
            )

            if total_days % 30 == 0:
                await tracker.event(
                    run_ctx,
                    stage="batch_progress",
                    message=f"研报历史同步进度: {date_str}",
                    total_items=total_days,
                    processed_items=total_days,
                    success_count=total_success,
                    skipped_count=total_skipped,
                    downloaded_count=total_downloaded,
                    fail_count=total_fail,
                    item_id=date_str,
                )

        logger.info("minishare 研报历史同步: 正在保存完成状态...")
        try:
            await tracker.finish_run(
                run_ctx,
                status=SUCCESS if total_fail == 0 else PARTIAL,
                total_items=total_days,
                processed_items=total_days,
                success_count=total_success,
                skipped_count=total_skipped,
                downloaded_count=total_downloaded,
                fail_count=total_fail,
                current_watermark=last_success_date,
                last_item_id=last_success_date,
            )
            logger.info("minishare 研报历史同步: finish_run 完成")
        except Exception as exc:
            logger.error("minishare 研报历史同步 finish_run 失败: %s", exc, exc_info=True)

        logger.info(
            "minishare 研报历史同步完成: %s~%s，日期 %d 天，入库 %d，跳过 %d，下载 %d，失败 %d",
            resume_start,
            end_date,
            total_days,
            total_success,
            total_skipped,
            total_downloaded,
            total_fail,
        )
        return {
            "total_days": total_days,
            "success": total_success,
            "skipped": total_skipped,
            "downloaded": total_downloaded,
            "fail": total_fail,
            "source": "minishare",
        }

    # ── 公告（minishare anns_d）───────────────────────────────

    async def fetch_minishare_announcements(
        self,
        ann_date: str | None = None,
        ts_code: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, int]:
        """从 minishare 获取公告数据（单日全市场或按股票代码+日期范围）。

        Args:
            ann_date: 公告日期 YYYYMMDD（与 ts_code 二选一）
            ts_code: 股票代码（配合 start_date/end_date）
            start_date: 起始日期 YYYYMMDD
            end_date: 结束日期 YYYYMMDD
        """
        task_id = generate_task_id()
        set_task_id(task_id)

        if not self.minishare_client.anns_available:
            logger.warning("minishare 公告 token 未配置，跳过")
            return {"success": 0, "skipped": 0, "fail": 0, "source": "minishare"}

        # 默认取昨天
        if not ann_date and not ts_code:
            ann_date = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")

        if ann_date:
            records = self.minishare_client.get_announcements(ann_date=ann_date)
        elif ts_code and start_date and end_date:
            records = self.minishare_client.get_announcements(
                ts_code=ts_code,
                start_date=start_date,
                end_date=end_date,
            )
        else:
            logger.warning("fetch_minishare_announcements 需要 ann_date 或 ts_code+日期范围")
            return {"success": 0, "skipped": 0, "fail": 0, "source": "minishare"}

        success = skipped = fail = 0
        # 白名单过滤：从 candidate_pool 加载活跃股票列表
        # 缓存池股票代码（以 set 形式缓存，避免每次查询数据库）
        if not hasattr(self, "_candidate_pool_cache") or not self._candidate_pool_cache:
            from sqlalchemy import text as sa_text

            from app.core.database import engine as db_engine

            async with db_engine.connect() as conn:
                rows = await conn.execute(
                    sa_text("SELECT ts_code FROM candidate_pool WHERE is_active = true")
                )
                self._candidate_pool_cache = {row[0] for row in rows.fetchall()}

        for rec in records:
            title = str(rec.get("title") or "")
            # 公告过滤：只保存命中关键词的公告
            _, action = classify_ann_title(title)
            if action != ANN_DOC_TYPE_SAVE:
                skipped += 1
                continue
            ts_code_val = _normalize_ts_code(str(rec.get("ts_code") or ""))
            if ts_code_val not in self._candidate_pool_cache:
                skipped += 1
                continue
            ok = await self._save_minishare_ann(rec, ts_code_val)
            if ok is True:
                success += 1
            elif ok is None:
                skipped += 1
            else:
                fail += 1

        logger.info(
            "minishare 公告同步完成: %s，入库 %d，跳过 %d，失败 %d",
            ann_date or f"{ts_code}({start_date}~{end_date})",
            success,
            skipped,
            fail,
        )
        return {"success": success, "skipped": skipped, "fail": fail, "source": "minishare"}

    async def fetch_minishare_ann_history(
        self,
        start_date: str,
        end_date: str,
        task_id: str | None = None,
    ) -> dict[str, int]:
        """从 minishare 批量回填历史公告（按日期遍历，断点续跑）。

        Args:
            start_date: 起始日期 YYYYMMDD
            end_date: 结束日期 YYYYMMDD
            task_id: 可选，API 层传入的任务ID，用于关联 ingestion_runs 表
        """
        internal_task_id = task_id or generate_task_id()
        set_task_id(internal_task_id)

        if not self.minishare_client.anns_available:
            logger.warning("minishare 公告 token 未配置，跳过")
            return {"total_days": 0, "success": 0, "skipped": 0, "fail": 0, "source": "minishare"}

        tracker = IngestionProgressTracker(
            source="minishare_ann",
            task_name="ann_history",
            scope=f"{start_date}_{end_date}",
        )
        await tracker.ensure_tables()

        # 读取 checkpoint
        checkpoint = await tracker.get_checkpoint()
        resume_start = start_date
        if checkpoint and checkpoint.get("last_success_watermark"):
            resume_date = checkpoint["last_success_watermark"]
            resume_next = (datetime.strptime(resume_date, "%Y%m%d") + timedelta(days=1)).strftime("%Y%m%d")
            if resume_next <= end_date:
                resume_start = resume_next
                logger.info(f"公告历史同步断点续跑: 从 {resume_start} 开始（已完成 {resume_date}）")

        run_uuid: uuid.UUID | None = None
        if task_id:
            try:
                run_uuid = uuid.UUID(task_id)
            except ValueError:
                run_uuid = None

        run_ctx = await tracker.start_run(
            from_watermark=resume_start,
            to_watermark=end_date,
            metadata={"source": "minishare"},
            run_id=run_uuid,
        )

        logger.info("开始 minishare 公告历史同步: %s~%s", resume_start, end_date)
        await self.audit_logger.ainfo(
            "fetcher",
            f"minishare 公告历史同步: {resume_start}~{end_date}",
            task_id=internal_task_id,
        )

        total_success = 0
        total_skipped = 0
        total_fail = 0
        total_days = 0
        last_success_date = resume_start

        async for date_str, records in self.minishare_client.iter_ann_by_date_range_async(resume_start, end_date):
            total_days += 1

            if not records:
                await tracker.save_checkpoint(
                    last_success_watermark=date_str,
                    last_success_at=datetime.now(UTC),
                    last_status="running",
                )
                await tracker.update_run(
                    run_ctx,
                    current_watermark=date_str,
                    total_items=total_days,
                    processed_items=total_days,
                )
                last_success_date = date_str
                continue

            day_success = day_skipped = day_fail = 0
            # 白名单过滤：scope=tech_mvp 时仅处理白名单股票公告
            from app.data_pipeline.backfill_config import load_backfill_settings

            bf_cfg = load_backfill_settings()
            for rec in records:
                title = str(rec.get("title") or "")
                # 公告过滤：只保存命中关键词的公告
                _, action = classify_ann_title(title)
                if action != ANN_DOC_TYPE_SAVE:
                    day_skipped += 1
                    continue
                ts_code_val = _normalize_ts_code(str(rec.get("ts_code") or ""))
                if bf_cfg.scope == "tech_mvp" and ts_code_val not in bf_cfg.ts_codes:
                    day_skipped += 1
                    continue
                ok = await self._save_minishare_ann(rec, ts_code_val)
                if ok is True:
                    day_success += 1
                elif ok is None:
                    day_skipped += 1
                else:
                    day_fail += 1

            total_success += day_success
            total_skipped += day_skipped
            total_fail += day_fail
            last_success_date = date_str

            await tracker.save_checkpoint(
                last_success_watermark=date_str,
                last_success_at=datetime.now(UTC),
                last_status="running",
            )
            await tracker.update_run(
                run_ctx,
                current_watermark=date_str,
                total_items=total_days,
                processed_items=total_days,
                success_count=total_success,
                skipped_count=total_skipped,
                fail_count=total_fail,
            )

            if total_days % 30 == 0:
                await tracker.event(
                    run_ctx,
                    stage="batch_progress",
                    message=f"公告历史同步进度: {date_str}",
                    total_items=total_days,
                    processed_items=total_days,
                    success_count=total_success,
                    skipped_count=total_skipped,
                    fail_count=total_fail,
                    item_id=date_str,
                )

        await tracker.finish_run(
            run_ctx,
            status=SUCCESS if total_fail == 0 else PARTIAL,
            total_items=total_days,
            processed_items=total_days,
            success_count=total_success,
            skipped_count=total_skipped,
            downloaded_count=0,
            fail_count=total_fail,
            current_watermark=last_success_date,
            last_item_id=last_success_date,
        )

        logger.info(
            "minishare 公告历史同步完成: %s~%s，日期 %d 天，入库 %d，跳过 %d，失败 %d",
            resume_start,
            end_date,
            total_days,
            total_success,
            total_skipped,
            total_fail,
        )
        return {
            "total_days": total_days,
            "success": total_success,
            "skipped": total_skipped,
            "fail": total_fail,
            "source": "minishare",
        }

    @staticmethod
    def _resolve_minishare_pdf_url(url: str) -> str | None:
        """从 minishare 的 cninfo 详情页 URL 直接构造 PDF 直链。

        当 FileStorage._resolve_pdf_url 的 API 调用失败时，
        直接从 URL 参数中提取 announcementId 和 announcementTime 构造 PDF 地址。
        """
        if not url or "detail" not in url or "cninfo" not in url:
            return None
        try:
            from urllib.parse import parse_qs, urlparse
            parsed = urlparse(url)
            qs = parse_qs(parsed.query)
            ann_id = qs.get("announcementId", [None])[0]
            ann_time = qs.get("announcementTime", [None])[0]
            if ann_id and ann_time:
                return f"http://static.cninfo.com.cn/finalpage/{ann_time}/{ann_id}.PDF"
        except Exception:
            pass
        return None

    async def _save_minishare_ann(
        self,
        rec: dict[str, Any],
        ts_code: str,
        skip_download: bool = False,
    ) -> bool | None:
        """保存 minishare 公告记录；True=成功，None=已存在，False=失败。

        只保存命中关键词的公告（业绩报告、投资者关系、重大资产重组等），
        其余静默跳过（不报错、不计入）。
        """
        ann_date = rec.get("ann_date") or ""
        title = rec.get("title") or ""
        if not ann_date or not title:
            return None  # 静默跳过空标题

        # 公告过滤：只保留需要下载的文档类型
        doc_type, action = classify_ann_title(title)
        if action != ANN_DOC_TYPE_SAVE:
            return None  # 静默跳过不命中的公告

        try:
            # 转换日期格式 YYYYMMDD -> DATE
            date_val = datetime.strptime(ann_date, "%Y%m%d").date() if ann_date else None
            url = rec.get("url") or ""

            async with engine.begin() as conn:
                result = await conn.execute(
                    text("""
                        INSERT INTO minishare_announcements
                            (ann_date, ts_code, name, title, type, ann_types, source_url, source_type, download_status)
                        VALUES
                            (:ann_date, :ts_code, :name, :title, :ann_type, :ann_types, :source_url, :source_type, 'pending')
                        ON CONFLICT (ann_date, ts_code, title) DO NOTHING
                        RETURNING ts_code, ann_date, title
                    """),
                    {
                        "ann_date": date_val,
                        "ts_code": ts_code or None,
                        "name": rec.get("name") or "",
                        "title": title,
                        "ann_type": doc_type,
                        "ann_types": doc_type,
                        "source_url": url,
                        "source_type": "minishare",
                    },
                )
                row = result.fetchone()

            if not row:
                return None  # 已存在

            # 保存元数据后，立即下载 PDF（除非 skip_download=True）
            if url and not skip_download:
                await self._download_minishare_pdf(
                    url=url,
                    ts_code=ts_code,
                    title=title,
                    ann_date=ann_date,
                    doc_type=doc_type,
                )

            return True
        except IntegrityError:
            return None
        except Exception as e:
            logger.warning("保存公告失败: %s", e)
            return False

    async def _download_minishare_pdf(
        self,
        url: str,
        ts_code: str,
        title: str,
        ann_date: str,
        doc_type: str,
    ) -> bool:
        """下载 minishare 公告 PDF，失败后重试 1 次，更新 file_path 和 download_status。"""
        if not url:
            return False

        safe_title = re.sub(r'[\\/:*?"<>|]', "_", title)[:80]
        filename = f"{ann_date}_{ts_code}_{safe_title}.pdf"

        # 解析 cninfo 详情页 URL → 真实 PDF 直链
        resolved_url = await asyncio.to_thread(FileStorage._resolve_pdf_url, url)
        if not resolved_url:
            # 回退方案：直接从 URL 参数构造 PDF 直链
            resolved_url = await asyncio.to_thread(self._resolve_minishare_pdf_url, url)
        if not resolved_url:
            logger.warning("minishare 公告 PDF URL 无法解析 [%s]: %s", title[:50], url[:80])
            await self._update_ann_download_status(ts_code, ann_date, title, "failed")
            return False

        for attempt in range(2):  # 首次 + 重试 1 次
            try:
                # 下载 PDF（投递到线程池避免阻塞）
                response = await asyncio.to_thread(
                    requests.get, resolved_url, timeout=30, headers=HTTP_HEADERS
                )
                response.raise_for_status()
                content = response.content

                if not content[:5] == b"%PDF-":
                    logger.warning(
                        "minishare 公告内容不是 PDF [%s] (attempt %d)", title[:50], attempt + 1
                    )
                    continue  # 重试

                file_path = self.storage.save_notice(content, ts_code, filename, ann_date)
                if not file_path:
                    continue  # 重试

                # 更新数据库
                await self._update_ann_file_path(
                    ts_code, ann_date, title, str(file_path), "downloaded"
                )
                return True

            except Exception as e:
                logger.warning(
                    "minishare 公告 PDF 下载失败 [%s] (attempt %d): %s",
                    title[:50], attempt + 1, e,
                )
                if attempt == 0:
                    continue  # 重试 1 次
                # 第二次也失败，标记 failed
                await self._update_ann_download_status(ts_code, ann_date, title, "failed")
                return False

        # 两次都失败
        await self._update_ann_download_status(ts_code, ann_date, title, "failed")
        return False

    async def _update_ann_file_path(
        self,
        ts_code: str,
        ann_date: str,
        title: str,
        file_path: str,
        status: str,
    ) -> None:
        """更新公告的 file_path 和 download_status。"""
        from datetime import datetime as dt
        date_val = dt.strptime(ann_date, "%Y%m%d").date() if ann_date else None
        async with engine.begin() as conn:
            await conn.execute(
                text("""
                    UPDATE minishare_announcements
                    SET file_path = :file_path, download_status = :status
                    WHERE ts_code = :ts_code AND ann_date = :ann_date AND title = :title
                """),
                {
                    "file_path": file_path,
                    "status": status,
                    "ts_code": ts_code,
                    "ann_date": date_val,
                    "title": title,
                },
            )

    async def _update_ann_download_status(
        self,
        ts_code: str,
        ann_date: str,
        title: str,
        status: str,
    ) -> None:
        """更新公告的 download_status。"""
        from datetime import datetime as dt
        date_val = dt.strptime(ann_date, "%Y%m%d").date() if ann_date else None
        async with engine.begin() as conn:
            await conn.execute(
                text("""
                    UPDATE minishare_announcements
                    SET download_status = :status
                    WHERE ts_code = :ts_code AND ann_date = :ann_date AND title = :title
                """),
                {
                    "status": status,
                    "ts_code": ts_code,
                    "ann_date": date_val,
                    "title": title,
                },
            )

    async def _save_report(
        self,
        ann_id: str,
        ts_code: str,
        title: str,
        trade_date: str,
        inst_csname: str,
        author: str,
        source_name: str = "akshare",
    ) -> bool | None:
        """保存研报元数据；True=成功，None=已存在，False=失败。"""
        sql = """
        INSERT INTO research_report_meta (
            trade_date, ts_code, file_name, author, inst_csname,
            source_type, source_name, confidence_tier
        ) VALUES (
            :trade_date, :ts_code, :file_name, :author, :inst_csname,
            :source_type, :source_name, :confidence_tier
        )
        ON CONFLICT (trade_date, file_name) DO UPDATE SET
            ts_code = EXCLUDED.ts_code,
            author = EXCLUDED.author,
            inst_csname = EXCLUDED.inst_csname
        """
        parsed_date = _yyyymmdd_to_date(trade_date)
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    text(sql),
                    {
                        "trade_date": parsed_date,
                        "ts_code": ts_code or None,
                        "file_name": ann_id,
                        "author": author or None,
                        "inst_csname": inst_csname or None,
                        "source_type": "research_report",
                        "source_name": source_name,
                        "confidence_tier": "Tier4",
                    },
                )
            return True
        except IntegrityError:
            return None
        except Exception as exc:
            logger.warning("保存研报失败 [%s]: %s", ann_id, exc)
            return False

    # ---------- 互动易 ----------

    async def fetch_irm(
        self,
        ts_codes: list[str] | None = None,
        extract_to_kg: bool = False,
    ) -> dict[str, int]:
        return await self._fetch_irm_impl(ts_codes=ts_codes, extract_to_kg=extract_to_kg)

    async def _fetch_irm_impl(
        self,
        ts_codes: list[str] | None = None,
        extract_to_kg: bool = False,
    ) -> dict[str, int]:
        """抓取互动易 Q&A，并发节流入库（Phase 31 I：MongoDB checkpoint 断点续抓）。"""
        task_id = generate_task_id()
        set_task_id(task_id)

        if not self.minishare_client.irm_available:
            requested = len(ts_codes or []) or 1
            error = "MINISHARE_IRM_TOKEN 未配置或 minishare 包未安装"
            logger.error(error)
            return {
                "total": requested,
                "processed": 0,
                "success": 0,
                "fail": requested,
                "skipped": 0,
                "duplicates": 0,
                "invalid": 0,
                "fetched_records": 0,
                "last_error": error,
                "source": "minishare",
            }
        await self._ensure_irm_checkpoint_index()

        # 默认范围由 backfill_config 决定（scope=tech_mvp 时仅白名单股票）
        from app.data_pipeline.backfill_config import load_backfill_settings

        bf_cfg = load_backfill_settings()
        requested_scope = "all_market" if ts_codes is None else ",".join(ts_codes[:5])
        if ts_codes is None:
            # 股票列表从 candidate_pool 读取（target pool：半导体/光模块/AI算力主题池）
            async with engine.connect() as conn:
                _r = await conn.execute(text("SELECT ts_code FROM candidate_pool WHERE is_active = true ORDER BY ts_code"))
                ts_codes = [row[0] for row in _r.fetchall()]
            if bf_cfg.scope == "tech_mvp" and bf_cfg.ts_codes:
                before = len(ts_codes)
                ts_codes = [c for c in ts_codes if c in bf_cfg.ts_codes]
                logger.info(
                    "fetch_irm: backfill scope=tech_mvp, %d/%d 命中白名单",
                    len(ts_codes),
                    before,
                )
                requested_scope = f"tech_mvp({len(ts_codes)})"
        elif len(ts_codes) > 5:
            requested_scope = f"{len(ts_codes)}_companies"

        raw_total = len(ts_codes)
        # I 核心：过滤 20h 窗口内已成功的
        ts_codes = await self._filter_irm_pending(ts_codes)
        total = len(ts_codes)
        tracker = IngestionProgressTracker(
            source="irm",
            task_name="qa_fetch",
            scope=requested_scope,
        )
        run_ctx = await tracker.start_run(
            metadata={
                "extract_to_kg": extract_to_kg,
                "raw_total_companies": raw_total,
                "checkpoint_skipped_companies": raw_total - total,
                "requested_scope": requested_scope,
            },
        )
        logger.info(
            "开始获取互动易: %d 只（原 %d，checkpoint 跳过 %d）",
            total,
            raw_total,
            raw_total - total,
        )

        semaphore = asyncio.Semaphore(IRM_CONCURRENCY)
        counter_lock = asyncio.Lock()
        counters = {
            "processed": 0,
            "success": 0,
            "fail": 0,
            "skipped": 0,
            "duplicates": 0,
            "invalid": 0,
            "fetched_records": 0,
            "last_error": "",
        }

        async def worker(code: str) -> None:
            async with semaphore:
                try:
                    end_date = datetime.now(SH_TZ).strftime("%Y%m%d")
                    start_date = (datetime.now(SH_TZ) - timedelta(days=7)).strftime("%Y%m%d")
                    records = await asyncio.to_thread(
                        self.minishare_client.get_irm,
                        code,
                        start_date,
                        end_date,
                    )
                except Exception as exc:
                    logger.debug("互动易 %s 抓取异常: %s", code, exc)
                    async with counter_lock:
                        counters["processed"] += 1
                        counters["fail"] += 1
                        counters["last_error"] = str(exc)
                        snapshot = dict(counters)
                    await tracker.update_run(
                        run_ctx,
                        total_items=total,
                        processed_items=snapshot["processed"],
                        success_count=snapshot["success"],
                        skipped_count=snapshot["skipped"] + snapshot["duplicates"] + snapshot["invalid"],
                        fail_count=snapshot["fail"],
                        last_item_id=code,
                        last_error=str(exc),
                    )
                    await tracker.event(
                        run_ctx,
                        stage="company_error",
                        message="互动易公司抓取失败",
                        total_items=total,
                        processed_items=snapshot["processed"],
                        success_count=snapshot["success"],
                        skipped_count=snapshot["skipped"] + snapshot["duplicates"] + snapshot["invalid"],
                        fail_count=snapshot["fail"],
                        item_id=code,
                        error=str(exc),
                    )
                    await self._save_irm_checkpoint(code, success=False)
                    return

                saved = duplicate = invalid = 0
                for rec in records:
                    ok = await self._save_irm_record(code, rec)
                    if ok is True:
                        saved += 1
                    elif ok is None:
                        duplicate += 1
                    else:
                        invalid += 1
                no_data = 1 if not records else 0
                async with counter_lock:
                    counters["processed"] += 1
                    counters["success"] += saved
                    counters["duplicates"] += duplicate
                    counters["invalid"] += invalid
                    counters["fetched_records"] += len(records)
                    if no_data:
                        counters["skipped"] += 1
                    snapshot = dict(counters)

                # 记录 checkpoint（WARNING 5 修正）：
                # success = 入库有成果 or 确实无数据（而非无条件 True）
                checkpoint_success = (saved > 0) or (len(records) == 0)
                await self._save_irm_checkpoint(code, success=checkpoint_success)
                visible_skipped = snapshot["skipped"] + snapshot["duplicates"] + snapshot["invalid"]
                await tracker.update_run(
                    run_ctx,
                    total_items=total,
                    processed_items=snapshot["processed"],
                    success_count=snapshot["success"],
                    skipped_count=visible_skipped,
                    fail_count=snapshot["fail"],
                    last_item_id=code,
                )
                if (
                    snapshot["processed"] % IRM_PROGRESS_EVERY == 0
                    or snapshot["processed"] == total
                    or total <= IRM_PROGRESS_EVERY
                ):
                    await tracker.event(
                        run_ctx,
                        stage="company_done",
                        message="互动易公司处理进展",
                        total_items=total,
                        processed_items=snapshot["processed"],
                        success_count=snapshot["success"],
                        skipped_count=visible_skipped,
                        fail_count=snapshot["fail"],
                        item_id=code,
                        metadata={
                            "records_fetched": len(records),
                            "records_saved": saved,
                            "duplicates": duplicate,
                            "invalid": invalid,
                            "no_data": bool(no_data),
                            "fetched_records_total": snapshot["fetched_records"],
                        },
                    )

                # 抖动，避免扎堆
                await asyncio.sleep(IRM_SLEEP_BASE + random.random() * IRM_SLEEP_JITTER)

        await asyncio.gather(*(worker(c) for c in ts_codes))

        logger.info(
            "互动易完成: 入库 %d，失败 %d，无数据 %d",
            counters["success"],
            counters["fail"],
            counters["skipped"],
        )
        result = {
            "total": total,
            "success": counters["success"],
            "fail": counters["fail"],
            "skipped": counters["skipped"],
            "duplicates": counters["duplicates"],
            "invalid": counters["invalid"],
            "fetched_records": counters["fetched_records"],
        }
        if counters["last_error"]:
            result["last_error"] = counters["last_error"]
        if extract_to_kg and ts_codes:
            try:
                from app.data_pipeline.irm_pipeline import process_irm_batch

                await tracker.event(
                    run_ctx,
                    stage="kg_start",
                    message="互动易知识构建开始",
                    total_items=total,
                    processed_items=counters["processed"],
                    success_count=counters["success"],
                    skipped_count=counters["skipped"] + counters["duplicates"] + counters["invalid"],
                    fail_count=counters["fail"],
                )
                kg_result = await process_irm_batch(ts_codes)
                result["kg_companies"] = kg_result.get("companies", 0)
                result["kg_entities"] = kg_result.get("entities", 0)
                result["kg_relations"] = kg_result.get("relations", 0)
                db = get_mongo_db()
                await db[IRM_CHECKPOINT_COLLECTION].update_one(
                    {"_id": "irm_kg"},
                    {
                        "$set": {
                            "last_extraction_at": datetime.now(UTC),
                            "stats": kg_result,
                        }
                    },
                    upsert=True,
                )
                logger.info("互动易 KG 构建完成: %s", kg_result)
                await tracker.event(
                    run_ctx,
                    stage="kg_done",
                    message="互动易知识构建完成",
                    total_items=total,
                    processed_items=counters["processed"],
                    success_count=counters["success"],
                    skipped_count=counters["skipped"] + counters["duplicates"] + counters["invalid"],
                    fail_count=counters["fail"],
                    metadata=kg_result,
                )
            except Exception as exc:  # noqa: BLE001
                result["kg_fail"] = 1
                logger.warning("互动易 KG 构建失败: %s", exc)
                await tracker.event(
                    run_ctx,
                    stage="kg_error",
                    message="互动易知识构建失败",
                    total_items=total,
                    processed_items=counters["processed"],
                    success_count=counters["success"],
                    skipped_count=counters["skipped"] + counters["duplicates"] + counters["invalid"],
                    fail_count=counters["fail"],
                    error=str(exc),
                )
        final_status = (
            FAILED if counters["fail"] and not counters["success"] else (PARTIAL if counters["fail"] else SUCCESS)
        )
        await tracker.finish_run(
            run_ctx,
            status=final_status,
            total_items=total,
            processed_items=counters["processed"],
            success_count=counters["success"],
            skipped_count=counters["skipped"] + counters["duplicates"] + counters["invalid"],
            downloaded_count=0,
            fail_count=counters["fail"],
            last_item_id=ts_codes[-1] if ts_codes else None,
            metadata={
                "extract_to_kg": extract_to_kg,
                "raw_total_companies": raw_total,
                "checkpoint_skipped_companies": raw_total - total,
                "duplicates": counters["duplicates"],
                "invalid": counters["invalid"],
                "fetched_records": counters["fetched_records"],
                "kg": {k: v for k, v in result.items() if k.startswith("kg_")},
            },
        )
        return result

    async def fetch_irm_with_kg(self, ts_codes: list[str] | None = None) -> dict[str, int]:
        return await self._fetch_irm_impl(ts_codes=ts_codes, extract_to_kg=True)

    async def _save_irm_record(self, ts_code: str, rec: dict[str, Any]) -> bool | None:
        question = str(rec.get("question") or "").strip()
        answer = str(rec.get("answer") or "").strip()
        if not question or not answer:
            return False

        question_time = str(rec.get("question_time") or "").strip()
        exchange = str(rec.get("exchange") or "").strip().upper() or "UNK"

        # 解析中文日期格式: "2026年05月08日 09:00" -> date
        import re
        from datetime import date as date_type

        ann_date_obj = datetime.now(SH_TZ).date()
        parsed = False
        if question_time:
            m = re.match(r"(\d{4})年(\d{1,2})月(\d{1,2})日", question_time)
            if m:
                ann_date_obj = date_type(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                parsed = True
            else:
                m2 = re.match(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", question_time)
                if m2:
                    ann_date_obj = date_type(int(m2.group(1)), int(m2.group(2)), int(m2.group(3)))
                    parsed = True
        if not parsed:
            trade_date_str = str(rec.get("trade_date") or "").strip()
            if len(trade_date_str) == 8 and trade_date_str.isdigit():
                ann_date_obj = date_type(int(trade_date_str[:4]), int(trade_date_str[4:6]), int(trade_date_str[6:8]))

        # ann_id 叠加 question hash + 解析后日期（用 date 而非原始 question_time，避免 trade_date 格式抖动导致重复）
        q_hash = hashlib.md5(question.encode("utf-8", errors="replace")).hexdigest()[:10]
        ann_id = _stable_id("irm", exchange, ts_code, str(ann_date_obj), q_hash)

        sql = """
        INSERT INTO announcements (
            ann_date, ts_code, name, title, type,
            cninfo_id, announcement_type,
            source_type, source_name, confidence_tier
        ) VALUES (
            :ann_date, :ts_code, :name, :title, :type,
            :cninfo_id, :announcement_type,
            :source_type, :source_name, :confidence_tier
        )
        ON CONFLICT (cninfo_id) DO NOTHING
        """
        try:
            async with engine.begin() as conn:
                result = await conn.execute(
                    text(sql),
                    {
                        "ann_date": ann_date_obj,
                        "ts_code": ts_code,
                        "name": rec.get("stock_name") or None,
                        "title": question[:500],
                        "type": answer,
                        "cninfo_id": ann_id,
                        "announcement_type": f"irm:{exchange}",
                        "source_type": "irm",
                        "source_name": f"互动易-{exchange}",
                        "confidence_tier": "Tier2",
                    },
                )
            return True if result.rowcount and result.rowcount > 0 else None
        except IntegrityError:
            return None
        except Exception as exc:
            logger.warning("保存互动易失败 [%s]: %s", ann_id, exc)
            return False

    # ---------- Phase 31 I: IRM MongoDB checkpoint ----------

    async def _ensure_irm_checkpoint_index(self) -> None:
        """确保 irm_checkpoint collection 有 unique index（启动时一次，幂等）。"""
        try:
            db = get_mongo_db()
            col = db[IRM_CHECKPOINT_COLLECTION]
            await col.create_index("ts_code", unique=True)
            await col.create_index("last_success_at")
        except Exception as exc:
            logger.warning("irm_checkpoint 索引创建失败（继续）: %s", exc)

    async def _filter_irm_pending(self, ts_codes: list[str]) -> list[str]:
        """过滤掉 IRM_CHECKPOINT_WINDOW_HOURS 小时内已成功的 ts_code（I 核心）。"""
        if not ts_codes:
            return []
        try:
            db = get_mongo_db()
            # P1 修复：使用北京时间，保持 checkpoint 窗口一致性
            cutoff = datetime.now(SH_TZ) - timedelta(hours=IRM_CHECKPOINT_WINDOW_HOURS)
            cursor = db[IRM_CHECKPOINT_COLLECTION].find(
                {
                    "ts_code": {"$in": ts_codes},
                    "last_success_at": {"$gt": cutoff},
                },
                {"ts_code": 1, "_id": 0},
            )
            done_set = {doc["ts_code"] async for doc in cursor}
            if done_set:
                logger.info(
                    "IRM checkpoint 跳过 %d/%d 只（%dh 窗口内已成功）",
                    len(done_set),
                    len(ts_codes),
                    IRM_CHECKPOINT_WINDOW_HOURS,
                )
            return [c for c in ts_codes if c not in done_set]
        except Exception as exc:
            logger.warning("IRM checkpoint 过滤失败，回退全量: %s", exc)
            return ts_codes

    async def _save_irm_checkpoint(self, ts_code: str, success: bool) -> None:
        """更新 irm_checkpoint：success=True 写 last_success_at，否则仅 last_attempt_at。"""
        try:
            db = get_mongo_db()
            # P1 修复：使用北京时间，与 _filter_irm_pending 保持一致
            now = datetime.now(SH_TZ)
            update: dict[str, Any] = {"last_attempt_at": now}
            if success:
                update["status"] = "done"
                update["last_success_at"] = now
            else:
                update["status"] = "retry"
            await db[IRM_CHECKPOINT_COLLECTION].update_one(
                {"ts_code": ts_code},
                {"$set": update},
                upsert=True,
            )
        except Exception as exc:
            logger.warning("IRM checkpoint 写入失败 [%s]: %s", ts_code, exc)

    # ---------- 巨潮公告（cninfo） ----------

async def fetch_concept() -> dict[str, int]:
    """获取概念板块涨停统计（tinyshare limit_list_d + ths_concept_members 映射）。

    替代原 akshare ``stock_zt_pool_strong_em`` 方案：
    1. tinyshare ``limit_list_d(trade_date=今天, limit_type="U")`` 拿涨停股
    2. ``ths_concept_members`` 表将涨停股映射到 THS 概念（TI 格式，与知识层对齐）
    3. 按概念聚合涨停家数写入 ``concept_limit``
    """
    from app.config import settings

    token = settings.tushare_token
    if not token:
        logger.warning("TUSHARE_TOKEN 未配置，跳过概念同步")
        return {"success": 0, "skipped": 1, "fail": 0}

    try:
        import tinyshare as ts
    except ImportError:
        logger.error("tinyshare 未安装，跳过概念同步")
        return {"success": 0, "skipped": 0, "fail": 1}

    today = datetime.now().strftime("%Y%m%d")
    try:
        ts.set_token(token)
        pro = ts.pro_api()
        # tinyshare 兼容 tushare SDK；优先 typed 方法，回退通用 query 接口
        fetcher_fn = getattr(pro, "limit_list_d", None) or (
            lambda **kw: pro.query("limit_list_d", **kw)
        )
        limit_df = await asyncio.to_thread(fetcher_fn, trade_date=today, limit_type="U")
    except Exception as exc:
        logger.warning("tinyshare limit_list_d 获取涨停股失败，跳过概念同步: %s", exc)
        return {"success": 0, "skipped": 0, "fail": 1}

    if limit_df is None or len(limit_df) == 0:
        logger.info("今日无涨停股，跳过概念同步")
        return {"success": 0, "skipped": 1, "fail": 0}

    limit_codes = [str(r.get("ts_code") or "").strip() for _, r in limit_df.iterrows()]
    limit_codes = [c for c in limit_codes if c]
    if not limit_codes:
        logger.info("今日涨停股无 ts_code，跳过概念同步")
        return {"success": 0, "skipped": 1, "fail": 0}

    # 涨停股 → THS 概念映射（ths_concept_members.con_code 与 ts_code 同为带交易所后缀格式）
    placeholders = ", ".join(f":c{i}" for i in range(len(limit_codes)))
    params = {f"c{i}": c for i, c in enumerate(limit_codes)}
    sql = f"""
        SELECT tcm.ts_code AS concept_code, tc.name AS concept_name
        FROM ths_concept_members tcm
        JOIN ths_concepts tc ON tc.ts_code = tcm.ts_code
        WHERE tcm.con_code IN ({placeholders})
    """
    async with engine.connect() as conn:
        result = await conn.execute(text(sql), params)
        rows = result.fetchall()

    concept_counts: dict[str, dict[str, Any]] = {}
    for concept_code, concept_name in rows:
        entry = concept_counts.setdefault(
            concept_code,
            {"count": 0, "pct_chg": 0.0, "name": concept_name or concept_code},
        )
        entry["count"] += 1

    success = fail = 0
    for concept_code, info in concept_counts.items():
        try:
            await _save_concept_limit(
                concept_code=concept_code,
                concept_name=info["name"],
                trade_date=today,
                up_nums=info["count"],
                pct_chg=info["pct_chg"],
            )
            success += 1
        except Exception as exc:
            fail += 1
            logger.warning("保存概念 %s 失败: %s", concept_code, exc)

    logger.info("概念热度同步完成: 入库 %d 个概念", success)
    return {"success": success, "fail": fail, "skipped": 0}


async def _save_concept_limit(
    concept_code: str,
    concept_name: str,
    trade_date: str,
    up_nums: int,
    pct_chg: float,
) -> None:
    parsed_date = _yyyymmdd_to_date(trade_date)
    if parsed_date is None:
        return

    sql = """
    INSERT INTO concept_limit (
        concept_code, concept_name, trade_date, up_nums, pct_chg
    ) VALUES (
        :concept_code, :concept_name, :trade_date, :up_nums, :pct_chg
    )
    ON CONFLICT (concept_code, trade_date) DO UPDATE SET
        up_nums = EXCLUDED.up_nums,
        pct_chg = EXCLUDED.pct_chg,
        concept_name = EXCLUDED.concept_name
    """
    async with engine.begin() as conn:
        await conn.execute(
            text(sql),
            {
                "concept_code": concept_code,
                "concept_name": concept_name,
                "trade_date": parsed_date,
                "up_nums": up_nums,
                "pct_chg": pct_chg,
            },
        )
