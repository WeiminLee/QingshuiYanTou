"""Evidence builders for announcements (chapter-chunked) and IRM (unchunked).

公告: 读取本地 PDF → 按章节分块 → 每个章节一个 EvidenceInput
互动易: 每条 Q&A → 一个 EvidenceInput（不分块）
"""

from __future__ import annotations

import os
from datetime import UTC, date, datetime
from typing import Any

from app.knowledge.evidence import EvidenceInput, default_source_confidence
from app.knowledge.ingestion.chunker import SmartChunker
from app.knowledge.ingestion.pdf_parser import extract_text_from_pdf

logger = __import__("logging").getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(UTC)


# 旧路径前缀 → 新路径前缀
PATH_PREFIX_MAP = {"/home/lwm/qingshui_data": "/run/media/lwm/0E27099B0E27099B/qingshui_data"}


def _map_file_path(file_path: str | None) -> str | None:
    """将旧路径映射到新路径"""
    if not file_path:
        return None
    for old_prefix, new_prefix in PATH_PREFIX_MAP.items():
        if file_path.startswith(old_prefix):
            return file_path.replace(old_prefix, new_prefix)
    return file_path


def _file_exists(file_path: str | None) -> bool:
    """检查文件是否存在"""
    return bool(file_path and os.path.exists(file_path))


def _split_pdf_chapters(file_path: str) -> list[dict] | None:
    """解析本地 PDF 并按章节切分，返回分块列表"""
    try:
        # 使用 SmartChunker 进行智能分块
        chunker = SmartChunker(max_tokens=4096)
        text = extract_text_from_pdf(file_path)
        if not text.strip():
            return None

        chunks = chunker.chunk(text)

        return [
            {
                "heading": c.heading,
                "body": c.text,
                "tokens": c.tokens,
                "source": c.source,
            }
            for c in chunks
        ]
    except Exception as e:
        logger.warning(f"PDF 解析失败 [{file_path}]: {e}")
        return None


def build_announcement_evidence(
    record: dict[str, Any],
) -> list[EvidenceInput]:
    """从 announcements 记录构建 EvidenceInput 列表。

    每个章节作为一个独立的 Evidence，通过 chapter_index 区分。

    本地 PDF 路径：file_path（需映射到新路径）
    如果本地有 PDF 则解析章节；否则回退到 title-only。

    Args:
        record: 数据库行（含 id, ann_date, ts_code, name, title, announcement_type, pdf_url, file_path 等）

    Returns:
        list[EvidenceInput]: 每个章节一个 EvidenceInput
    """
    ann_id = record.get("id") or ""
    title = (record.get("title") or "").strip()
    ts_code = (record.get("ts_code") or "").strip()
    ann_date_raw = record.get("ann_date")
    # Convert date/datetime to ISO string for MongoDB
    if ann_date_raw is None:
        ann_date = None
    elif isinstance(ann_date_raw, date):
        ann_date = ann_date_raw.isoformat()
    elif isinstance(ann_date_raw, datetime):
        ann_date = ann_date_raw.isoformat()
    else:
        ann_date = str(ann_date_raw) if ann_date_raw else None
    ann_type = (record.get("announcement_type") or "").strip()
    pdf_url = (record.get("pdf_url") or "").strip()
    company_name = (record.get("name") or "").strip()

    source_id = str(ann_id)

    # 映射本地 PDF 路径
    raw_path = record.get("file_path")
    local_pdf = _map_file_path(raw_path)
    has_local_pdf = _file_exists(local_pdf)

    # 解析章节
    chapters: list[dict] = []
    if has_local_pdf:
        chapters = _split_pdf_chapters(local_pdf) or []

    # 回退：PDF 不可用时只用 title
    if not chapters:
        chapters = [{"heading": "", "body": title}]

    evidence_list: list[EvidenceInput] = []
    for i, ch in enumerate(chapters):
        chunk_text = f"# {ch['heading']}\n\n{ch['body']}" if ch["heading"] else ch["body"]
        evidence_list.append(
            EvidenceInput(
                source_type="announcement",
                source_name=f"公告:{ts_code}" if ts_code else "公告",
                source_id=source_id,
                text_excerpt=chunk_text,
                subject_hint={
                    "ts_code": ts_code,
                    "name": company_name,
                    "ann_type": ann_type,
                    "title": title,
                },
                publish_date=ann_date,
                observed_at=_utc_now(),
                source_ref={
                    "source_table": "announcements",
                    "ann_id": ann_id,
                    "ann_date": ann_date,
                    "local_pdf": local_pdf if has_local_pdf else None,
                    "pdf_url": pdf_url,
                    "chapter_index": i,
                    "chapter_heading": ch["heading"],
                },
                confidence=default_source_confidence("announcement"),
                metadata={"title": title, "chapter_count": len(chapters), "has_pdf": has_local_pdf},
            )
        )

    return evidence_list


def build_irm_evidence(record: dict[str, Any]) -> EvidenceInput:
    """从 announcements (irm:*) 记录构建 EvidenceInput。

    每条互动易 Q&A 作为一个 Evidence，不分块。

    IRM 数据结构：
    - title: 问题内容
    - type: 回答内容（注意：不是 content 字段！）
    """
    ann_id = record.get("id") or ""
    question = (record.get("title") or "").strip()
    # IRM 回答在 type 字段，不是 content 字段
    answer = (record.get("type") or "").strip()
    ts_code = (record.get("ts_code") or "").strip()
    ann_date_raw = record.get("ann_date")
    if ann_date_raw is None:
        ann_date = None
    elif isinstance(ann_date_raw, date):
        ann_date = ann_date_raw.isoformat()
    elif isinstance(ann_date_raw, datetime):
        ann_date = ann_date_raw.isoformat()
    else:
        ann_date = str(ann_date_raw) if ann_date_raw else None
    ann_type = (record.get("announcement_type") or "").strip()
    company_name = (record.get("name") or "").strip()

    # 构造 text_excerpt
    if answer:
        text_excerpt = f"问：{question}\n答：{answer}"
    else:
        text_excerpt = question

    return EvidenceInput(
        source_type="irm",
        source_name=f"互动易:{ts_code}" if ts_code else "互动易",
        source_id=str(ann_id),
        text_excerpt=text_excerpt,
        subject_hint={
            "ts_code": ts_code,
            "name": company_name,
            "irm_type": ann_type,
        },
        publish_date=ann_date,
        observed_at=_utc_now(),
        source_ref={
            "source_table": "announcements",
            "ann_id": ann_id,
            "ann_date": ann_date,
            "ann_type": ann_type,
        },
        confidence=default_source_confidence("irm"),
        metadata={
            "question": question,
            "answer": answer,
            "irm_type": ann_type,
        },
    )
