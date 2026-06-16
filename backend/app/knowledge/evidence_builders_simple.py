"""Evidence builders for announcements (chapter-chunked) and IRM (unchunked).

公告: 下载 PDF → 按章节分块 → 每个章节一个 EvidenceInput
互动易: 每条 Q&A → 一个 EvidenceInput（不分块）
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from app.knowledge.evidence import EvidenceInput, default_source_confidence
from app.knowledge.ingestion.announcement_parser import (
    download_announcement_pdf,
    parse_pdf_text,
    split_by_chapters,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def build_announcement_evidence(
    record: dict[str, Any],
    download_pdf: bool = True,
) -> list[EvidenceInput]:
    """从 minishare_announcements 记录构建 EvidenceInput 列表。

    每个章节作为一个独立的 Evidence，通过 chunk_index 区分。

    Args:
        record: 数据库行（含 id, ann_date, ts_code, name, title, type, source_url 等）
        download_pdf: 是否下载 PDF（默认 True，失败时回退到 title-only）

    Returns:
        list[EvidenceInput]: 每个章节一个 EvidenceInput
    """
    ann_id = record.get("id") or ""
    title = (record.get("title") or "").strip()
    ts_code = (record.get("ts_code") or "").strip()
    ann_date_raw = record.get("ann_date")
    # Convert date/dateime to ISO string for MongoDB
    if ann_date_raw is None:
        ann_date = None
    elif isinstance(ann_date_raw, date):
        ann_date = ann_date_raw.isoformat()
    elif isinstance(ann_date_raw, datetime):
        ann_date = ann_date_raw.isoformat()
    else:
        ann_date = str(ann_date_raw) if ann_date_raw else None
    ann_type = (record.get("type") or record.get("ann_types") or "")
    source_url = (record.get("source_url") or "")
    company_name = (record.get("name") or "").strip()

    source_id = str(ann_id)
    chapters: list[dict] = []

    # 尝试下载 PDF 并按章节分块
    if download_pdf and source_url:
        pdf_content = download_announcement_pdf(source_url)
        if pdf_content:
            full_text = parse_pdf_text(pdf_content)
            if full_text.strip():
                chapters = split_by_chapters(full_text)

    # 回退：PDF 不可用时只用 title
    if not chapters:
        chapters = [{"heading": "", "body": title}]

    evidence_list: list[EvidenceInput] = []
    for i, ch in enumerate(chapters):
        chunk_text = f"# {ch['heading']}\n\n{ch['body']}" if ch["heading"] else ch["body"]
        evidence_list.append(EvidenceInput(
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
                "source_table": "minishare_announcements",
                "source_id": ann_id,
                "ann_date": ann_date,
                "source_url": source_url,
                "chapter_heading": ch["heading"],
            },
            confidence=default_source_confidence("announcement"),
            metadata={"title": title, "chapter_count": len(chapters)},
        ))

    return evidence_list


def build_irm_evidence(
    record: dict[str, Any],
) -> EvidenceInput:
    """从 announcements (irm:*) 记录构建 EvidenceInput。

    每条互动易 Q&A 作为一个 Evidence，不分块。
    """
    ann_id = record.get("id") or ""
    question = (record.get("title") or "").strip()  # IRM stores question in title
    ts_code = (record.get("ts_code") or "").strip()
    ann_date = record.get("ann_date")
    ann_type = (record.get("announcement_type") or "")
    company_name = (record.get("name") or "").strip()

    return EvidenceInput(
        source_type="irm",
        source_name=f"互动易:{ts_code}" if ts_code else "互动易",
        source_id=str(ann_id),
        text_excerpt=f"问题：{question}",
        subject_hint={
            "ts_code": ts_code,
            "name": company_name,
        },
        publish_date=ann_date,
        observed_at=_utc_now(),
        source_ref={
            "source_table": "announcements",
            "source_id": ann_id,
            "ann_date": ann_date,
            "ann_type": ann_type,
        },
        confidence=default_source_confidence("irm"),
        metadata={},
    )