"""Mechanical Evidence builders for source ingestion paths."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from app.knowledge.evidence import EvidenceInput, default_source_confidence
from app.knowledge.evidence_filters import (
    FilterConfig,
    clean_chunk_text,
    filter_chunks,
    preprocess_text,
    should_include_chunk,
)
from app.knowledge.extraction.chunker import chunk_by_token


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_str(value: Any) -> str:
    return str(value or "").strip()


def _irm_content_hash(record: dict[str, Any]) -> str:
    payload = "\n".join([
        _as_str(record.get("ts_code")),
        _as_str(record.get("company_name") or record.get("name")),
        _as_str(record.get("question") or record.get("title")),
        _as_str(record.get("answer") or record.get("type")),
        _as_str(record.get("ann_date")),
    ])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def irm_record_key(record: dict[str, Any]) -> str:
    cninfo_id = _as_str(record.get("cninfo_id"))
    if cninfo_id:
        return cninfo_id
    ts_code = _as_str(record.get("ts_code"))
    content_hash = _irm_content_hash(record)
    return f"{ts_code}:{content_hash[:20]}" if ts_code else content_hash[:24]


def build_text_evidence(
    *,
    text: str,
    source_type: str,
    source_name: str,
    source_id: str,
    subject_hint: dict[str, Any] | None = None,
    source_ref: dict[str, Any] | None = None,
    publish_date: Any = None,
    observed_at: Any = None,
    chunk_max_tokens: int = 2048,
    max_chunks: int | None = None,
    metadata: dict[str, Any] | None = None,
    filter_config: FilterConfig | None = None,
) -> list[EvidenceInput]:
    """
    构建 Evidence 列表（带内容过滤）。

    Args:
        chunk_max_tokens: 最大 token 数（默认 2048）
        filter_config: 过滤器配置
    """
    # 分块
    chunks = chunk_by_token(text or "", max_tokens=chunk_max_tokens, overlap_tokens=0)

    # 应用过滤器
    if filter_config is None:
        filter_config = FilterConfig(min_chars=50)

    chunks = filter_chunks(chunks, filter_config)

    if max_chunks is not None and max_chunks > 0:
        chunks = chunks[:max_chunks]

    evidence: list[EvidenceInput] = []
    for index, chunk in enumerate(chunks):
        # 获取 chunk 文本
        chunk_text = getattr(chunk, "content", str(chunk))

        # 清理文本
        chunk_text = clean_chunk_text(chunk_text)

        # 再次检查（清理后可能变短）
        if not should_include_chunk(chunk_text, filter_config):
            continue

        ref = dict(source_ref or {})
        chunk_id = getattr(chunk, "chunk_id", index)
        heading = getattr(chunk, "heading", "") or ""
        ref.update({"chunk_id": chunk_id, "heading": heading})
        evidence.append(EvidenceInput(
            source_type=source_type,
            source_name=source_name,
            source_id=source_id,
            text_excerpt=chunk_text,
            subject_hint=dict(subject_hint or {}),
            publish_date=publish_date,
            observed_at=observed_at or _utc_now(),
            source_ref=ref,
            confidence=default_source_confidence(source_type),
            metadata=dict(metadata or {}),
        ))
    return evidence


def build_file_evidence(
    file_info: dict[str, Any],
    text: str,
    source_type: str,
    doc_type: str,
    ts_code: str | None,
    chunk_max_tokens: int = 2048,
    max_chunks: int | None = None,
    filter_config: FilterConfig | None = None,
) -> list[EvidenceInput]:
    """
    从文件构建 Evidence 列表。

    Args:
        file_info: 文件元信息
        text: 原始文本
        source_type: 来源类型
        doc_type: 文档类型
        ts_code: 股票代码
        chunk_max_tokens: 最大 token 数（默认 2048）
        max_chunks: 最大 chunk 数
        filter_config: 过滤器配置（默认启用全部过滤）
    """
    # 默认过滤器配置
    if filter_config is None:
        filter_config = FilterConfig(
            min_chars=50,
            min_tokens=None,
            max_tokens=chunk_max_tokens,
            enable_table_filter=True,
            enable_legal_filter=True,
            enable_header_filter=True,
            enable_noise_filter=True,
        )

    # 预处理：去除页眉页脚、表格噪声
    text = preprocess_text(text, filter_config)

    source_id = _as_str(file_info.get("cninfo_id")) or _as_str(file_info.get("file_path"))
    file_name = _as_str(file_info.get("file_name"))
    title = _as_str(file_info.get("title"))
    subject_hint = {
        "ts_code": ts_code or file_info.get("ts_code"),
        "file_name": file_name,
    }
    if title:
        subject_hint["title"] = title
    source_ref = {
        "file_path": file_info.get("file_path"),
        "file_hash": file_info.get("file_hash"),
        "file_type": file_info.get("file_type"),
        "doc_type": doc_type,
        "source_type": source_type,
    }
    return build_text_evidence(
        text=text,
        source_type=source_type,
        source_name=title or file_name or source_id,
        source_id=source_id,
        subject_hint=subject_hint,
        source_ref=source_ref,
        publish_date=file_info.get("publish_date") or file_info.get("ann_date"),
        observed_at=_utc_now(),
        chunk_max_tokens=chunk_max_tokens,
        max_chunks=max_chunks,
        metadata={"doc_type": doc_type},
        filter_config=filter_config,
    )


def build_irm_evidence(record: dict[str, Any]) -> EvidenceInput:
    cninfo_id = _as_str(record.get("cninfo_id"))
    question = _as_str(record.get("question") or record.get("title"))
    answer = _as_str(record.get("answer") or record.get("type"))
    ts_code = _as_str(record.get("ts_code"))
    company_name = _as_str(record.get("company_name") or record.get("name"))
    record_key = irm_record_key(record)
    text = f"问题：{question}\n回答：{answer}"
    return EvidenceInput(
        source_type="irm",
        source_name=f"互动易:{cninfo_id}" if cninfo_id else "互动易",
        source_id=cninfo_id or record_key,
        text_excerpt=text,
        subject_hint={"ts_code": ts_code, "company_name": company_name},
        publish_date=record.get("ann_date"),
        observed_at=_utc_now(),
        source_ref={
            "cninfo_id": cninfo_id,
            "ts_code": ts_code,
            "ann_date": record.get("ann_date"),
            "record_key": record_key,
        },
        confidence=default_source_confidence("irm"),
        metadata={},
    )
