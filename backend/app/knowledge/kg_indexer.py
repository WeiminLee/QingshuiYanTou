"""
KG 提取索引 — 防重机制

记录每篇文档的 KG 提取状态，确保不重复提取。

架构原则（重要）：
  本地 = 处理中枢（提取 KG + 存储原始内容 + 存储结构化结果）

  本地必须存储原始 PDF 内容（包括文本/表格/图片描述），原因：
    1. LLM 总结和转义会有信息损耗，必须保留原文用于溯源
    2. 实体关系经过 LLM 处理后，可能偏离原始含义
    3. 表格和图片信息 LLM 无法直接处理，需单独提取存储
    4. 推理层溯源时需要回读原始上下文

  推理决策层从本地获取：
    - 原始内容（原始 PDF 文本 + 表格 + 图片描述）
    - KG 提取结果（节点/关系/状态跃迁/投资信号）

存储后端：MongoDB
Collection：kg_extraction_index
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# ── Collection 名 ─────────────────────────────────────────────────────────

COLLECTION_NAME = "kg_extraction_index"


def _get_collection():
    from app.core.mongodb import get_mongo_db

    db = get_mongo_db()
    return db[COLLECTION_NAME]


def _ensure_indexes():
    """确保索引存在"""
    col = _get_collection()
    try:
        col.create_index("ann_id", unique=True, sparse=True)
        col.create_index("doc_id", unique=True, sparse=True)
        col.create_index([("ts_code", 1), ("kg_status", 1)])
        col.create_index([("kg_status", 1), ("extracted_at", -1)])
        col.create_index([("content_hash", 1)])
    except Exception:
        pass  # 索引可能已存在


# ── 提取状态枚举 ────────────────────────────────────────────────────────


class ExtractionStatus:
    PENDING = "pending"  # 待提取
    RUNNING = "running"  # 提取中
    DONE = "done"  # 已完成
    FAILED = "failed"  # 提取失败
    SKIPPED = "skipped"  # 跳过（无文本或格式不支持）


# ── 核心 API ─────────────────────────────────────────────────────────


def check_extracted(ann_id: str | None = None, doc_id: str | None = None) -> dict | None:
    """
    查询文档是否已提取。

    Returns:
        None：未提取过
        dict：已提取记录（包含 kg_status / extracted_at / content_hash）
    """
    col = _get_collection()
    query: dict[str, str] = {}
    if ann_id:
        query["ann_id"] = ann_id
    elif doc_id:
        query["doc_id"] = doc_id
    else:
        return None
    return col.find_one(query)


def is_already_extracted(
    ann_id: str | None = None,
    doc_id: str | None = None,
    content_hash: str | None = None,
) -> tuple[bool, dict | None]:
    """
    判断文档是否需要提取。

    Returns:
        (是否已提取且无需重提, 现有记录)

    逻辑：
    - 无记录 → 需要提取
    - 有记录且状态为 DONE：
        - 有 content_hash 且相同 → 无需重提
        - 有 content_hash 且不同 → 内容变更，需要重提
    - 有记录且状态为 RUNNING → 正在提取，跳过
    - 有记录且状态为 FAILED → 重试
    """
    record = check_extracted(ann_id=ann_id, doc_id=doc_id)
    if not record:
        return False, None

    status = record.get("kg_status", "")

    if status == ExtractionStatus.RUNNING:
        return True, record  # 正在提取，跳过

    if status in (ExtractionStatus.FAILED, ExtractionStatus.SKIPPED):
        return False, record  # 失败/跳过，可重试

    if status == ExtractionStatus.DONE and content_hash:
        existing_hash = record.get("content_hash", "")
        if existing_hash and existing_hash != content_hash:
            return False, record  # 内容变更，需要重提
        return True, record  # 内容和状态都没变，无需重提

    return False, record


def mark_extracting(
    ann_id: str | None = None,
    doc_id: str | None = None,
    ts_code: str = "",
    title: str = "",
    doc_type: str = "",
    source_type: str = "",
    content_hash: str = "",
    file_size: int = 0,
) -> str:
    """
    标记文档开始提取（RUNNING 状态）。

    如果已有记录（FAILED/SKIPPED），更新状态。
    如果无记录，插入新记录。

    Returns:
        record_id (str)
    """
    _ensure_indexes()
    col = _get_collection()
    now = datetime.now()

    query: dict[str, str] = {}
    if ann_id:
        query["ann_id"] = ann_id
    elif doc_id:
        query["doc_id"] = doc_id
    else:
        raise ValueError("必须提供 ann_id 或 doc_id")

    record = col.find_one(query)

    update_doc = {
        "$set": {
            "kg_status": ExtractionStatus.RUNNING,
            "ts_code": ts_code,
            "title": title,
            "doc_type": doc_type,
            "source_type": source_type,
            "content_hash": content_hash,
            "file_size": file_size,
            "extracting_started_at": now,
            "updated_at": now,
        }
    }

    if record:
        col.update_one(query, update_doc)
        logger.debug("更新提取状态为 RUNNING: %s", ann_id or doc_id)
        return str(record.get("_id", ""))
    else:
        doc = {
            "ann_id": ann_id,
            "doc_id": doc_id,
            "ts_code": ts_code,
            "title": title,
            "doc_type": doc_type,  # 公告分类（annual_report/contract等）
            "source_type": source_type,  # research_report / announcement
            "pub_date": "",  # 发布时间 YYYYMMDD
            "file_size": file_size,
            # ── 提取状态 ──────────────────────────────────
            "kg_status": ExtractionStatus.RUNNING,
            "content_hash": content_hash,
            "extracting_started_at": now,
            "extracted_at": None,
            "updated_at": now,
            # ── 本地存储的原始内容（LLM总结有损耗，必须保留原文）─────
            "raw_text": "",  # PDF 原始文本（全文）
            "raw_tables": [],  # 表格 [{"page": 1, "content": "..."}]
            "raw_images": [],  # 图片描述 [{"page": 2, "description": "..."}]
            # ── KG 结构化结果（LLM 抽取 + 推断）─────────────────
            "kg_result": None,  # extract_text() 完整返回值
            "inferred_state": None,  # 行业状态
            "state_transitions": [],  # 状态跃迁列表
            "investment_signal": {},  # PRODUCTION_INFLECTION 等投资信号
            "signals": [],  # RuleBasedSignalExtractor 结果
            "conflict_alerts": [],  # CONTRADICTS 冲突
            # ── 统计 ──────────────────────────────────────
            "entities_count": 0,
            "relations_count": 0,
            "chunks_count": 0,
            "error_message": None,
        }
        result = col.insert_one(doc)
        logger.debug("新建提取记录: %s", ann_id or doc_id)
        return str(result.inserted_id)


def mark_done(
    ann_id: str | None = None,
    doc_id: str | None = None,
    kg_result: dict | None = None,
    state_transitions: list | None = None,
    investment_signal: dict | None = None,
    signals: list | None = None,
    raw_text: str = "",
    raw_tables: list | None = None,
    raw_images: list | None = None,
) -> bool:
    """
    标记文档提取完成，写入原始内容 + 结构化结果到本地 MongoDB。

    重要原则：
      原始内容（PDF 文本/表格/图片）是可信推理的根本，必须保留。
      LLM 总结和转义存在信息损耗，推理层溯源时必须能回读原文。

    Returns:
        True：更新成功
    """
    col = _get_collection()
    query: dict[str, str] = {}
    if ann_id:
        query["ann_id"] = ann_id
    elif doc_id:
        query["doc_id"] = doc_id
    else:
        return False

    now = datetime.now()
    update: dict = {
        "$set": {
            "kg_status": ExtractionStatus.DONE,
            "extracted_at": now,
            "updated_at": now,
            # ── 原始内容（可信佐证，LLM 总结有损耗）────────────────
            "raw_text": raw_text[:200000] if raw_text else "",
            "raw_tables": raw_tables or [],
            "raw_images": raw_images or [],
            # ── KG 结构化结果 ──────────────────────────────
            "kg_result": kg_result,
            "inferred_state": (kg_result or {}).get("inferred_state"),
            "state_transitions": state_transitions or [],
            "investment_signal": investment_signal or {},
            "signals": signals or [],
            # ── 统计字段 ──────────────────────────────
            "entities_count": (
                (kg_result or {}).get("entities_created", 0) + (kg_result or {}).get("entities_updated", 0)
            ),
            "relations_count": (
                (kg_result or {}).get("relations_created", 0) + (kg_result or {}).get("relations_updated", 0)
            ),
            "chunks_count": (kg_result or {}).get("chunks_processed", 0),
        }
    }

    result = col.update_one(query, update)
    logger.info("标记 DONE: %s (matched=%d)", ann_id or doc_id, result.matched_count)
    return result.matched_count > 0


def mark_failed(
    ann_id: str | None = None,
    doc_id: str | None = None,
    error_message: str = "",
) -> bool:
    """标记文档提取失败"""
    col = _get_collection()
    query: dict[str, str] = {}
    if ann_id:
        query["ann_id"] = ann_id
    elif doc_id:
        query["doc_id"] = doc_id
    else:
        return False

    result = col.update_one(
        query,
        {
            "$set": {
                "kg_status": ExtractionStatus.FAILED,
                "error_message": error_message,
                "updated_at": datetime.now(),
            }
        },
    )
    return result.matched_count > 0


def mark_skipped(
    ann_id: str | None = None,
    doc_id: str | None = None,
    reason: str = "",
) -> bool:
    """标记文档跳过（无文本/格式不支持）"""
    col = _get_collection()
    query: dict[str, str] = {}
    if ann_id:
        query["ann_id"] = ann_id
    elif doc_id:
        query["doc_id"] = doc_id
    else:
        return False

    result = col.update_one(
        query,
        {
            "$set": {
                "kg_status": ExtractionStatus.SKIPPED,
                "error_message": reason,
                "extracted_at": datetime.now(),
                "updated_at": datetime.now(),
            }
        },
    )
    return result.matched_count > 0


def compute_content_hash(text: str) -> str:
    """计算文本内容 hash（用于检测内容变更）"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ── 统计 ────────────────────────────────────────────────────────────────


def get_stats() -> dict:
    """获取提取统计"""
    col = _get_collection()
    pipeline = [
        {
            "$group": {
                "_id": "$kg_status",
                "count": {"$sum": 1},
            }
        }
    ]
    results = list(col.aggregate_documents(pipeline))
    stats = {r["_id"]: r["count"] for r in results}
    total = sum(stats.values())
    return {
        "total": total,
        "done": stats.get(ExtractionStatus.DONE, 0),
        "pending": stats.get(ExtractionStatus.PENDING, 0),
        "running": stats.get(ExtractionStatus.RUNNING, 0),
        "failed": stats.get(ExtractionStatus.FAILED, 0),
        "skipped": stats.get(ExtractionStatus.SKIPPED, 0),
    }
