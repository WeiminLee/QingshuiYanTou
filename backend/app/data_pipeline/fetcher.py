"""
DataFetcher - 数据获取服务

协调 DataSourceClient 抓数 + PostgreSQL 入库 + 文件落盘。
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import math
import random
from datetime import date, datetime, timedelta, timezone
from functools import partial
from pathlib import Path
from typing import Any, Iterable, Optional

import pytz
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.core.database import engine
from app.core.mongodb import get_mongo_db
from app.data_pipeline.announcement_filter import (
    DOC_TYPE_SAVE,
    classify_title,
    get_doc_type,
    should_download,
)
from app.data_pipeline.cninfo_client import CninfoClient
from app.data_pipeline.data_source import DataSourceClient
from app.data_pipeline.minishare_client import DataSourceClientMinishare
from app.data_pipeline.file_storage import FileStorage
from app.data_pipeline.progress import (
    FAILED,
    PARTIAL,
    SUCCESS,
    IngestionProgressTracker,
)
from app.data_pipeline.rate_limiter import (
    get_akshare_limiter,
)
from app.logging.logger import AsyncAuditLogger, generate_task_id, set_task_id

logger = logging.getLogger(__name__)


# ── 常量 ───────────────────────────────────────────────

IRM_CONCURRENCY = 4                # 互动易并发抓取度（保护接口 & 避免被反爬）
IRM_SLEEP_BASE = 1.0               # 每只股票最小间隔（秒）
IRM_SLEEP_JITTER = 1.0             # 附加随机抖动
IRM_PROGRESS_EVERY = 10            # 互动易接入进度事件节流
CONCEPT_CODE_PREFIX = "CN_"        # 自造概念板块代码前缀，避免与 THS TI 代码冲突
CNINFO_PROGRESS_EVERY = 50

# Phase 31 D-A2/A5 — 全市场个股 K 线采集
STOCK_KLINE_CONCURRENCY = 8           # baostock 服务端可承受的并发（保守值，可 4-16 调整）
STOCK_KLINE_SLEEP_BASE = 0.3          # worker 内 sleep 基线（秒）
STOCK_KLINE_SLEEP_JITTER = 0.4        # worker sleep 随机抖动上限
STOCK_KLINE_RECONNECT_EVERY = 500     # 每 N 只重连一次（防 baostock 长连接 broken pipe）
STOCK_KLINE_BACKFILL_DAYS = 30        # 首次回填窗口（D-A5：agent 分析常用窗口）

# Phase 31 I: IRM MongoDB checkpoint
IRM_CHECKPOINT_COLLECTION = "irm_checkpoint"
IRM_CHECKPOINT_WINDOW_HOURS = 20   # 20 小时内成功过的 ts_code 跳过

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

    def __init__(self) -> None:
        self.data_source = DataSourceClient()
        self.storage = FileStorage()
        self.cninfo_client = CninfoClient()
        self.audit_logger = AsyncAuditLogger("data_pipeline")
        self.minishare_client = DataSourceClientMinishare()

    # ---------- 研报 ----------

    async def fetch_reports(self, trade_date: str | None = None) -> dict[str, int]:
        """获取研报并入库（Phase 31 G：EXISTS 预查询跳过已存在 ann_id，减少 PDF 下载 IO）。"""
        task_id = generate_task_id()
        set_task_id(task_id)

        if trade_date is None:
            trade_date = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")

        logger.info("开始获取研报: %s", trade_date)
        await self.audit_logger.ainfo("fetcher", f"开始获取研报: {trade_date}", task_id=task_id, trade_date=trade_date)
        # Phase 31 D-D2: akshare 限速 + 同步→异步桥接
        await asyncio.to_thread(get_akshare_limiter().wait_and_acquire)
        reports = await asyncio.to_thread(self.data_source.get_reports, trade_date)

        # ── G 修复第 1 步：收集 candidates + ann_id ──
        candidates: list[dict[str, Any]] = []
        for report in reports:
            title = str(report.get("title") or "")
            inst_csname = str(report.get("inst_csname") or "")
            author = str(report.get("author") or "")
            url = str(report.get("url") or "")
            ts_code = _norm_ts_code(report.get("ts_code"))

            ann_id: str | None = None
            if url and "pdf.dfcfw.com" in url:
                try:
                    pdf_part = url.split("/")[-1].split("?")[0]
                    if pdf_part:
                        ann_id = f"report_{pdf_part}"
                except Exception:
                    ann_id = None
            if not ann_id:
                ann_id = _stable_id("report", trade_date, title, inst_csname)

            candidates.append({
                "ann_id": ann_id,
                "ts_code": ts_code,
                "title": title,
                "inst_csname": inst_csname,
                "author": author,
                "url": url,
            })

        # ── G 修复第 2 步：批量 EXISTS 预查询 ──
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
                logger.warning("研报 EXISTS 预查询失败，回退到逐条 ON CONFLICT 流程: %s", exc)

        # ── G 修复第 3 步：循环只处理新增 ──
        total = len(candidates)
        success = skipped = fail = 0
        for c in candidates:
            if c["ann_id"] in existing:
                skipped += 1
                continue

            file_path: Path | None = None
            if c["url"]:
                safe_title = c["title"][:50].replace("/", "_").replace(" ", "")
                if not safe_title.lower().endswith(".pdf"):
                    safe_title += ".pdf"
                filename = f"{c['ann_id']}_{safe_title}"
                # Phase 31 CR-02 fix: offload synchronous FileStorage.download_report to thread pool
                file_path = await asyncio.to_thread(
                    self.storage.download_report,
                    url=c["url"],
                    ts_code=c["ts_code"],
                    inst_csname=c["inst_csname"],
                    trade_date=trade_date,
                    filename=filename,
                )

            saved = await self._save_report(
                ann_id=c["ann_id"],
                ts_code=c["ts_code"],
                title=c["title"],
                trade_date=trade_date,
                inst_csname=c["inst_csname"],
                author=c["author"],
            )
            if saved is True:
                success += 1
            elif saved is None:
                skipped += 1
            else:
                fail += 1
            logger.debug("研报入库: [%s] %s", c["ts_code"] or "_industry", c["title"][:40])

        logger.info(
            "研报获取完成: 总 %d，预跳过 %d，总跳过 %d，新增 %d，失败 %d",
            total, len(existing), skipped, success, fail,
        )
        return {"total": total, "success": success, "skipped": skipped, "fail": fail}

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

            candidates.append({
                "ann_id": ann_id,
                "ts_code": ts_code_val,
                "title": title,
                "inst_csname": inst_csname,
                "author": author,
                "url": url,
            })

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
            total, success, skipped, fail,
        )
        return {"total": total, "success": success, "skipped": skipped, "fail": fail, "source": "minishare"}

    async def fetch_minishare_irm(
        self,
        trade_date: str | None = None,
    ) -> dict[str, int]:
        """从 minishare 获取互动易 Q&A 并入库（备选通道）。"""
        task_id = generate_task_id()
        set_task_id(task_id)

        if trade_date is None:
            trade_date = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")

        if not self.minishare_client.irm_available:
            logger.warning("minishare 互动易 token 未配置，跳过")
            return {"total": 0, "success": 0, "skipped": 0, "fail": 0, "source": "minishare"}

        logger.info("开始从 minishare 获取互动易: %s", trade_date)
        await self.audit_logger.ainfo(
            "fetcher",
            f"开始从 minishare 获取互动易: {trade_date}",
            task_id=task_id,
            trade_date=trade_date,
        )

        records = await asyncio.to_thread(
            self.minishare_client.get_irm,
            trade_date=trade_date,
        )

        if not records:
            logger.info("minishare 互动易数据为空")
            return {"total": 0, "success": 0, "skipped": 0, "fail": 0, "source": "minishare"}

        success = skipped = fail = 0
        for rec in records:
            # 复用 _save_irm_record 的逻辑（ts_code 从 stock_code 推断）
            ts_code_raw = _norm_ts_code(rec.get("stock_code") or "")
            if ts_code_raw and "." not in ts_code_raw:
                ts_code = _normalize_ts_code(ts_code_raw)
            else:
                ts_code = ts_code_raw
            ok = await self._save_irm_record(ts_code or "UNKNOWN", rec)
            if ok is True:
                success += 1
            elif ok is None:
                skipped += 1
            else:
                fail += 1

        logger.info(
            "minishare 互动易获取完成: 总 %d，新增 %d，跳过 %d，失败 %d",
            len(records), success, skipped, fail,
        )
        return {"total": len(records), "success": success, "skipped": skipped, "fail": fail, "source": "minishare"}

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
            trade_date, ts_code, file_name, title, author, inst_csname,
            source_type, source_name, confidence_tier
        ) VALUES (
            :trade_date, :ts_code, :file_name, :title, :author, :inst_csname,
            :source_type, :source_name, :confidence_tier
        )
        ON CONFLICT (trade_date, file_name) DO UPDATE SET
            ts_code = EXCLUDED.ts_code,
            title = EXCLUDED.title,
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
                        "title": title,
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
        await self._ensure_irm_checkpoint_index()

        requested_scope = "all_market" if ts_codes is None else ",".join(ts_codes[:5])
        if ts_codes is None:
            all_stocks = self.data_source.get_stocks_basic(list_status="L")
            ts_codes = [s["ts_code"] for s in all_stocks]
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
        logger.info("开始获取互动易: %d 只（原 %d，checkpoint 跳过 %d）",
                    total, raw_total, raw_total - total)

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
        }

        async def worker(code: str) -> None:
            async with semaphore:
                try:
                    # Phase 31 D-D2: akshare 限速（在 semaphore 内，避免 ack 后再等）
                    await asyncio.to_thread(get_akshare_limiter().wait_and_acquire)
                    records = await asyncio.to_thread(self.data_source.get_irm, code)
                except Exception as exc:
                    logger.debug("互动易 %s 抓取异常: %s", code, exc)
                    async with counter_lock:
                        counters["processed"] += 1
                        counters["fail"] += 1
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
            counters["success"], counters["fail"], counters["skipped"],
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
                    {"$set": {
                        "last_extraction_at": datetime.now(timezone.utc),
                        "stats": kg_result,
                    }},
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
        final_status = FAILED if counters["fail"] and not counters["success"] else (PARTIAL if counters["fail"] else SUCCESS)
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

        # ann_id 叠加 question hash 防 (ts_code, question_time) 同秒多问题的冲突
        q_hash = hashlib.md5(question.encode("utf-8", errors="replace")).hexdigest()[:10]
        ann_id = _stable_id("irm", exchange, ts_code, question_time or "-", q_hash)

        # 解析中文日期格式: "2026年05月08日 09:00" -> date
        # P1 修复：使用北京时间，避免凌晨抓取时日期错位
        ann_date_obj = datetime.now(SH_TZ).date()
        if question_time:
            import re
            m = re.match(r"(\d{4})年(\d{1,2})月(\d{1,2})日", question_time)
            if m:
                from datetime import date as date_type
                ann_date_obj = date_type(int(m.group(1)), int(m.group(2)), int(m.group(3)))

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
                    len(done_set), len(ts_codes), IRM_CHECKPOINT_WINDOW_HOURS,
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

    async def _process_announcement_list(
        self,
        announcements: list[dict[str, Any]],
        default_date: str,
        scope: str,
        tracker: IngestionProgressTracker,
        run_ctx: Any,
        *,
        is_history: bool = False,
    ) -> dict[str, int]:
        """共享的公告列表处理逻辑（fetch_announcements / fetch_announcements_history 共用）。

        Returns:
            {"total", "success", "skipped", "downloaded", "fail"}
        """
        total = len(announcements)
        if total == 0:
            await tracker.finish_run(
                run_ctx,
                status=SUCCESS,
                total_items=0,
                processed_items=0,
                success_count=0,
                skipped_count=0,
                downloaded_count=0,
                fail_count=0,
                current_watermark=default_date,
                checkpoint_watermark=default_date,
                next_from_watermark=default_date,
                metadata={"mode": "history" if is_history else "daily_increment", "scope": scope},
            )
            return {"total": 0, "success": 0, "skipped": 0, "downloaded": 0, "fail": 0}

        # ── 预查询：批量过滤已入库 cninfo_id ──
        candidate_ids: list[str] = []
        prepared: list[dict[str, Any]] = []
        for ann in announcements:
            cninfo_id = CninfoClient.get_announcement_id(ann)
            if not cninfo_id:
                continue
            candidate_ids.append(cninfo_id)
            prepared.append({
                "raw": ann,
                "cninfo_id": cninfo_id,
                "title": CninfoClient.get_title(ann),
                "ts_code": CninfoClient.get_ts_code(ann),
                "ann_date_str": CninfoClient.get_ann_date(ann) or default_date,
                "name": str(ann.get("secName", "")),
                "pdf_url": CninfoClient.get_pdf_url(ann),
            })

        existing: dict[str, str | None] = {}
        if candidate_ids:
            try:
                async with engine.connect() as conn:
                    rows = await conn.execute(
                        text(
                            "SELECT cninfo_id, file_path FROM announcements "
                            "WHERE cninfo_id = ANY(:ids)"
                        ),
                        {"ids": candidate_ids},
                    )
                    existing = {r[0]: r[1] for r in rows.fetchall()}
            except Exception as exc:
                logger.warning("公告 cninfo_id 预查询失败: %s", exc)

        success = skipped = downloaded = fail = 0
        for idx, item in enumerate(prepared, start=1):
            doc_type, action = classify_title(item["title"])
            need_download = action == DOC_TYPE_SAVE
            cninfo_id = item["cninfo_id"]

            if cninfo_id in existing:
                skipped += 1
                old_file_path = existing[cninfo_id]
                if old_file_path and Path(old_file_path).exists():
                    pass  # 已入库且本地文件存在，无需处理
                else:
                    if old_file_path:
                        await self._clear_announcement_file_path(cninfo_id)
                    if need_download and item["pdf_url"]:
                        repaired_path = await self._download_announcement_pdf(item)
                        if repaired_path is not None:
                            downloaded += 1
                            updated = await self._update_announcement_file_path(cninfo_id, repaired_path)
                            if updated is True:
                                await self._on_pdf_download_complete(cninfo_id, repaired_path, item["ts_code"], item["title"])
                            elif updated is False:
                                fail += 1
                                await tracker.event(
                                    run_ctx, stage="item_error", message="公告 PDF 路径回写失败",
                                    total_items=total, processed_items=idx,
                                    success_count=success, skipped_count=skipped,
                                    downloaded_count=downloaded, fail_count=fail,
                                    item_id=cninfo_id, item_title=item["title"],
                                )
            else:
                file_path: Path | None = None
                if need_download and item["pdf_url"]:
                    file_path = await self._download_announcement_pdf(item)
                    if file_path is not None:
                        downloaded += 1

                saved = await self._save_announcement(
                    cninfo_id=cninfo_id,
                    ann_date_str=item["ann_date_str"],
                    ts_code=item["ts_code"],
                    name=item["name"],
                    title=item["title"],
                    doc_type=doc_type,
                    pdf_url=item["pdf_url"],
                    file_path=file_path,
                )
                if saved is True:
                    success += 1
                    if file_path is not None:
                        await self._on_pdf_download_complete(cninfo_id, file_path, item["ts_code"], item["title"])
                elif saved is None:
                    skipped += 1
                else:
                    fail += 1
                    await tracker.event(
                        run_ctx, stage="item_error", message="公告元数据入库失败",
                        total_items=total, processed_items=idx,
                        success_count=success, skipped_count=skipped,
                        downloaded_count=downloaded, fail_count=fail,
                        item_id=cninfo_id, item_title=item["title"],
                    )

            if idx % CNINFO_PROGRESS_EVERY == 0 or idx == total:
                await tracker.update_run(
                    run_ctx,
                    total_items=total, processed_items=idx,
                    success_count=success, skipped_count=skipped,
                    downloaded_count=downloaded, fail_count=fail,
                    last_item_id=cninfo_id,
                )
                await tracker.event(
                    run_ctx, stage="process_batch", message="公告处理进展",
                    total_items=total, processed_items=idx,
                    success_count=success, skipped_count=skipped,
                    downloaded_count=downloaded, fail_count=fail,
                    item_id=cninfo_id,
                )

        current_watermark = prepared[-1]["cninfo_id"] if prepared else default_date
        await tracker.finish_run(
            run_ctx,
            status=SUCCESS if fail == 0 else PARTIAL,
            total_items=total,
            processed_items=len(prepared),
            success_count=success,
            skipped_count=skipped,
            downloaded_count=downloaded,
            fail_count=fail,
            current_watermark=current_watermark,
            last_item_id=current_watermark,
            checkpoint_watermark=default_date,
            next_from_watermark=default_date,
            metadata={
                "mode": "history" if is_history else "daily_increment",
                "scope": scope,
                "candidate_count": len(prepared),
            },
        )
        return {
            "total": total,
            "success": success,
            "skipped": skipped,
            "downloaded": downloaded,
            "fail": fail,
        }

    async def fetch_announcements(
        self,
        ann_date: str | None = None,
    ) -> dict[str, int]:
        """从巨潮拉取指定日期的公告，按关键词过滤后入库 / 下载 PDF。

        Plan: 03-02 (phase 03-cninfoclient)
        Decisions: D-02（关键词过滤）、D-03（cninfo_id UNIQUE 去重）、
                   D-04（增量只增不减）、D-06（PDF 下载 1 file/sec）、
                   D-07（复用 announcements 表）

        流程：
        1. ``ann_date`` 为空时取昨天（YYYYMMDD）
        2. ``CninfoClient.get_announcements`` 异步拉全量公告
        3. 批量预查 ``announcements.cninfo_id`` 跳过已入库
        4. 命中 ``should_download(title)`` 的公告下 PDF（线程池 + 限流）
        5. 元数据 ``ON CONFLICT (cninfo_id) DO NOTHING`` 入库

        Returns:
            ``{"total", "success", "skipped", "downloaded", "fail"}``
        """
        task_id = generate_task_id()
        set_task_id(task_id)

        if ann_date is None:
            ann_date = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")

        tracker = IngestionProgressTracker(
            source="cninfo",
            task_name="announcements",
            scope=ann_date,
        )
        run_ctx = await tracker.start_run(
            from_watermark=ann_date,
            to_watermark=ann_date,
            metadata={"mode": "daily_increment"},
        )

        async def on_page(progress: dict[str, Any]) -> None:
            await tracker.update_run(
                run_ctx,
                current_watermark=ann_date,
                current_page=progress.get("page"),
                total_pages=progress.get("total_pages"),
                total_items=progress.get("total_items"),
                processed_items=progress.get("fetched_items"),
            )
            await tracker.event(
                run_ctx,
                stage="fetch_page",
                message="巨潮公告分页获取进展",
                current_page=progress.get("page"),
                total_pages=progress.get("total_pages"),
                total_items=progress.get("total_items"),
                processed_items=progress.get("fetched_items"),
                metadata={
                    "page_items": progress.get("page_items"),
                    "has_more": progress.get("has_more"),
                },
            )

        logger.info("开始获取巨潮公告: %s", ann_date)
        await self.audit_logger.ainfo(
            "fetcher",
            f"开始获取巨潮公告: {ann_date}",
            task_id=task_id,
            ann_date=ann_date,
        )

        try:
            announcements = await self.cninfo_client.get_announcements(
                ann_date=ann_date,
                progress_callback=on_page,
            )
        except Exception as exc:
            logger.error("巨潮公告抓取失败 [%s]: %s", ann_date, exc)
            await tracker.finish_run(
                run_ctx,
                status=FAILED,
                total_items=0,
                processed_items=0,
                success_count=0,
                skipped_count=0,
                downloaded_count=0,
                fail_count=1,
                current_watermark=ann_date,
                last_error=str(exc),
                metadata={"mode": "daily_increment"},
            )
            return {"total": 0, "success": 0, "skipped": 0, "downloaded": 0, "fail": 1}

        result = await self._process_announcement_list(
            announcements=announcements,
            default_date=ann_date,
            scope=ann_date,
            tracker=tracker,
            run_ctx=run_ctx,
            is_history=False,
        )
        logger.info(
            "巨潮公告完成 [%s]: 总 %d，新增 %d，跳过 %d，下载 PDF %d，失败 %d",
            ann_date, result["total"], result["success"], result["skipped"], result["downloaded"], result["fail"],
        )
        return result

    async def _save_announcement(
        self,
        cninfo_id: str,
        ann_date_str: str,
        ts_code: str,
        name: str,
        title: str,
        doc_type: str,
        pdf_url: str,
        file_path: Path | None,
    ) -> bool | None:
        """写入 ``announcements`` 表（ON CONFLICT DO NOTHING）。

        Returns:
            ``True`` 成功新增 / ``None`` 主键冲突跳过 / ``False`` 其它失败
        """
        parsed_date = _yyyymmdd_to_date(ann_date_str)
        sql = """
        INSERT INTO announcements (
            ann_date, ts_code, name, title, type,
            cninfo_id, announcement_type,
            source_type, source_name, confidence_tier,
            file_path, pdf_url
        ) VALUES (
            :ann_date, :ts_code, :name, :title, :type,
            :cninfo_id, :announcement_type,
            :source_type, :source_name, :confidence_tier,
            :file_path, :pdf_url
        )
        ON CONFLICT (cninfo_id) DO NOTHING
        """
        try:
            async with engine.begin() as conn:
                result = await conn.execute(
                    text(sql),
                    {
                        "ann_date": parsed_date,
                        "ts_code": ts_code or None,
                        "name": name or None,
                        "title": (title or "")[:500],
                        "type": None,  # cninfo 公告无 Q&A 内容
                        "cninfo_id": cninfo_id,
                        "announcement_type": doc_type,
                        "source_type": "cninfo",
                        "source_name": "巨潮资讯",
                        "confidence_tier": "Tier1",
                        "file_path": str(file_path) if file_path else None,
                        "pdf_url": pdf_url or None,
                    },
                )
            # ON CONFLICT DO NOTHING：rowcount == 0 表示已存在
            return True if result.rowcount and result.rowcount > 0 else None
        except IntegrityError:
            return None
        except Exception as exc:
            logger.warning("保存巨潮公告失败 [%s]: %s", cninfo_id, exc)
            return False

    async def _download_announcement_pdf(self, item: dict[str, Any]) -> Path | None:
        """下载公告 PDF，返回本地路径；失败返回 None。"""
        safe_title = item["title"][:80]
        filename = f"{item['cninfo_id']}_{safe_title}.pdf"
        try:
            return await asyncio.to_thread(
                self.storage.download_notice,
                url=item["pdf_url"],
                ts_code=item["ts_code"] or "_invalid",
                filename=filename,
                pub_date=item["ann_date_str"],
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("公告 PDF 下载异常 [%s]: %s", item["cninfo_id"], exc)
            return None

    async def _on_pdf_download_complete(
        self,
        cninfo_id: str,
        file_path: Path | str,
        ts_code: str,
        title: str,
    ) -> None:
        """Trigger non-blocking KG extraction after a PDF download."""
        try:
            from app.knowledge.kg_extractor import kg_extraction_task

            async def _runner() -> None:
                try:
                    await kg_extraction_task(
                        cninfo_id=cninfo_id,
                        file_path=str(file_path),
                        ts_code=ts_code,
                        title=title,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("公告 PDF 后台 KG 抽取异常 [%s]: %s", cninfo_id, exc)

            asyncio.create_task(_runner(), name=f"kg_pdf_{cninfo_id}")
            logger.info("公告 PDF KG 抽取任务已触发 [%s]: %s", cninfo_id, file_path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("公告 PDF KG hook 触发失败 [%s]: %s", cninfo_id, exc)

    async def _update_announcement_file_path(
        self,
        cninfo_id: str,
        file_path: Path,
    ) -> bool:
        """PDF 下载成功后回写 ``announcements.file_path``。"""
        try:
            async with engine.begin() as conn:
                result = await conn.execute(
                    text(
                        "UPDATE announcements "
                        "SET file_path = :file_path "
                        "WHERE cninfo_id = :cninfo_id"
                    ),
                    {
                        "cninfo_id": cninfo_id,
                        "file_path": str(file_path),
                    },
                )
            return bool(result.rowcount and result.rowcount > 0)
        except Exception as exc:  # noqa: BLE001
            logger.warning("回写公告 PDF 路径失败 [%s]: %s", cninfo_id, exc)
            return False

    async def _clear_announcement_file_path(self, cninfo_id: str) -> bool:
        """本地 PDF 丢失或被删除后清空 ``announcements.file_path``。"""
        try:
            async with engine.begin() as conn:
                result = await conn.execute(
                    text(
                        "UPDATE announcements "
                        "SET file_path = NULL "
                        "WHERE cninfo_id = :cninfo_id"
                    ),
                    {"cninfo_id": cninfo_id},
                )
            return bool(result.rowcount and result.rowcount > 0)
        except Exception as exc:  # noqa: BLE001
            logger.warning("清空公告 PDF 路径失败 [%s]: %s", cninfo_id, exc)
            return False

    async def delete_announcement_pdf(self, cninfo_id: str) -> bool:
        """删除本地公告 PDF，并同步清空数据库 ``file_path``。

        这是公告 PDF 删除的业务入口；避免调用 ``FileStorage.delete_file``
        后数据库仍保留悬空路径。
        """
        try:
            async with engine.connect() as conn:
                row = (
                    await conn.execute(
                        text(
                            "SELECT file_path FROM announcements "
                            "WHERE cninfo_id = :cninfo_id"
                        ),
                        {"cninfo_id": cninfo_id},
                    )
                ).first()
        except Exception as exc:  # noqa: BLE001
            logger.warning("查询公告 PDF 路径失败 [%s]: %s", cninfo_id, exc)
            return False

        if row is None:
            return False

        file_path = row[0]
        if file_path:
            self.storage.delete_file(Path(file_path))
        return await self._clear_announcement_file_path(cninfo_id)

    async def reconcile_announcement_file_paths(self, limit: int = 1000) -> dict[str, int]:
        """扫描并修复公告 PDF 数据库路径与本地文件状态。

        本方法不删除文件，只维护数据库：
        - ``checked``: 检查了多少条带 file_path 的公告
        - ``cleared``: 本地文件不存在，已清空 file_path 的数量
        - ``fail``: 清空失败数量
        """
        checked = cleared = fail = 0
        try:
            async with engine.connect() as conn:
                rows = (
                    await conn.execute(
                        text(
                            "SELECT cninfo_id, file_path FROM announcements "
                            "WHERE file_path IS NOT NULL AND file_path <> '' "
                            "ORDER BY ann_date DESC "
                            "LIMIT :limit"
                        ),
                        {"limit": limit},
                    )
                ).fetchall()
        except Exception as exc:  # noqa: BLE001
            logger.warning("扫描公告 PDF 路径失败: %s", exc)
            return {"checked": 0, "cleared": 0, "fail": 1}

        for cninfo_id, file_path in rows:
            checked += 1
            if Path(file_path).exists():
                continue
            ok = await self._clear_announcement_file_path(cninfo_id)
            if ok:
                cleared += 1
            else:
                fail += 1

        return {"checked": checked, "cleared": cleared, "fail": fail}

    # ---------- 历史公告批量同步 ----------

    async def fetch_announcements_history(
        self,
        start_date: str,
        end_date: str,
        ts_code: str | None = None,
    ) -> dict[str, int]:
        """批量同步历史公告（支持日期范围查询）

        Args:
            start_date: 起始日期 YYYYMMDD
            end_date: 结束日期 YYYYMMDD
            ts_code: 股票代码，为 None 则查全市场

        Returns:
            {"total", "success", "skipped", "downloaded", "fail"}
        """
        logger.info("开始历史公告同步: %s~%s, ts_code=%s", start_date, end_date, ts_code)

        scope = ts_code or "all"
        tracker = IngestionProgressTracker(
            source="cninfo",
            task_name="announcements_history",
            scope=scope,
        )
        run_ctx = await tracker.start_run(
            from_watermark=start_date,
            to_watermark=end_date,
            metadata={"mode": "history", "ts_code": ts_code},
        )

        async def on_page(progress: dict[str, Any]) -> None:
            await tracker.update_run(
                run_ctx,
                current_watermark=end_date,
                current_page=progress.get("page"),
                total_pages=progress.get("total_pages"),
                total_items=progress.get("total_items"),
                processed_items=progress.get("fetched_items"),
            )
            await tracker.event(
                run_ctx,
                stage="fetch_page",
                message="巨潮历史公告分页获取进展",
                current_page=progress.get("page"),
                total_pages=progress.get("total_pages"),
                total_items=progress.get("total_items"),
                processed_items=progress.get("fetched_items"),
                metadata={
                    "page_items": progress.get("page_items"),
                    "has_more": progress.get("has_more"),
                },
            )

        try:
            announcements = await self.cninfo_client.get_announcements(
                ann_date=start_date,
                ann_date_end=end_date,
                ts_code=ts_code,
                progress_callback=on_page,
            )
        except Exception as exc:
            logger.error("历史公告抓取失败 [%s~%s, %s]: %s", start_date, end_date, ts_code, exc)
            await tracker.finish_run(
                run_ctx,
                status=FAILED,
                total_items=0,
                processed_items=0,
                success_count=0,
                skipped_count=0,
                downloaded_count=0,
                fail_count=1,
                current_watermark=start_date,
                last_error=str(exc),
                metadata={"mode": "history", "ts_code": ts_code},
            )
            return {"total": 0, "success": 0, "skipped": 0, "downloaded": 0, "fail": 1}

        result = await self._process_announcement_list(
            announcements=announcements,
            default_date=end_date,
            scope=scope,
            tracker=tracker,
            run_ctx=run_ctx,
            is_history=True,
        )
        logger.info(
            "历史公告完成 [%s~%s]: 总 %d，新增 %d，跳过 %d，下载 %d，失败 %d",
            start_date, end_date, result["total"], result["success"], result["skipped"], result["downloaded"], result["fail"],
        )
        return result

    # ---------- 指数 K 线 ----------

    async def fetch_index_kline(
        self,
        index_code: str = "sh.000001",
        start_date: str | None = None,
        end_date: str | None = None,
        frequency: str = "d",
    ) -> dict[str, int]:
        today = datetime.now()
        end = datetime.strptime(end_date, "%Y%m%d") if end_date else today - timedelta(days=1)
        start = datetime.strptime(start_date, "%Y%m%d") if start_date else end - timedelta(days=30)
        start_str = start.strftime("%Y%m%d")
        end_str = end.strftime("%Y%m%d")

        logger.info("获取指数K线: %s %s~%s %s", index_code, start_str, end_str, frequency)

        records = await asyncio.to_thread(
            self.data_source.get_index_kline,
            index_code=index_code,
            start_date=start_str,
            end_date=end_str,
            frequency=frequency,
        )
        if not records:
            logger.warning("指数 %s K线为空", index_code)
            return {"total": 0, "success": 0, "skipped": 0, "fail": 0}

        success = skipped = fail = 0
        for rec in records:
            trade_date = str(rec.get("date") or "").replace("-", "")
            try:
                saved = await self._save_index_kline(index_code, trade_date, rec)
                if saved is True:
                    success += 1
                elif saved is None:
                    skipped += 1
                else:
                    fail += 1
            except Exception as exc:
                fail += 1
                logger.warning("保存指数K线失败 [%s %s]: %s", index_code, trade_date, exc)

        logger.info("指数K线 %s 完成: 入库 %d，跳过 %d，失败 %d",
                    index_code, success, skipped, fail)
        return {"total": len(records), "success": success, "skipped": skipped, "fail": fail}

    async def _save_index_kline(
        self,
        index_code: str,
        trade_date: str,
        rec: dict[str, Any],
    ) -> bool | None:
        parsed_date = _yyyymmdd_to_date(trade_date)
        if parsed_date is None:
            return None

        close = _safe_float(rec.get("close"))
        preclose = _safe_float(rec.get("preclose"))
        change = (close - preclose) if (close is not None and preclose is not None) else None

        sql = """
        INSERT INTO index_daily (
            ts_code, trade_date, open, high, low, close, pre_close,
            change, pct_chg, vol, amount
        ) VALUES (
            :ts_code, :trade_date, :open, :high, :low, :close, :pre_close,
            :change, :pct_chg, :vol, :amount
        )
        ON CONFLICT (ts_code, trade_date) DO UPDATE SET
            open = EXCLUDED.open,
            high = EXCLUDED.high,
            low = EXCLUDED.low,
            close = EXCLUDED.close,
            pct_chg = EXCLUDED.pct_chg,
            vol = EXCLUDED.vol,
            amount = EXCLUDED.amount
        """
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    text(sql),
                    {
                        "ts_code": index_code,
                        "trade_date": parsed_date,
                        "open": _safe_float(rec.get("open")),
                        "high": _safe_float(rec.get("high")),
                        "low": _safe_float(rec.get("low")),
                        "close": close,
                        "pre_close": preclose,
                        "change": change,
                        "pct_chg": _safe_float(rec.get("pctChg")),
                        "vol": _safe_float(rec.get("volume")),
                        "amount": _safe_float(rec.get("amount")),
                    },
                )
            return True
        except IntegrityError:
            return None

    async def _save_stock_kline(
        self,
        ts_code: str,
        trade_date: str,
        rec: dict[str, Any],
    ) -> bool | None:
        """保存个股 K 线（Phase 31 D-A3）。True=新建/更新成功，None=IntegrityError，False=其他失败。

        FK 约束：daily_data.ts_code → stocks.ts_code，需先确保 stocks 表已同步。
        """
        parsed_date = _yyyymmdd_to_date(trade_date)
        if parsed_date is None:
            return None

        close = _safe_float(rec.get("close"))
        preclose = _safe_float(rec.get("preclose"))
        change = (close - preclose) if (close is not None and preclose is not None) else None
        # baostock tradestatus："1" 正常 / "0" 停牌（白名单转换，T-A-baostock-dirty mitigation）
        is_suspended = (str(rec.get("tradestatus", "1")) == "0")

        sql = """
        INSERT INTO daily_data (
            ts_code, trade_date, open, high, low, close, pre_close,
            change, pct_chg, vol, amount, is_suspended
        ) VALUES (
            :ts_code, :trade_date, :open, :high, :low, :close, :pre_close,
            :change, :pct_chg, :vol, :amount, :is_suspended
        )
        ON CONFLICT (ts_code, trade_date) DO UPDATE SET
            open = EXCLUDED.open,
            high = EXCLUDED.high,
            low = EXCLUDED.low,
            close = EXCLUDED.close,
            pre_close = EXCLUDED.pre_close,
            change = EXCLUDED.change,
            pct_chg = EXCLUDED.pct_chg,
            vol = EXCLUDED.vol,
            amount = EXCLUDED.amount,
            is_suspended = EXCLUDED.is_suspended
        """
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    text(sql),
                    {
                        "ts_code": ts_code,
                        "trade_date": parsed_date,
                        "open": _safe_float(rec.get("open")),
                        "high": _safe_float(rec.get("high")),
                        "low": _safe_float(rec.get("low")),
                        "close": close,
                        "pre_close": preclose,
                        "change": change,
                        "pct_chg": _safe_float(rec.get("pctChg")),
                        "vol": _safe_float(rec.get("volume")),
                        "amount": _safe_float(rec.get("amount")),
                        "is_suspended": is_suspended,
                    },
                )
            return True
        except IntegrityError:
            return None
        except Exception as exc:
            logger.warning("保存个股 K 线失败 [%s %s]: %s", ts_code, trade_date, exc)
            return False

    async def fetch_stock_kline(
        self,
        ts_code: str,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, int]:
        """单只个股 K 线 orchestration（Phase 31 D-A1）。"""
        today = datetime.now()
        end = datetime.strptime(end_date, "%Y%m%d") if end_date else today - timedelta(days=1)
        start = datetime.strptime(start_date, "%Y%m%d") if start_date else end - timedelta(days=STOCK_KLINE_BACKFILL_DAYS)
        start_str = start.strftime("%Y%m%d")
        end_str = end.strftime("%Y%m%d")

        try:
            records = await asyncio.to_thread(
                partial(
                    self.data_source.get_stock_kline,
                    ts_code=ts_code,
                    start_date=start_str,
                    end_date=end_str,
                    adjustflag="3",
                    raise_on_error=True,
                )
            )
        except Exception as exc:
            logger.warning("个股 %s K线抓取失败: %s", ts_code, exc)
            return {"total": 0, "success": 0, "skipped": 0, "fail": 1}
        if not records:
            return {"total": 0, "success": 0, "skipped": 0, "fail": 0}

        success = skipped = fail = 0
        for rec in records:
            trade_date = str(rec.get("date") or "").replace("-", "")
            try:
                saved = await self._save_stock_kline(ts_code, trade_date, rec)
                if saved is True:
                    success += 1
                elif saved is None:
                    skipped += 1
                else:
                    fail += 1
            except Exception as exc:
                fail += 1
                logger.debug("保存个股K线失败 [%s %s]: %s", ts_code, trade_date, exc)
        return {"total": len(records), "success": success, "skipped": skipped, "fail": fail}

    async def fetch_all_stocks_kline(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, int]:
        """全市场个股 daily_data 采集（Phase 31 D-A2/D-A5）。

        起始日期决策（D-A5）：
          - 显式传 start_date：使用之
          - 否则按每只 ts_code 自己的 MAX(daily_data.trade_date) 计算缺口
          - 单只股票无历史数据：回填 STOCK_KLINE_BACKFILL_DAYS
          - 单只股票已到 end_date：跳过，避免用全表最大日期掩盖个股遗漏

        T-A-5000-overload mitigation: Semaphore=STOCK_KLINE_CONCURRENCY；
        每只股票使用隔离 DataSourceClient，抓取后 logout，避免共享 baostock session。
        """
        all_stocks = await asyncio.to_thread(self.data_source.get_stocks_basic, "L")
        ts_codes = [s["ts_code"] for s in all_stocks if s.get("ts_code")]
        total = len(ts_codes)
        if total == 0:
            logger.warning("get_stocks_basic 返回空，全市场 K 线跳过")
            return {"total": 0, "processed": 0, "success": 0, "skipped": 0, "fail": 0}
        logger.info("开始采集全市场个股 K 线: %d 只", total)

        today = datetime.now()
        end = datetime.strptime(end_date, "%Y%m%d") if end_date else today - timedelta(days=1)
        end_day = end.date()

        if start_date:
            explicit_start = datetime.strptime(start_date, "%Y%m%d").date()
            kline_jobs = [(code, explicit_start, end_day) for code in ts_codes]
        else:
            latest_by_code: dict[str, date] = {}
            async with engine.connect() as conn:
                result = await conn.execute(
                    text(
                        """
                        SELECT ts_code, MAX(trade_date) AS latest
                        FROM daily_data
                        WHERE ts_code = ANY(:ts_codes)
                        GROUP BY ts_code
                        """
                    ),
                    {"ts_codes": ts_codes},
                )
                for row in result.mappings().all():
                    latest = row["latest"]
                    if latest:
                        latest_by_code[row["ts_code"]] = latest

            kline_jobs = []
            up_to_date = 0
            missing_history = 0
            for code in ts_codes:
                latest = latest_by_code.get(code)
                if latest is None:
                    start_day = end_day - timedelta(days=STOCK_KLINE_BACKFILL_DAYS)
                    missing_history += 1
                elif latest >= end_day:
                    up_to_date += 1
                    continue
                else:
                    start_day = latest + timedelta(days=1)
                kline_jobs.append((code, start_day, end_day))
            logger.info(
                "全市场 K 线补齐计划: 待抓取 %d/%d，只股票已最新 %d，无历史 %d",
                len(kline_jobs), total, up_to_date, missing_history,
            )

        end_str = end.strftime("%Y%m%d")

        semaphore = asyncio.Semaphore(STOCK_KLINE_CONCURRENCY)
        counters = {
            "success": 0,
            "fail": 0,
            "skipped": total - len(kline_jobs),
            "processed": 0,
            "up_to_date": total - len(kline_jobs),
        }

        def fetch_with_isolated_client(
            code: str,
            start_str: str,
            end_str: str,
            force_reconnect: bool = False,
        ) -> list[dict[str, Any]]:
            client = DataSourceClient()
            try:
                return client.get_stock_kline(
                    code,
                    start_str,
                    end_str,
                    raise_on_error=True,
                )
            finally:
                client._bs_logout()
                if force_reconnect:
                    # 强制重新初始化连接：logout 后再 login，
                    # 解决长连接 broken pipe 问题（Phase 31 承诺但未实现）
                    client2 = DataSourceClient()
                    try:
                        client2._bs_login()
                        client2._bs_logout()
                    except Exception:
                        pass

        processed_count = 0

        async def worker(idx: int, code: str, start_day: date, end_day: date) -> None:
            nonlocal processed_count
            async with semaphore:
                force_reconnect = (processed_count > 0 and processed_count % STOCK_KLINE_RECONNECT_EVERY == 0)
                try:
                    start_str = start_day.strftime("%Y%m%d")
                    end_str = end_day.strftime("%Y%m%d")
                    records = await asyncio.to_thread(
                        fetch_with_isolated_client,
                        code,
                        start_str,
                        end_str,
                        force_reconnect=force_reconnect,
                    )
                except Exception as exc:
                    logger.warning("股票 %s 抓取失败: %s", code, exc)
                    counters["fail"] += 1
                    processed_count += 1
                    return
                if not records:
                    counters["skipped"] += 1
                    return
                for rec in records:
                    trade_date = str(rec.get("date", "")).replace("-", "")
                    try:
                        saved = await self._save_stock_kline(code, trade_date, rec)
                        if saved is True:
                            counters["success"] += 1
                        elif saved is False:
                            counters["fail"] += 1
                    except Exception as exc:
                        counters["fail"] += 1
                        logger.debug("保存 %s %s 失败: %s", code, trade_date, exc)
                counters["processed"] += 1
                processed_count += 1
                await asyncio.sleep(STOCK_KLINE_SLEEP_BASE + random.random() * STOCK_KLINE_SLEEP_JITTER)

        await asyncio.gather(*(worker(i, code, start, end) for i, (code, start, end) in enumerate(kline_jobs)))
        logger.info(
            "全市场 K 线完成: 处理 %d/%d，入库 %d 条，跳过 %d，失败 %d，已最新 %d",
            counters["processed"], total, counters["success"],
            counters["skipped"], counters["fail"], counters["up_to_date"],
        )
        return {"total": total, **counters}

    # ---------- 公司概况 ----------

    async def fetch_stock_profile(self, ts_code: str) -> dict[str, int]:
        data = await asyncio.to_thread(self.data_source.get_stock_profile, ts_code)
        if not data:
            return {"success": 0, "skipped": 1}

        sql = """
        INSERT INTO company_profiles (ts_code, main_business, business_scope)
        VALUES (:ts_code, :main_business, :business_scope)
        ON CONFLICT (ts_code) DO UPDATE SET
            main_business = EXCLUDED.main_business,
            business_scope = EXCLUDED.business_scope
        """
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    text(sql),
                    {
                        "ts_code": ts_code,
                        "main_business": data.get("main_business") or "",
                        "business_scope": data.get("business_scope") or "",
                    },
                )
            return {"success": 1, "skipped": 0}
        except Exception as exc:
            logger.warning("保存股票概况失败 %s: %s", ts_code, exc)
            return {"success": 0, "skipped": 1}

    # ---------- 概念板块 ----------

    # Phase 31 CR-01: instance method removed — module-level fetch_concept() called directly


# ── 股票同步 ───────────────────────────────────────────

async def async_sync_stocks() -> dict[str, int]:
    """同步股票列表到 PostgreSQL。"""
    client = DataSourceClient()
    stocks = await asyncio.to_thread(client.get_stocks_basic, "L")
    sql = """
    INSERT INTO stocks (ts_code, symbol, name, industry)
    VALUES (:ts_code, :symbol, :name, :industry)
    ON CONFLICT (ts_code) DO UPDATE SET
        name = EXCLUDED.name,
        industry = EXCLUDED.industry
    """
    inserted = failed = 0
    for stock in stocks:
        ts_code = stock.get("ts_code", "")
        if not ts_code:
            continue
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    text(sql),
                    {
                        "ts_code": ts_code,
                        "symbol": ts_code.split(".")[0] if "." in ts_code else ts_code,
                        "name": stock.get("name") or "",
                        "industry": stock.get("industry") or "",
                    },
                )
            inserted += 1
        except Exception as exc:
            failed += 1
            logger.warning("股票同步失败 %s: %s", ts_code, exc)

    logger.info("股票列表同步完成: 处理 %d，失败 %d", inserted, failed)
    return {"total": len(stocks), "success": inserted, "fail": failed}


def sync_stocks() -> dict[str, int]:
    """同步入口（同步接口，供 CLI 调用）。"""
    return asyncio.run(async_sync_stocks())


# ── 概念板块同步 ───────────────────────────────────────

async def fetch_concept() -> dict[str, int]:
    """
    获取概念板块数据（涨停股所在概念）。

    - 用 concept_name 的稳定 hash 作为 concept_code，避免把名字当 code 写入（B6）。
    - 仅统计涨停家数（akshare stock_zt_pool_strong_em）。
    """
    try:
        import akshare as ak
    except ImportError:
        logger.error("akshare 未安装，跳过概念同步")
        return {"success": 0, "skipped": 0, "fail": 1}

    today = datetime.now().strftime("%Y%m%d")
    try:
        # Phase 31 D-D2: akshare 限速
        await asyncio.to_thread(get_akshare_limiter().wait_and_acquire)
        limit_df = await asyncio.to_thread(ak.stock_zt_pool_strong_em, today)
    except Exception as exc:
        logger.warning("获取涨停股失败，跳过概念同步: %s", exc)
        return {"success": 0, "skipped": 0, "fail": 1}

    if limit_df is None or len(limit_df) == 0:
        logger.info("今日无涨停股，跳过概念同步")
        return {"success": 0, "skipped": 1, "fail": 0}

    concept_counts: dict[str, dict[str, Any]] = {}
    for _, row in limit_df.iterrows():
        concept_raw = str(row.get("概念板块") or "")
        if not concept_raw or concept_raw in ("nan", "None", ""):
            continue
        try:
            pct_chg = float(row.get("涨停统计", 0) or 0)
        except (TypeError, ValueError):
            pct_chg = 0.0
        for name in concept_raw.split("|"):
            name = name.strip()
            if not name:
                continue
            entry = concept_counts.setdefault(
                name, {"count": 0, "pct_chg": 0.0},
            )
            entry["count"] += 1
            entry["pct_chg"] = max(entry["pct_chg"], pct_chg)

    success = fail = 0
    for concept_name, info in concept_counts.items():
        try:
            await _save_concept_limit(
                concept_code=_concept_code(concept_name),
                concept_name=concept_name,
                trade_date=today,
                up_nums=info["count"],
                pct_chg=info["pct_chg"],
            )
            success += 1
        except Exception as exc:
            fail += 1
            logger.warning("保存概念 %s 失败: %s", concept_name, exc)

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
