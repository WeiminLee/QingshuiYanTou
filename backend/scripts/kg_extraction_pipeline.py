"""
KG 抽取管道 + 定时扫描脚本

功能：
  1. 扫描本地报告目录（industry_reports / stock_reports）
  2. 增量检测新文件 / 内容变化
  3. 调用 LLM 抽取实体和关系 → Neo4j
  4. 更新 MongoDB 索引状态
  5. 支持常驻扫描（--daemon）和单次运行（默认）

稳健性设计：
  - 单文件独立事务：一文件失败不影响其他文件
  - 自动重试：失败文件最多重试 3 次
  - 增量扫描：file_hash 变化才重新抽取
  - 断点续传：extracting 状态重启后自动重跑
  - 并发控制：每批 2 个文件，间隔 3 秒

用法：
  # 单次运行
  python scripts/kg_extraction_pipeline.py

  # 常驻模式（每 30 分钟扫描一次）
  python scripts/kg_extraction_pipeline.py --daemon --interval 30

  # 只处理 pending，不扫描新文件
  python scripts/kg_extraction_pipeline.py --once
"""
import argparse
import asyncio
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ.setdefault("UV_RUN", "1")

from dotenv import load_dotenv
load_dotenv()

from app.core.mongodb import get_mongo_db
from app.core.neo4j_client import health_check as neo4j_health_check
from app.data_pipeline.announcement_filter import classify_title
from app.data_pipeline.progress import FAILED, PARTIAL, SUCCESS, IngestionProgressTracker
from app.knowledge.file_indexer import FileIndexer
from app.knowledge.evidence_builders import build_file_evidence
from app.knowledge.evidence_service import EvidenceService
from app.knowledge.kg_extractor import extract_text_async, _extract_text_from_file
from app.core.llm_client import chat, get_llm_client
from app.core.task_logger import TaskLogger
import signal

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

BATCH_SIZE = 2          # 每批并发处理文件数
EXCLUDE_TYPES = set()     # 不再排除 PDF，opendataloader_pdf 已能高效处理
SCAN_INTERVAL = 30 * 60  # 扫描间隔（秒），默认 30 分钟
FILE_TIMEOUT = 300        # 单文件超时（秒）
MAX_PDF_CHUNKS_PER_FILE = int(os.getenv("KG_MAX_PDF_CHUNKS_PER_FILE", "8"))


def _normalize_source_and_doc_type(file_info: dict) -> tuple[str, str]:
    """Return KG source_type and business doc_type for a file-index document."""
    raw_source = str(file_info.get("source_type") or "").strip()
    raw_doc_type = str(file_info.get("doc_type") or file_info.get("announcement_type") or "").strip()
    title = str(file_info.get("title") or file_info.get("file_name") or "")
    fname = str(file_info.get("file_name") or "")
    fname_lower = fname.lower()

    if raw_doc_type and raw_doc_type not in {"disclosure", "other", "unknown"}:
        doc_type = raw_doc_type
    else:
        doc_type, _ = classify_title(title)

    if raw_source in {"annual_report", "announcement", "research_report", "uploaded_doc", "interactive_qa"}:
        source_type = raw_source
    elif raw_source in {"cninfo", "cninfo_announcement", "announcement_v4"} or file_info.get("cninfo_id"):
        source_type = "annual_report" if doc_type == "annual_report" else "announcement"
    elif "report" in fname_lower or "研报" in fname:
        source_type = "research_report"
    else:
        source_type = "uploaded_doc"

    return source_type, doc_type


class KGPipeline:
    """KG 抽取管道"""

    def __init__(self, evidence_first: bool = True):
        self._db = get_mongo_db()
        self._indexer = FileIndexer(self._db)
        self._evidence = EvidenceService(self._db)
        self.evidence_first = evidence_first

    async def run(
        self,
        limit: int | None = None,
        max_runtime_seconds: int | None = None,
    ) -> dict:
        """完整运行：扫描 → 抽取 → 统计"""
        if not neo4j_health_check():
            logger.error("Neo4j 不可用，跳过")
            return {"error": "Neo4j unavailable"}

        # 启动自愈：把卡在 extracting 的记录重置回 pending
        healed = await self._indexer.heal_extracting()
        if healed:
            logger.info("🔧 自愈: %d 个卡死文件已重置", healed)

        scan = await self._indexer.scan_and_index()
        new_c, chg_c = len(scan["new"]), len(scan["changed"])
        logger.info("扫描: 新增=%d 变化=%d 未变=%d", new_c, chg_c, scan["unchanged"])

        processed = await self._process_pending(limit=limit, max_runtime_seconds=max_runtime_seconds)
        stats = await self._indexer.get_stats()
        stats["scan_new"] = new_c
        stats["scan_changed"] = chg_c
        stats.update(processed)
        return stats

    async def run_once(
        self,
        limit: int | None = None,
        max_runtime_seconds: int | None = None,
    ) -> dict:
        """只处理 pending，不扫描新文件"""
        if not neo4j_health_check():
            return {"error": "Neo4j unavailable"}
        processed = await self._process_pending(limit=limit, max_runtime_seconds=max_runtime_seconds)
        stats = await self._indexer.get_stats()
        stats.update(processed)
        return stats

    async def get_stats(self) -> dict:
        return await self._indexer.get_stats()

    async def _process_pending(
        self,
        limit: int | None = None,
        max_runtime_seconds: int | None = None,
    ) -> dict:
        result = {"total": 0, "success": 0, "failed": 0, "skipped": 0, "limit_reached": False, "runtime_exhausted": False}
        if limit is not None and limit <= 0:
            return result
        deadline = time.monotonic() + max_runtime_seconds if max_runtime_seconds and max_runtime_seconds > 0 else None
        tracker = IngestionProgressTracker(source="kg", task_name="pdf_extract", scope="kg_file_index")
        ctx = await tracker.start_run(metadata={"limit": limit, "max_runtime_seconds": max_runtime_seconds})

        # LLM 预检：不可用则立即退出，不继续处理
        if not _llm_health_check():
            logger.error("LLM 不可用，退出进程")
            await tracker.finish_run(
                ctx,
                status=FAILED,
                total_items=limit or 0,
                processed_items=0,
                success_count=0,
                skipped_count=0,
                downloaded_count=0,
                fail_count=1,
                last_error="LLM unavailable",
                metadata=result,
            )
            raise SystemExit(1)

        while True:
            if limit is not None and result["total"] >= limit:
                result["limit_reached"] = True
                break
            if deadline is not None and time.monotonic() >= deadline:
                result["runtime_exhausted"] = True
                break

            batch_limit = BATCH_SIZE
            if limit is not None:
                batch_limit = min(batch_limit, max(0, limit - result["total"]))
            if batch_limit <= 0:
                result["limit_reached"] = True
                break
            pending = await self._indexer.get_pending_files(
                limit=batch_limit, exclude_types=EXCLUDE_TYPES,
            )
            if not pending:
                break

            tasks = [self._process_one(f, tracker=tracker, ctx=ctx) for f in pending]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for f, res in zip(pending, results):
                result["total"] += 1
                if isinstance(res, Exception):
                    result["failed"] += 1
                    logger.error("处理异常: %s → %s", f["file_name"], res)
                elif res == "success":
                    result["success"] += 1
                elif res == "skipped":
                    result["skipped"] += 1
                else:
                    result["failed"] += 1
                await tracker.update_run(
                    ctx,
                    total_items=limit or result["total"],
                    processed_items=result["total"],
                    success_count=result["success"],
                    skipped_count=result["skipped"],
                    fail_count=result["failed"],
                    last_item_id=str(f.get("cninfo_id") or f.get("file_name") or "")[:100],
                    last_error=str(res)[:1000] if isinstance(res, Exception) else None,
                )

            await asyncio.sleep(3)  # 避免 LLM 过载

        status = FAILED if result["failed"] and not result["success"] and not result["skipped"] else (PARTIAL if result["failed"] else SUCCESS)
        await tracker.finish_run(
            ctx,
            status=status,
            total_items=limit or result["total"],
            processed_items=result["total"],
            success_count=result["success"],
            skipped_count=result["skipped"],
            downloaded_count=0,
            fail_count=result["failed"],
            metadata=result,
        )
        return result

    async def _process_one(self, file_info: dict, tracker: IngestionProgressTracker | None = None, ctx=None) -> str:
        """处理单个文件（含超时保护）"""
        file_path = file_info["file_path"]
        file_type = file_info["file_type"]
        fname = file_info["file_name"]
        source_type, doc_type = _normalize_source_and_doc_type(file_info)

        # 优先用文件名解析的 ts_code
        ts_code = file_info.get("ts_code") or self._guess_ts_code(fname)
        await self._indexer.mark_extracting(file_path, source_type=source_type, doc_type=doc_type)
        if tracker and ctx:
            await tracker.event(
                ctx,
                stage="file_start",
                message="PDF 知识抽取开始",
                item_id=str(file_info.get("cninfo_id") or fname)[:100],
                item_title=str(file_info.get("title") or fname)[:500],
                metadata={"file_path": file_path, "source_type": source_type, "doc_type": doc_type, "ts_code": ts_code},
            )

        # 文本长度（用于估算 chunk 数）
        try:
            if file_type == "md":
                text = Path(file_path).read_text(encoding="utf-8", errors="replace")
            elif file_type == "pdf":
                from app.knowledge.extraction.announcement_filter import (
                    filter_announcement_pdf, extract_filtered_text,
                )
                # 判断类型：文件名含 report/研报 → 研报，全量保留
                fname_lower = fname.lower()
                is_report = source_type == "research_report" or "report" in fname_lower or "研报" in fname

                if is_report:
                    # 研报：不过滤章节，全量提取
                    logger.info("📄 研报文件，全量抽取: %s", fname)
                    text = _extract_text_from_file(Path(file_path), ".pdf")
                else:
                    # 公告或其他：走两级过滤
                    fr = filter_announcement_pdf(file_path, is_announcement=True)
                    if fr.decision == "skip":
                        logger.info("⏭ 跳过 [%s] %s | %s", fr.file_reason, fname, fr.detail)
                        await self._indexer.mark_skipped(file_path, f"{fr.file_reason}:{fr.detail}")
                        if tracker and ctx:
                            await tracker.event(
                                ctx,
                                stage="file_skipped",
                                message="PDF 知识抽取过滤跳过",
                                item_id=str(file_info.get("cninfo_id") or fname)[:100],
                                item_title=str(file_info.get("title") or fname)[:500],
                                metadata={
                                    "file_path": file_path,
                                    "source_type": source_type,
                                    "doc_type": doc_type,
                                    "reason": fr.file_reason,
                                    "detail": fr.detail,
                                },
                            )
                        return "skipped"
                    if fr.file_reason == "section_filtered":
                        logger.info("📋 章节过滤: %s | 保留=%d 跳过=%d | %s",
                                    fname, fr.sections_kept, fr.sections_skipped,
                                    " / ".join(fr.kept_chapters[:3]))
                        filtered = extract_filtered_text(file_path, is_announcement=True)
                        text = filtered if filtered.strip() else _extract_text_from_file(Path(file_path), ".pdf")
                    else:
                        # standard_format 快速通过
                        text = _extract_text_from_file(Path(file_path), ".pdf")
            else:
                await self._indexer.mark_skipped(file_path, f"不支持类型: {file_type}")
                if tracker and ctx:
                    await tracker.event(ctx, stage="file_skipped", message="PDF 知识抽取跳过", item_id=str(file_info.get("cninfo_id") or fname)[:100], item_title=fname, metadata={"reason": f"不支持类型: {file_type}"})
                return "skipped"
        except Exception as read_err:
            logger.warning("文件读取失败: %s → %s", fname, read_err)
            await self._indexer.mark_failed(file_path, f"读取失败: {read_err}")
            if tracker and ctx:
                await tracker.event(ctx, stage="file_error", message="PDF 文件读取失败", item_id=str(file_info.get("cninfo_id") or fname)[:100], item_title=fname, error=str(read_err), metadata={"file_path": file_path})
            return "failed"

        if not text.strip():
            await self._indexer.mark_skipped(file_path, "文件内容为空")
            if tracker and ctx:
                await tracker.event(ctx, stage="file_skipped", message="PDF 知识抽取跳过", item_id=str(file_info.get("cninfo_id") or fname)[:100], item_title=fname, metadata={"reason": "文件内容为空"})
            return "skipped"

        # 估算 chunk 数（512 tokens/块）
        est_chunks = max(1, len(text) // 700)
        chunk_max_tokens = 512 if file_type == "md" else 2048
        logger.info("▶ 抽取: %s | 字数=%d | 预估chunk≈%d | ts=%s",
                     fname, len(text), est_chunks, ts_code)

        if self.evidence_first:
            try:
                result = await self._create_file_evidence_jobs(
                    file_info, text, source_type, doc_type, ts_code, tracker=tracker, ctx=ctx,
                    chunk_max_tokens=chunk_max_tokens,
                    max_chunks=MAX_PDF_CHUNKS_PER_FILE if file_type == "pdf" else None,
                )
                await self._indexer.mark_done(file_path, 0, 0, source_type=source_type, doc_type=doc_type)
                if tracker and ctx:
                    await tracker.event(
                        ctx,
                        stage="file_done",
                        message="PDF Evidence 构建完成",
                        item_id=str(file_info.get("cninfo_id") or fname)[:100],
                        item_title=str(file_info.get("title") or fname)[:500],
                        metadata={"file_path": file_path, **result},
                    )
                logger.info("✅ Evidence-first %s | evidence=%d jobs=%d", fname, result.get("evidence_created_or_updated", 0), result.get("jobs_enqueued", 0))
                return "success"
            except Exception as e:
                logger.warning("❌ Evidence 构建失败: %s → %s", fname, e)
                await self._indexer.mark_failed(file_path, str(e))
                if tracker and ctx:
                    await tracker.event(ctx, stage="file_error", message="PDF Evidence 构建失败", item_id=str(file_info.get("cninfo_id") or fname)[:100], item_title=fname, error=str(e))
                raise

        def _progress(msg: str, pct: float):
            """逐阶段日志回调"""
            logger.info("  [%s] %.0f%% %s", fname, pct, msg)

        try:
            coro = extract_text_async(
                text=text,
                ts_code=ts_code or "UNKNOWN",
                source_name=fname,
                source_type=source_type,
                article_ref=fname,
                progress_callback=_progress,
                file_path=file_path,       # 用于获取文件创建日期，构建 source_file
                # Markdown 有标题结构，512 tokens 足够；PDF/TXT 无结构，增大避免 chunk 爆炸
                chunk_max_tokens=chunk_max_tokens,
                max_chunks=MAX_PDF_CHUNKS_PER_FILE if file_type == "pdf" else None,
            )

            # 超时保护：单文件最长 FILE_TIMEOUT 秒
            result = await asyncio.wait_for(coro, timeout=FILE_TIMEOUT)

            n_chunks = result.get("chunks_processed", 0)
            n_chunks_total = result.get("chunks_total", n_chunks)
            n_entities = result.get("entities_created", 0)
            n_relations = result.get("relations_created", 0)
            state = result.get("inferred_state", "") or ""
            chunk_budget_applied = bool(result.get("chunk_budget_applied"))

            await self._indexer.mark_done(
                file_path, n_entities, n_relations, source_type=source_type, doc_type=doc_type,
            )
            if tracker and ctx:
                await tracker.event(
                    ctx,
                    stage="file_done",
                    message="PDF 知识抽取完成",
                    item_id=str(file_info.get("cninfo_id") or fname)[:100],
                    item_title=str(file_info.get("title") or fname)[:500],
                    metadata={
                        "file_path": file_path,
                        "source_type": source_type,
                        "doc_type": doc_type,
                        "chunks": n_chunks,
                        "chunks_total": n_chunks_total,
                        "entities": n_entities,
                        "relations": n_relations,
                        "state": state,
                        "chunk_budget_applied": chunk_budget_applied,
                        "max_pdf_chunks": MAX_PDF_CHUNKS_PER_FILE,
                    },
                )
            state_str = f" | 行业状态={state}" if state else ""
            logger.info(
                "✅ %s | chunks=%d 实体=%d 关系=%d%s",
                fname, n_chunks, n_entities, n_relations, state_str,
            )
            return "success"

        except asyncio.TimeoutError:
            logger.warning("⏰ 超时: %s (>%ds)，跳过", fname, FILE_TIMEOUT)
            await self._indexer.mark_failed(file_path, f"LLM 超时 ({FILE_TIMEOUT}s)")
            if tracker and ctx:
                await tracker.event(ctx, stage="file_error", message="PDF 知识抽取超时", item_id=str(file_info.get("cninfo_id") or fname)[:100], item_title=fname, error=f"LLM 超时 ({FILE_TIMEOUT}s)")
            return "failed"
        except Exception as e:
            logger.warning("❌ 失败: %s → %s", fname, e)
            await self._indexer.mark_failed(file_path, str(e))
            if tracker and ctx:
                await tracker.event(ctx, stage="file_error", message="PDF 知识抽取失败", item_id=str(file_info.get("cninfo_id") or fname)[:100], item_title=fname, error=str(e), metadata={"file_path": file_path, "source_type": source_type, "doc_type": doc_type})
            raise


    async def _create_file_evidence_jobs(
        self,
        file_info: dict,
        text: str,
        source_type: str,
        doc_type: str,
        ts_code: str | None,
        tracker: IngestionProgressTracker | None = None,
        ctx=None,
        chunk_max_tokens: int = 2048,
        max_chunks: int | None = None,
    ) -> dict:
        evidence_items = build_file_evidence(
            file_info=file_info,
            text=text,
            source_type=source_type,
            doc_type=doc_type,
            ts_code=ts_code,
            chunk_max_tokens=chunk_max_tokens,
            max_chunks=max_chunks,
        )
        jobs_enqueued = 0
        evidence_ids: list[str] = []
        for idx, item in enumerate(evidence_items):
            saved = await self._evidence.upsert_evidence(item, chunk_index=idx)
            evidence_id = saved["evidence_id"]
            evidence_ids.append(evidence_id)
            jobs = await self._evidence.enqueue_default_jobs(evidence_id)
            jobs_enqueued += len(jobs)
        result = {
            "evidence_created_or_updated": len(evidence_items),
            "jobs_enqueued": jobs_enqueued,
            "chunks_total": len(evidence_items),
            "evidence_ids": evidence_ids[:20],
        }
        if tracker and ctx:
            await tracker.event(
                ctx,
                stage="evidence_created",
                message="PDF Evidence 已创建",
                item_id=str(file_info.get("cninfo_id") or file_info.get("file_name") or "")[:100],
                item_title=str(file_info.get("title") or file_info.get("file_name") or "")[:500],
                metadata=result,
            )
        return result

    @staticmethod
    def _guess_ts_code(fname: str) -> str | None:
        from app.knowledge.file_indexer import _parse_ts_code_from_filename
        return _parse_ts_code_from_filename(fname)


def run_daemon(interval_minutes: int, limit: int | None = None, max_runtime_seconds: int | None = None, evidence_first: bool = True):
    """常驻模式：每 N 分钟扫描一次"""
    interval_sec = interval_minutes * 60
    pipeline = KGPipeline(evidence_first=evidence_first)
    logger.info("🚀 KG 抽取管道启动（常驻模式，间隔 %d 分钟，evidence_first=%s）", interval_minutes, evidence_first)

    while True:
        tl = TaskLogger("kg_extraction_pipeline")
        tl.start()
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            stats = loop.run_until_complete(pipeline.run(limit=limit, max_runtime_seconds=max_runtime_seconds))
            loop.close()

            if "error" in stats:
                logger.error("本次运行失败: %s", stats["error"])
            else:
                logger.info(
                    "📊 本次运行: 新增文件=%d 变化=%d 抽取成功=%d 失败=%d "
                    "累计 pending=%d done=%d",
                    stats.get("scan_new", 0),
                    stats.get("scan_changed", 0),
                    stats.get("success", 0),
                    stats.get("failed", 0),
                    stats.get("pending", 0),
                    stats.get("done", 0),
                )
            tl.end(success="error" not in stats, info=str(stats))
        except Exception as e:
            logger.exception("管道异常: %s", e)
            tl.end(success=False, info=str(e))

        logger.info("⏱ 等待 %d 分钟后再次扫描...", interval_minutes)
        time.sleep(interval_sec)


def _llm_health_check() -> bool:
    """预检 LLM 连通性，失败则快速失败不白等"""
    try:
        chat("你好，请回复 OK", timeout=15)
        return True
    except Exception as e:
        logger.error("❌ LLM 预检失败: %s", e)
        return False


def run_once(scan: bool = True, limit: int | None = None, max_runtime_seconds: int | None = None, evidence_first: bool = True):
    """单次运行"""
    pipeline = KGPipeline(evidence_first=evidence_first)
    tl = TaskLogger("kg_extraction_pipeline")
    tl.start()
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        if scan:
            stats = loop.run_until_complete(pipeline.run(limit=limit, max_runtime_seconds=max_runtime_seconds))
        else:
            stats = loop.run_until_complete(pipeline.run_once(limit=limit, max_runtime_seconds=max_runtime_seconds))
        loop.close()

        logger.info("📊 结果: %s", stats)
        if "error" not in stats:
            logger.info(
                "✅ 完成: 抽取成功=%d 失败=%d "
                "累计 done=%d pending=%d",
                stats.get("success", 0),
                stats.get("failed", 0),
                stats.get("done", 0),
                stats.get("pending", 0),
            )
        tl.end(success="error" not in stats, info=str(stats))
        return stats
    except Exception as e:
        logger.exception("管道异常: %s", e)
        tl.end(success=False, info=str(e))
        return {"error": str(e)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="KG 抽取管道")
    parser.add_argument("--daemon", action="store_true", help="常驻模式")
    parser.add_argument("--interval", type=int, default=30,
                        help="扫描间隔（分钟，默认 30）")
    parser.add_argument("--once", action="store_true",
                        help="只处理 pending 文件，不扫描新文件")
    parser.add_argument("--limit", type=int, default=None,
                        help="最多处理 pending 文件数；0 表示只启动并退出，不触发 LLM")
    parser.add_argument("--max-runtime", type=int, default=None,
                        help="本次处理最大运行秒数，到时停止领取新文件")
    parser.add_argument("--legacy-direct-extract", action="store_true",
                        help="使用旧路径直接 LLM 抽取写 KG；默认走 Evidence-first")
    args = parser.parse_args()

    if args.daemon:
        run_daemon(args.interval, limit=args.limit, max_runtime_seconds=args.max_runtime, evidence_first=not args.legacy_direct_extract)
    else:
        run_once(scan=not args.once, limit=args.limit, max_runtime_seconds=args.max_runtime, evidence_first=not args.legacy_direct_extract)
