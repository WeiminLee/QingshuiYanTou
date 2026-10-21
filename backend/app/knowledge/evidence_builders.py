"""Mechanical Evidence builders for source ingestion paths."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any

from app.knowledge.evidence import EvidenceInput, default_source_confidence


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _to_iso_date(value: Any) -> str | None:
    """Convert date/datetime to ISO string for MongoDB storage."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _as_str(value: Any) -> str:
    return str(value or "").strip()


def _irm_content_hash(record: dict[str, Any]) -> str:
    payload = "\n".join(
        [
            _as_str(record.get("ts_code")),
            _as_str(record.get("company_name") or record.get("name")),
            _as_str(record.get("question") or record.get("title")),
            _as_str(record.get("answer") or record.get("type")),
            _as_str(record.get("ann_date")),
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def irm_record_key(record: dict[str, Any]) -> str:
    cninfo_id = _as_str(record.get("cninfo_id"))
    if cninfo_id:
        return cninfo_id
    ts_code = _as_str(record.get("ts_code"))
    content_hash = _irm_content_hash(record)
    return f"{ts_code}:{content_hash[:20]}" if ts_code else content_hash[:24]


def build_irm_evidence_batch(records: list[dict]) -> list[EvidenceInput]:
    """按 (ts_code, ann_date) 聚合 IRM 记录，返回合并后的 EvidenceInput 列表。

    同一天同一公司的 IRM Q&A 合并为一条 evidence，减少 LLM 调用次数
    并提升每条 evidence 的上下文丰富度。
    """
    from collections import defaultdict

    # 按 (ts_code, ann_date) 分组
    groups: dict[str, list[dict]] = defaultdict(list)
    for rec in records:
        ts_code = _as_str(rec.get("ts_code"))
        ann_date = _to_iso_date(rec.get("ann_date")) or ""
        key = f"{ts_code}|{ann_date}"
        groups[key].append(rec)

    results: list[EvidenceInput] = []
    for key, group in groups.items():
        ts_code, ann_date = key.split("|", 1)
        # 取第一个记录的基础信息
        first = group[0]
        company_name = _as_str(first.get("company_name") or first.get("name"))
        first_cninfo = _as_str(first.get("cninfo_id"))

        # 合并所有 Q&A 文本
        merged_texts: list[str] = []
        cninfo_ids: list[str] = []
        for rec in group:
            question = _as_str(rec.get("question") or rec.get("title"))
            answer = _as_str(rec.get("answer") or rec.get("type"))
            merged_texts.append(f"问题：{question}\n回答：{answer}")
            cid = _as_str(rec.get("cninfo_id"))
            if cid:
                cninfo_ids.append(cid)

        # 合并后的 source_id 用首条 cninfo 或组哈希
        if cninfo_ids:
            source_id = cninfo_ids[0]
        else:
            combined = hashlib.sha256(
                "|".join(merged_texts).encode("utf-8")
            ).hexdigest()[:20]
            source_id = f"{ts_code}:{combined}"

        source_name = f"互动易:{first_cninfo}" if first_cninfo else f"互动易:{ts_code}"
        text = "\n\n".join(merged_texts)
        # 记录原始条数到 metadata 用于审计
        metadata = {"merged_count": len(group)}

        results.append(
            EvidenceInput(
                source_type="irm",
                source_name=source_name,
                source_id=source_id,
                text_excerpt=text,
                subject_hint={"ts_code": ts_code, "company_name": company_name},
                publish_date=ann_date or None,
                observed_at=_utc_now(),
                source_ref={
                    "cninfo_id": cninfo_ids[0] if cninfo_ids else "",
                    "ts_code": ts_code,
                    "ann_date": ann_date,
                    "merged_ids": cninfo_ids,
                },
                confidence=default_source_confidence("irm"),
                metadata=metadata,
            )
        )

    return results
