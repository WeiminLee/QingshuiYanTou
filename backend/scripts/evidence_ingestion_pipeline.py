"""
Evidence 抽取管道 - 并发处理本地互动易/公告/研报数据

功能：
  1. 从 notices/reports 集合读取文件元数据
  2. 检查哪些文件已处理过（防重复）
  3. 并发提取 PDF 文本
  4. 按 token 分块，构建 evidence
  5. 存入 kg_evidence，job 存入 kg_extraction_jobs
  6. 记录处理进度

用法：
  # 处理全部
  python scripts/evidence_ingestion_pipeline.py

  # 只处理前 100 个文件
  python scripts/evidence_ingestion_pipeline.py --limit 100

  # 只处理研报
  python scripts/evidence_ingestion_pipeline.py --source reports

  # 常驻模式（每 30 分钟扫描一次）
  python scripts/evidence_ingestion_pipeline.py --daemon --interval 30
"""
import argparse
import concurrent.futures
import hashlib
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ.setdefault("UV_RUN", "1")

from dotenv import load_dotenv
load_dotenv()

from pymongo import MongoClient, ReturnDocument
from app.config import settings
from app.knowledge.evidence_builders import build_file_evidence
from app.knowledge.kg_extractor import _extract_text_from_file
from app.knowledge.evidence import (
    EVIDENCE_COLLECTION,
    EXTRACTOR_VERSION,
    EXTRACTION_JOBS_COLLECTION,
    JOB_COMBINED,
    JOB_VECTOR,
    STATUS_PENDING,
    EvidenceInput,
    default_source_confidence,
    stable_evidence_id,
    stable_job_id,
    text_checksum,
)
from app.core.task_logger import TaskLogger

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

# 并发控制
MAX_WORKERS = 5           # 最大并发线程数
SCAN_INTERVAL = 30 * 60  # 扫描间隔（秒）
CHUNK_MAX_TOKENS = 2048   # 每个 chunk 的最大 token 数
MAX_CHUNKS_PER_FILE = 8   # 每个文件最多 chunk 数

# 处理状态
STATUS_PENDING = "pending"
STATUS_PROCESSING = "processing"
STATUS_DONE = "done"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"

# 集合名
EVIDENCE_PROGRESS_COLLECTION = "evidence_ingestion_progress"


def _utc_now():
    return datetime.now(timezone.utc)


def _normalize_source_type(source: str, file_name: str) -> str:
    """根据来源和文件名判断 source_type"""
    source_lower = source.lower()
    fname_lower = file_name.lower()

    if source_lower == "reports" or "report" in fname_lower or "研报" in file_name:
        return "research_report"
    elif source_lower == "notices":
        if "投资者关系活动记录表" in file_name or "互动易" in file_name:
            return "irm"
        else:
            return "announcement"
    return "document"


def _normalize_date(value: Any) -> str | None:
    """Convert datetime.date or datetime.datetime to ISO string for MongoDB."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=timezone.utc).isoformat()
    if isinstance(value, str):
        return value.strip() or None
    return str(value) or None


class EvidenceServiceSync:
    """同步版本的 Evidence Service"""

    def __init__(self, db):
        self._db = db
        self._evidence = db[EVIDENCE_COLLECTION]
        self._jobs = db[EXTRACTION_JOBS_COLLECTION]

    def ensure_indexes(self):
        """创建必要的索引"""
        self._evidence.create_index("evidence_id", unique=True)
        self._evidence.create_index("checksum")
        self._evidence.create_index("source_type")
        self._evidence.create_index("subject_hint.ts_code")
        self._evidence.create_index("publish_date")
        self._jobs.create_index("job_id", unique=True)
        self._jobs.create_index("evidence_id")
        self._jobs.create_index("status")
        self._jobs.create_index("job_type")

    def upsert_evidence(self, input: EvidenceInput, chunk_index: int = 0) -> dict[str, Any]:
        """插入或更新 evidence"""
        now = _utc_now()
        text = input.text_excerpt or ""
        evidence_id = stable_evidence_id(input.source_type, input.source_id, chunk_index, text)
        checksum = text_checksum(text)
        confidence = input.confidence
        if confidence is None:
            confidence = default_source_confidence(input.source_type)

        doc = {
            "evidence_id": evidence_id,
            "source_type": input.source_type,
            "source_name": input.source_name,
            "source_id": input.source_id,
            "subject_hint": dict(input.subject_hint or {}),
            "publish_date": _normalize_date(input.publish_date),
            "observed_at": _normalize_date(input.observed_at) or now,
            "text_excerpt": text,
            "source_ref": dict(input.source_ref or {}),
            "checksum": checksum,
            "confidence": float(confidence),
            "metadata": dict(input.metadata or {}),
            "updated_at": now,
        }
        set_on_insert = {
            "created_at": now,
            "extraction_status": {
                JOB_COMBINED: STATUS_PENDING,
                JOB_VECTOR: STATUS_PENDING,
                "last_extracted_at": None,
                "extractor_version": EXTRACTOR_VERSION,
            },
        }
        self._evidence.update_one(
            {"evidence_id": evidence_id},
            {"$set": doc, "$setOnInsert": set_on_insert},
            upsert=True,
        )
        saved = self._evidence.find_one({"evidence_id": evidence_id}, {"_id": 0})
        return dict(saved) if saved else {**set_on_insert, **doc}

    def enqueue_job(self, evidence_id: str, job_type: str) -> dict[str, Any]:
        """入队抽取 job"""
        now = _utc_now()
        job_id = stable_job_id(evidence_id, job_type, EXTRACTOR_VERSION)
        doc = {
            "job_id": job_id,
            "evidence_id": evidence_id,
            "job_type": job_type,
            "status": STATUS_PENDING,
            "retry_count": 0,
            "error": None,
            "extractor_version": EXTRACTOR_VERSION,
            "locked_by": None,
            "locked_at": None,
            "started_at": None,
            "finished_at": None,
            "created_at": now,
            "updated_at": now,
        }
        self._jobs.update_one(
            {"job_id": job_id},
            {"$setOnInsert": doc},
            upsert=True,
        )
        saved = self._jobs.find_one({"job_id": job_id}, {"_id": 0})
        return dict(saved) if saved else doc

    def enqueue_default_jobs(self, evidence_id: str) -> list[dict[str, Any]]:
        """入队默认的 combined 和 vector jobs"""
        return [
            self.enqueue_job(evidence_id, JOB_COMBINED),
            self.enqueue_job(evidence_id, JOB_VECTOR),
        ]


class EvidenceIngestionPipeline:
    """Evidence 抽取管道（多线程版本）"""

    def __init__(self):
        # 使用同步 pymongo 客户端
        self._client = MongoClient(settings.mongodb_url)
        db_name = settings.mongodb_url.split("/")[-1].split("?")[0] or "qingniu"
        self._db = self._client[db_name]
        self._evidence_service = EvidenceServiceSync(self._db)

    def ensure_indexes(self):
        """创建必要的索引"""
        progress_coll = self._db[EVIDENCE_PROGRESS_COLLECTION]
        progress_coll.create_index("file_path", unique=True)
        progress_coll.create_index("source")
        progress_coll.create_index("status")
        progress_coll.create_index("updated_at")
        progress_coll.create_index([("status", 1), ("updated_at", 1)])
        self._evidence_service.ensure_indexes()
        logger.info("索引已创建")

    def is_already_processed(self, file_path: str) -> bool:
        """检查文件是否已处理过"""
        progress = self._db[EVIDENCE_PROGRESS_COLLECTION]
        doc = progress.find_one({"file_path": file_path, "status": STATUS_DONE})
        return doc is not None

    def mark_processing(self, file_path: str, source: str, metadata: dict):
        """标记文件开始处理"""
        progress = self._db[EVIDENCE_PROGRESS_COLLECTION]
        progress.update_one(
            {"file_path": file_path},
            {
                "$set": {
                    "status": STATUS_PROCESSING,
                    "source": source,
                    "metadata": metadata,
                    "updated_at": _utc_now(),
                },
                "$setOnInsert": {
                    "created_at": _utc_now(),
                }
            },
            upsert=True,
        )

    def mark_done(self, file_path: str, evidence_count: int, chunk_count: int):
        """标记文件处理完成"""
        progress = self._db[EVIDENCE_PROGRESS_COLLECTION]
        progress.update_one(
            {"file_path": file_path},
            {
                "$set": {
                    "status": STATUS_DONE,
                    "evidence_count": evidence_count,
                    "chunk_count": chunk_count,
                    "updated_at": _utc_now(),
                }
            },
        )

    def mark_failed(self, file_path: str, error: str):
        """标记文件处理失败"""
        progress = self._db[EVIDENCE_PROGRESS_COLLECTION]
        progress.update_one(
            {"file_path": file_path},
            {
                "$set": {
                    "status": STATUS_FAILED,
                    "error": error[:500],
                    "updated_at": _utc_now(),
                }
            },
        )

    def mark_skipped(self, file_path: str, reason: str):
        """标记文件跳过"""
        progress = self._db[EVIDENCE_PROGRESS_COLLECTION]
        progress.update_one(
            {"file_path": file_path},
            {
                "$set": {
                    "status": STATUS_SKIPPED,
                    "skip_reason": reason[:200],
                    "updated_at": _utc_now(),
                }
            },
        )

    def _fix_file_path(self, file_path: str) -> str:
        """修复文件路径（远程路径转本地路径）"""
        for base in ["/home/code/QingShuiTouYan/backend", "/home/lwm/code/QingShuiTouYan/backend"]:
            if base in file_path:
                return file_path.replace(base, "/home/lwm/code/QingShuiTouYan/backend")
        return file_path

    def get_pending_files(self, source: str | None = None, limit: int = 100) -> list[dict]:
        """获取待处理文件列表"""
        sources = ["notices", "reports"] if source is None else [source]
        pending_files = []

        for src in sources:
            coll_name = src
            coll = self._db[coll_name]

            # 获取所有文件
            for doc in coll.find({}):
                file_path = doc.get("file_path", "")
                if not file_path:
                    continue

                # 检查是否已处理
                if self.is_already_processed(file_path):
                    continue

                # 检查文件是否存在
                local_path = self._fix_file_path(file_path)
                if not Path(local_path).exists():
                    self.mark_skipped(file_path, "file_not_found")
                    continue

                pending_files.append({
                    "file_path": file_path,
                    "local_path": local_path,
                    "source": src,
                    "metadata": {
                        "ts_code": doc.get("ts_code", ""),
                        "file_name": doc.get("file_name", ""),
                        "title": doc.get("title", doc.get("file_name", "")),
                        "source": src,
                    }
                })

                if len(pending_files) >= limit:
                    return pending_files

        return pending_files

    def process_file(self, file_info: dict) -> dict:
        """处理单个文件（在线程池中执行）"""
        file_path = file_info["file_path"]
        local_path = file_info["local_path"]
        source = file_info["source"]
        metadata = file_info["metadata"]

        self.mark_processing(file_path, source, metadata)

        try:
            # 提取文本
            path = Path(local_path)
            if path.suffix.lower() == ".pdf":
                text = _extract_text_from_file(path, ".pdf")
            elif path.suffix.lower() in [".txt", ".md"]:
                text = path.read_text(encoding="utf-8", errors="replace")
            else:
                self.mark_skipped(file_path, f"unsupported_file_type: {path.suffix}")
                return {"status": "skipped", "reason": "unsupported file type"}

            if not text or not text.strip():
                self.mark_skipped(file_path, "empty_text")
                return {"status": "skipped", "reason": "empty text"}

            # 获取文件信息
            ts_code = metadata.get("ts_code", "")
            file_name = metadata.get("file_name", "")
            title = metadata.get("title", file_name)

            # 判断 source_type
            source_type = _normalize_source_type(source, file_name)

            # 构建 file_info 字典
            file_info_dict = {
                "file_path": file_path,
                "file_name": file_name,
                "title": title,
                "ts_code": ts_code,
                "source_type": source_type,
                "doc_type": source_type,
            }

            # 计算文件 hash
            try:
                with open(path, "rb") as f:
                    file_hash = hashlib.sha256(f.read()).hexdigest()
                file_info_dict["file_hash"] = file_hash
            except Exception:
                pass

            # 构建 evidence
            evidence_items = build_file_evidence(
                file_info=file_info_dict,
                text=text,
                source_type=source_type,
                doc_type=source_type,
                ts_code=ts_code,
                chunk_max_tokens=CHUNK_MAX_TOKENS,
                max_chunks=MAX_CHUNKS_PER_FILE,
            )

            # 存入 evidence 库
            evidence_count = 0
            chunk_count = len(evidence_items)
            for idx, item in enumerate(evidence_items):
                saved = self._evidence_service.upsert_evidence(item, chunk_index=idx)
                if saved:
                    evidence_count += 1
                # 创建抽取 job
                self._evidence_service.enqueue_default_jobs(saved["evidence_id"])

            # 标记完成
            self.mark_done(file_path, evidence_count, chunk_count)

            logger.info(f"✅ 完成: {file_name} | evidence={evidence_count} chunks={chunk_count}")
            return {
                "status": "success",
                "evidence_count": evidence_count,
                "chunk_count": chunk_count,
            }

        except Exception as e:
            logger.warning(f"❌ 失败: {file_path} -> {e}")
            self.mark_failed(file_path, str(e))
            return {"status": "failed", "reason": str(e)}

    def run(
        self,
        source: str | None = None,
        limit: int | None = None,
        max_runtime_seconds: int | None = None,
    ) -> dict:
        """完整运行（多线程并发）"""
        self.ensure_indexes()

        result = {
            "total": 0,
            "success": 0,
            "failed": 0,
            "skipped": 0,
            "limit_reached": False,
            "runtime_exhausted": False,
        }

        start_time = time.time()
        deadline = start_time + max_runtime_seconds if max_runtime_seconds and max_runtime_seconds > 0 else None

        while True:
            if limit is not None and result["total"] >= limit:
                result["limit_reached"] = True
                break
            if deadline is not None and time.time() >= deadline:
                result["runtime_exhausted"] = True
                break

            # 获取待处理文件
            batch_limit = MAX_WORKERS * 2
            if limit is not None:
                batch_limit = min(batch_limit, max(0, limit - result["total"]))
            if batch_limit <= 0:
                result["limit_reached"] = True
                break

            pending = self.get_pending_files(source=source, limit=batch_limit)
            if not pending:
                logger.info("没有更多待处理文件")
                break

            # 多线程并发处理
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                futures = {executor.submit(self.process_file, f): f for f in pending}
                for future in as_completed(futures):
                    f = futures[future]
                    try:
                        res = future.result()
                    except Exception as e:
                        res = {"status": "failed", "reason": str(e)}

                    result["total"] += 1
                    if isinstance(res, dict):
                        if res.get("status") == "success":
                            result["success"] += 1
                        elif res.get("status") == "skipped":
                            result["skipped"] += 1
                        else:
                            result["failed"] += 1
                    else:
                        result["failed"] += 1

                    # 检查是否超时
                    if deadline is not None and time.time() >= deadline:
                        result["runtime_exhausted"] = True
                        # 取消剩余的 futures
                        for f2 in futures:
                            f2.cancel()
                        break

        return result

    def get_stats(self) -> dict:
        """获取统计信息"""
        progress = self._db[EVIDENCE_PROGRESS_COLLECTION]

        # 按状态统计
        pipeline = [
            {"$group": {"_id": "$status", "count": {"$sum": 1}}},
            {"$sort": {"_id": 1}},
        ]
        status_stats = {}
        for row in progress.aggregate(pipeline):
            status_stats[str(row["_id"])] = int(row["count"])

        total_in_progress = progress.count_documents({})
        total_notices = self._db.notices.count_documents({})
        total_reports = self._db.reports.count_documents({})

        # Evidence 统计
        evidence_count = self._db[EVIDENCE_COLLECTION].count_documents({})
        jobs_total = self._db[EXTRACTION_JOBS_COLLECTION].count_documents({})

        # Job 状态统计
        job_pipeline = [
            {"$group": {"_id": "$status", "count": {"$sum": 1}}},
        ]
        jobs_by_status = {}
        for row in self._db[EXTRACTION_JOBS_COLLECTION].aggregate(job_pipeline):
            jobs_by_status[str(row["_id"])] = int(row["count"])

        return {
            "progress_total": total_in_progress,
            "progress_by_status": status_stats,
            "source_notices": total_notices,
            "source_reports": total_reports,
            "evidence": evidence_count,
            "jobs": jobs_total,
            "jobs_by_status": jobs_by_status,
        }


def run_daemon(interval_minutes: int, source: str | None = None, limit: int | None = None):
    """常驻模式"""
    interval_sec = interval_minutes * 60
    pipeline = EvidenceIngestionPipeline()
    logger.info(f"🚀 Evidence 抽取管道启动（常驻模式，间隔 {interval_minutes} 分钟）")

    while True:
        tl = TaskLogger("evidence_ingestion")
        tl.start()
        try:
            stats = pipeline.run(source=source, limit=limit)
            logger.info(f"📊 本次运行: success={stats['success']} failed={stats['failed']} skipped={stats['skipped']}")
            tl.end(success=stats["success"] > 0, info=str(stats))
        except Exception as e:
            logger.exception(f"管道异常: {e}")
            tl.end(success=False, info=str(e))

        logger.info(f"⏱ 等待 {interval_minutes} 分钟后再次扫描...")
        time.sleep(interval_sec)


def run_once(source: str | None = None, limit: int | None = None, max_runtime_seconds: int | None = None):
    """单次运行"""
    pipeline = EvidenceIngestionPipeline()
    tl = TaskLogger("evidence_ingestion")
    tl.start()

    try:
        stats = pipeline.run(source=source, limit=limit, max_runtime_seconds=max_runtime_seconds)
        logger.info(f"📊 结果: {stats}")
        tl.end(success=stats["success"] > 0, info=str(stats))
        return stats
    except Exception as e:
        logger.exception(f"管道异常: {e}")
        tl.end(success=False, info=str(e))
        return {"error": str(e)}


def show_stats():
    """显示统计信息"""
    pipeline = EvidenceIngestionPipeline()
    stats = pipeline.get_stats()

    print("=" * 80)
    print("📊 Evidence 抽取统计")
    print("=" * 80)
    print(f"源数据:")
    print(f"  notices (互动易/公告): {stats['source_notices']}")
    print(f"  reports (研报): {stats['source_reports']}")
    print()
    print(f"处理进度:")
    for status, count in stats.get("progress_by_status", {}).items():
        print(f"  {status}: {count}")
    print(f"  总计: {stats['progress_total']}")
    print()
    print(f"Evidence 库:")
    print(f"  Evidence 数量: {stats['evidence']}")
    print(f"  Job 数量: {stats['jobs']}")
    print(f"  Job 状态:")
    for status, count in stats.get("jobs_by_status", {}).items():
        print(f"    {status}: {count}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evidence 抽取管道")
    parser.add_argument("--daemon", action="store_true", help="常驻模式")
    parser.add_argument("--interval", type=int, default=30, help="扫描间隔（分钟，默认 30）")
    parser.add_argument("--source", choices=["notices", "reports"], help="只处理指定来源")
    parser.add_argument("--limit", type=int, default=None, help="最多处理文件数")
    parser.add_argument("--max-runtime", type=int, default=None, help="本次处理最大运行秒数")
    parser.add_argument("--stats", action="store_true", help="显示统计信息并退出")
    args = parser.parse_args()

    if args.stats:
        show_stats()
    elif args.daemon:
        run_daemon(args.interval, source=args.source, limit=args.limit)
    else:
        run_once(source=args.source, limit=args.limit, max_runtime_seconds=args.max_runtime)
