# backend/app/knowledge/linklayer/ingest.py
"""链接层入库管线：dict match + LLM 浅提取 → 归一化 → keyword/link 幂等 upsert。"""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.knowledge.evidence_service import EvidenceService
from app.knowledge.linklayer.dict_match import build_subject_index, match_all
from app.knowledge.linklayer.dictionaries import load_vocabulary
from app.knowledge.linklayer.llm_extract import extract_keywords
from app.knowledge.linklayer.models import Link
from app.knowledge.linklayer.normalize import canonicalize_subject, ensure_keyword

logger = logging.getLogger(__name__)


async def ingest_evidence(evidence_id: str, *, _session=None) -> dict:
    """对单条 evidence 建链。幂等：link PK 冲突 do nothing。"""
    svc = EvidenceService()
    evidence = await svc.get_evidence(evidence_id)
    if not evidence:
        return {"links": 0, "keywords": 0, "llm_used": False}

    text = evidence.get("text_excerpt") or ""
    vocab = load_vocabulary()
    subject_index = await build_subject_index()

    # 通道 1：词典匹配（封闭类：subject 兜底 / dimension / stage）
    actions: list[tuple[str, str, str, int, int, datetime | None]] = []  # layer, norm, source, s, e, published
    published = _parse_date(evidence.get("publish_date"))
    for m in match_all(text, vocab, subject_index):
        actions.append((m.layer, m.norm_text, "dictionary", m.span_start, m.span_end, published))

    # 通道 2：LLM 浅提取（开放类：Company/Product/Metric）
    llm_result = await extract_keywords(evidence)
    llm_used = llm_result is not None
    if llm_result:
        for surface in llm_result.get("company", []):
            norm = canonicalize_subject(surface, subject_index) or surface
            actions.append(("subject", norm, "llm", 0, 0, published))
        for surface in llm_result.get("product", []):
            actions.append(("scope", surface, "llm", 0, 0, published))
        for m in llm_result.get("metric", []):
            actions.append(("dimension", m["name"], "llm", 0, 0, published))

    # # # 落库 # # #
    assert _session is not None, "需要 PG session（由 worker / script 传入）"
    link_count = 0
    for layer, norm, source, s, e, pub in actions:
        kw_id = await ensure_keyword(_session, layer, norm, source=source)
        stmt = (
            pg_insert(Link)
            .values(
                keyword_id=kw_id,
                evidence_id=evidence_id,
                span_start=s,
                span_end=e,
                published_at=pub,
                source=source,
            )
            .on_conflict_do_nothing()
        )
        await _session.execute(stmt)
        link_count += 1
    await _session.commit()
    return {"links": link_count, "keywords": len(actions), "llm_used": llm_used}


def _parse_date(value) -> datetime | None:
    """publish_date 解析；无时区的 naive datetime 视为本地时间（补挂本地时区）。

    timestamptz 列遇到 naive datetime 会按 UTC 解释，直接落库会产生
    本地时区偏移（如 UTC+8 差 8 小时），故在边界处统一补挂时区。
    """
    if isinstance(value, datetime):
        return value if value.tzinfo else value.astimezone()
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.astimezone()
