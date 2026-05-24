"""Mechanical Evidence builders for source ingestion paths."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from app.knowledge.evidence import EvidenceInput, default_source_confidence
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
) -> list[EvidenceInput]:
    chunks = chunk_by_token(text or "", max_tokens=chunk_max_tokens, overlap_tokens=0)
    if max_chunks is not None and max_chunks > 0:
        chunks = chunks[:max_chunks]
    evidence: list[EvidenceInput] = []
    for index, chunk in enumerate(chunks):
        ref = dict(source_ref or {})
        chunk_id = getattr(chunk, "chunk_id", index)
        heading = getattr(chunk, "heading", "") or ""
        ref.update({"chunk_id": chunk_id, "heading": heading})
        evidence.append(EvidenceInput(
            source_type=source_type,
            source_name=source_name,
            source_id=source_id,
            text_excerpt=getattr(chunk, "content", str(chunk)),
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
) -> list[EvidenceInput]:
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
