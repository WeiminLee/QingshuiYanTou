# backend/app/knowledge/linklayer/ingest.py
"""链接层入库管线：dict match + LLM 浅提取 → 归一化 → keyword/link 幂等 upsert。"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.knowledge.evidence_service import EvidenceService
from app.knowledge.linklayer.dict_match import build_subject_index, match_all
from app.knowledge.linklayer.dictionaries import load_vocabulary
from app.knowledge.linklayer.llm_extract import extract_keywords
from app.knowledge.linklayer.models import Link
from app.knowledge.linklayer.normalize import canonicalize_subject, ensure_keyword

logger = logging.getLogger(__name__)


@dataclass
class LinkAction:
    layer: str
    norm_text: str
    source: str
    span_start: int
    span_end: int
    published_at: datetime | None = None
    dimension: str | None = None
    level: int | None = None

    def to_payload(self) -> dict:
        return {
            "layer": self.layer,
            "norm_text": self.norm_text,
            "source": self.source,
            "span_start": self.span_start,
            "span_end": self.span_end,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "dimension": self.dimension,
            "level": self.level,
        }


async def compute_link_actions(
    evidence: dict,
    *,
    skip_llm: bool = False,
    subject_index=None,
    use_db: bool = True,
) -> tuple[list[LinkAction], bool]:
    """计算一条 evidence 的 link 行集合（不做任何落库）。返回 (actions, llm_used)。"""
    text = evidence.get("text_excerpt") or ""
    vocab = load_vocabulary()
    if subject_index is None:
        subject_index = (
            await build_subject_index() if use_db else await build_subject_index(use_db=False)
        )

    actions: list[LinkAction] = []
    published = _parse_date(evidence.get("publish_date"))
    for m in match_all(text, vocab, subject_index):
        actions.append(LinkAction(m.layer, m.norm_text, "dictionary", m.span_start, m.span_end, published))
        if m.layer == "stage" and m.dimension:
            actions.append(LinkAction("dimension", m.dimension, "dictionary", m.span_start, m.span_end, published))

    hint_subject = _subject_from_hint(evidence.get("subject_hint"))
    if hint_subject:
        actions.append(LinkAction("subject", hint_subject, "hint", 0, 0, published))

    llm_result = None if skip_llm else await extract_keywords(evidence)
    llm_used = llm_result is not None
    if llm_result:
        for surface in llm_result.get("company", []):
            norm = canonicalize_subject(surface, subject_index) or surface
            actions.append(LinkAction("subject", norm, "llm", 0, 0, published))
        for surface in llm_result.get("product", []):
            actions.append(LinkAction("scope", surface, "llm", 0, 0, published))
        for m in llm_result.get("metric", []):
            actions.append(LinkAction("dimension", m["name"], "llm", 0, 0, published))

    return actions, llm_used


async def persist_link_actions(session, evidence_id: str, actions: list[LinkAction]) -> int:
    """落库 link 行（幂等）。返回处理行数。"""
    link_count = 0
    for action in actions:
        kw_id = await ensure_keyword(session, action.layer, action.norm_text, source=action.source)
        base = pg_insert(Link).values(
            keyword_id=kw_id,
            evidence_id=evidence_id,
            span_start=action.span_start,
            span_end=action.span_end,
            published_at=action.published_at,
            source=action.source,
        )
        if action.source == "hint":
            stmt = base.on_conflict_do_update(
                index_elements=["keyword_id", "evidence_id", "span_start"],
                set_={"source": "hint"},
            )
        else:
            stmt = base.on_conflict_do_nothing()
        await session.execute(stmt)
        link_count += 1
    await session.commit()
    return link_count


async def ingest_evidence(evidence_id: str, *, _session=None, skip_llm: bool = False) -> dict:
    """对单条 evidence 建链。幂等：link PK 冲突 do nothing。行为与拆分前一致。"""
    svc = EvidenceService()
    evidence = await svc.get_evidence(evidence_id)
    if not evidence:
        return {"links": 0, "keywords": 0, "llm_used": False}

    actions, llm_used = await compute_link_actions(evidence, skip_llm=skip_llm)
    assert _session is not None, "需要 PG session（由 worker / script 传入）"
    link_count = await persist_link_actions(_session, evidence_id, actions)
    return {"links": link_count, "keywords": len(actions), "llm_used": llm_used}


def _subject_from_hint(subject_hint) -> str | None:
    """从 evidence.subject_hint 提取主体规范键（spec §4.2 subject 层兜底）。

    观测到的形态：IRM 为 {"ts_code", "company_name"}，公告为
    {"ts_code", "name", "ann_type"}；上市主体规范键 = ts_code
    （与词典/查询侧 build_subject_index 的归一口径一致）。
    """
    if isinstance(subject_hint, dict):
        return (
            subject_hint.get("ts_code")
            or subject_hint.get("company_name")
            or subject_hint.get("name")
        )
    if isinstance(subject_hint, str):
        return subject_hint or None
    return None


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
