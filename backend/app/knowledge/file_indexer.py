"""
KG 文件索引管理器（异步版，motor）

职责：
- 扫描本地报告目录（industry_reports / stock_reports）
- 维护 MongoDB kg_file_index collection，记录每个文件的抽取状态
- 增量检测：新增文件 / 内容 hash 变化 → pending
- 提供待抽取文件列表（供 extractor 调用）

索引 Key：file_path（绝对路径）+ file_hash（SHA256，内容指纹）
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

logger = logging.getLogger(__name__)

# 监控目录
REPORT_DIRS = [
    "/home/10241671/DataSets/Stocks/industry_reports",
    "/home/10241671/DataSets/Stocks/stock_reports",
]

ALLOWED_EXTENSIONS = {".md", ".pdf"}

# 例：华工科技(000988)深度研究 → 000988.SZ
_STOCK_CODE_RE = re.compile(r"\((\d{6})\)")


def _parse_ts_code_from_filename(filename: str) -> Optional[str]:
    """从文件名解析 ts_code"""
    m = _STOCK_CODE_RE.search(filename)
    if m:
        code = m.group(1)
        if code.startswith(("000", "300", "200")):
            return f"{code}.SZ"
        return f"{code}.SH"
    return None


def _compute_file_hash(file_path: Path) -> str:
    """计算文件 SHA256，内容指纹"""
    h = hashlib.sha256()
    try:
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception as e:
        logger.warning("无法计算 hash: %s: %s", file_path, e)
        stat = file_path.stat()
        return hashlib.sha256(
            f"{file_path}:{stat.st_mtime}:{stat.st_size}".encode()
        ).hexdigest()


class FileIndexer:
    """
    文件索引管理器（async）

    用法：
        indexer = FileIndexer(db)
        await indexer.scan_and_index()
        pending = await indexer.get_pending_files()
        await indexer.mark_extracting(path)
        await indexer.mark_done(path, n, m)
        await indexer.mark_failed(path, error)
    """

    COLLECTION = "kg_file_index"

    def __init__(self, db: AsyncIOMotorDatabase):
        self._db = db
        self._col = db[self.COLLECTION]

    async def ensure_indexes(self) -> None:
        await self._col.create_index("file_path", unique=True)
        await self._col.create_index("cninfo_id")
        await self._col.create_index("status")
        await self._col.create_index("file_type")
        await self._col.create_index("created_at")

    # ── 扫描与索引 ──────────────────────────────────────────

    async def scan_and_index(self) -> dict:
        """
        扫描所有监控目录，增量更新索引。

        Returns:
            {"new": [...], "changed": [...], "unchanged": int, "removed": int}
        """
        await self.ensure_indexes()
        result = {"new": [], "changed": [], "unchanged": 0, "removed": 0}
        now = datetime.utcnow()

        for base_dir in REPORT_DIRS:
            dir_path = Path(base_dir)
            if not dir_path.exists():
                logger.warning("监控目录不存在: %s", base_dir)
                continue

            for entry in os.scandir(dir_path):
                if not entry.is_file():
                    continue

                file_path = Path(entry.path)
                ext = file_path.suffix.lower()
                if ext not in ALLOWED_EXTENSIONS:
                    continue

                stat = entry.stat()
                file_size = stat.st_size
                mtime = stat.st_mtime

                doc = await self._col.find_one({"file_path": str(file_path)})

                if doc is None:
                    # 新文件
                    file_hash = _compute_file_hash(file_path)
                    ts_code = _parse_ts_code_from_filename(file_path.name)
                    await self._col.insert_one({
                        "file_path": str(file_path),
                        "file_name": file_path.name,
                        "file_type": ext[1:],
                        "file_size": file_size,
                        "mtime": mtime,
                        "file_hash": file_hash,
                        "status": "pending",
                        "ts_code": ts_code,
                        "entities_count": 0,
                        "relations_count": 0,
                        "extracted_at": None,
                        "error": None,
                        "retry_count": 0,
                        "schema_version": "v4",
                        "parser_version": "v4",
                        "created_at": now,
                        "updated_at": now,
                    })
                    result["new"].append(file_path.name)
                    logger.info("新文件: %s", file_path.name)

                elif doc["mtime"] != mtime or doc["file_size"] != file_size:
                    file_hash = _compute_file_hash(file_path)
                    if file_hash != doc["file_hash"]:
                        await self._col.update_one(
                            {"file_path": str(file_path)},
                            {"$set": {
                                "file_hash": file_hash,
                                "file_size": file_size,
                                "mtime": mtime,
                                "status": "pending",
                                "entities_count": 0,
                                "relations_count": 0,
                                "extracted_at": None,
                                "error": None,
                                "schema_version": "v4",
                                "parser_version": "v4",
                                "updated_at": now,
                            }}
                        )
                        result["changed"].append(file_path.name)
                        logger.info("内容变化: %s", file_path.name)
                    else:
                        await self._col.update_one(
                            {"file_path": str(file_path)},
                            {"$set": {"mtime": mtime, "updated_at": now}}
                        )
                        result["unchanged"] += 1
                else:
                    result["unchanged"] += 1

        # 清理已删除文件
        async for doc in self._col.find({}, {"file_path": 1}):
            if not Path(doc["file_path"]).exists():
                await self._col.update_one(
                    {"file_path": doc["file_path"]},
                    {"$set": {"status": "skipped", "updated_at": now}}
                )
                result["removed"] += 1
                logger.info("已删除: %s", doc["file_path"])

        return result

    # ── 状态管理 ──────────────────────────────────────────

    async def get_pending_files(
        self,
        limit: int = 10,
        exclude_types: Optional[set[str]] = None,
    ) -> list[dict]:
        """获取待抽取文件列表"""
        query: dict = {"status": "pending"}
        if exclude_types:
            query["file_type"] = {"$nin": list(exclude_types)}

        cursor = self._col.find(query, {"_id": 0}).sort("created_at", 1).limit(limit)
        files = []
        async for doc in cursor:
            files.append(doc)
        return files

    async def get_file_info(self, file_path: str) -> Optional[dict]:
        doc = await self._col.find_one({"file_path": file_path}, {"_id": 0})
        return doc

    async def find_files_by_status(self, status: str, limit: int = 100) -> list[dict]:
        cursor = self._col.find({"status": status}, {"_id": 0}).sort("updated_at", 1).limit(limit)
        return [doc async for doc in cursor]

    async def get_extracting_files(self, older_than_minutes: int = 30) -> list[dict]:
        cutoff = datetime.utcnow() - timedelta(minutes=older_than_minutes)
        cursor = self._col.find(
            {"status": "extracting", "updated_at": {"$lt": cutoff}},
            {"_id": 0},
        )
        return [doc async for doc in cursor]

    async def mark_extracting(
        self,
        file_path: str,
        source_type: str | None = None,
        doc_type: str | None = None,
    ) -> None:
        update = {
            "status": "extracting",
            "schema_version": "v4",
            "parser_version": "v4",
            "updated_at": datetime.utcnow(),
        }
        if source_type:
            update["source_type"] = source_type
        if doc_type:
            update["doc_type"] = doc_type
        await self._col.update_one(
            {"file_path": file_path},
            {"$set": update},
            upsert=True,
        )

    async def mark_extracting_status(self, file_paths: list[str]) -> int:
        if not file_paths:
            return 0
        result = await self._col.update_many(
            {"file_path": {"$in": file_paths}},
            {"$set": {
                "status": "extracting",
                "schema_version": "v4",
                "parser_version": "v4",
                "updated_at": datetime.utcnow(),
            }},
        )
        return int(result.modified_count)

    async def mark_done(
        self,
        file_path: str,
        entities_count: int,
        relations_count: int,
        source_type: str | None = None,
        doc_type: str | None = None,
    ) -> None:
        update = {
            "status": "done",
            "entities_count": entities_count,
            "relations_count": relations_count,
            "extracted_at": datetime.utcnow(),
            "schema_version": "v4",
            "parser_version": "v4",
            "error": None,
            "updated_at": datetime.utcnow(),
        }
        if source_type:
            update["source_type"] = source_type
        if doc_type:
            update["doc_type"] = doc_type
        await self._col.update_one(
            {"file_path": file_path},
            {"$set": update}
        )

    async def mark_failed(
        self,
        file_path: str,
        error: str,
        max_retries: int = 3,
    ) -> None:
        doc = await self._col.find_one(
            {"file_path": file_path}, {"retry_count": 1}
        )
        retry_count = (doc.get("retry_count") or 0) + 1
        if retry_count >= max_retries:
            new_status = "failed"
            logger.error("抽取失败已达上限 %d: %s", max_retries, file_path)
        else:
            new_status = "pending"
            logger.warning("抽取失败（重试 %d/%d）: %s", retry_count, max_retries, file_path)

        await self._col.update_one(
            {"file_path": file_path},
            {"$set": {
                "status": new_status,
                "error": error[:500],
                "last_error": error[:1000],
                "retry_count": retry_count,
                "updated_at": datetime.utcnow(),
            }}
        )

    async def find_files_older_than(self, cutoff_date: datetime, limit: int = 1000) -> list[dict]:
        cursor = self._col.find(
            {
                "created_at": {"$lt": cutoff_date},
                "file_path": {"$nin": [None, ""]},
            },
            {"_id": 0},
        ).sort("created_at", 1).limit(limit)
        return [doc async for doc in cursor]

    async def clear_file_path(self, cninfo_id: str) -> bool:
        result = await self._col.update_one(
            {"cninfo_id": cninfo_id},
            {"$set": {
                "file_path": None,
                "status": "rotated",
                "rotated_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
            }},
        )
        return bool(result.modified_count)

    async def heal_extracting(self) -> int:
        """
        将所有卡在 extracting 的记录重置回 pending。

        捕获场景：Ctrl+C / 进程崩溃 / LLM 超时未归还
        """
        result = await self._col.update_many(
            {"status": "extracting"},
            {"$set": {
                "status": "pending",
                "error": "进程中断，上次抽取未完成",
                "updated_at": datetime.utcnow(),
            }}
        )
        return result.modified_count

    # ── 统计 ──────────────────────────────────────────

    async def get_stats(self) -> dict:
        """获取索引统计"""
        pipeline = [
            {"$group": {"_id": "$status", "count": {"$sum": 1}}}
        ]
        status_counts = {}
        async for r in self._col.aggregate(pipeline):
            status_counts[r["_id"]] = r["count"]

        total_pipeline = [
            {"$group": {"_id": None, "total": {"$sum": "$file_size"}}}
        ]
        total = 0
        async for r in self._col.aggregate(total_pipeline):
            total = r.get("total", 0)
            break

        return {
            "total_files": await self._col.count_documents({}),
            "by_status": status_counts,
            "total_size_mb": round(total / 1024 / 1024, 1),
            "pending": status_counts.get("pending", 0),
            "done": status_counts.get("done", 0),
            "failed": status_counts.get("failed", 0),
            "extracting": status_counts.get("extracting", 0),
            "skipped": status_counts.get("skipped", 0),
        }
