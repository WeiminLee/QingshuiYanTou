from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import Event
from app.signals.event_sources import resolve_event_origin, signal_source_type_for_origin
from app.signals.extractor import SignalCandidate, SourcePayload, stable_signal_id
from app.signals.kg_propagation import KGPath, KGPathProvider
from app.signals.propagation import PropagationCandidate


def coerce_event(event: Any) -> Any:
    """Accept an ORM row or a plain dict from the news writer."""
    if not isinstance(event, dict):
        return event
    metadata = event.get("metadata_")
    if metadata is None:
        metadata = event.get("metadata") or {}
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except json.JSONDecodeError:
            metadata = {}
    return SimpleNamespace(
        event_id=str(event.get("event_id") or ""),
        title=event.get("title") or "",
        summary=event.get("summary") or "",
        content=event.get("content") or "",
        publish_at=event.get("publish_at"),
        url=event.get("url"),
        source=event.get("source") or "news",
        metadata_=metadata if isinstance(metadata, dict) else {},
    )


def event_to_source_payload(event: Any) -> SourcePayload:
    event = coerce_event(event)
    raw_source = str(getattr(event, "source", None) or "news")
    origin = resolve_event_origin(raw_source)
    metadata = dict(getattr(event, "metadata_", None) or {})
    metadata["event_origin"] = origin
    metadata["raw_source"] = raw_source
    return SourcePayload(
        source_type=signal_source_type_for_origin(origin),
        source_id=str(event.event_id),
        title=event.title or "",
        content=event.content or "",
        summary=event.summary or "",
        published_at=event.publish_at,
        url=event.url,
        metadata=metadata,
    )


def _freshness_score(published_at: datetime | None) -> int:
    if published_at is None:
        return 50
    return 100


def _signal_values(candidate: SignalCandidate) -> dict[str, Any]:
    return {
        "signal_id": stable_signal_id(candidate),
        "source_type": candidate.source_type,
        "source_id": candidate.source_id,
        "source_title": candidate.source_title,
        "source_url": candidate.source_url,
        "published_at": candidate.published_at,
        "detected_at": datetime.now(tz=candidate.published_at.tzinfo or UTC)
        if candidate.published_at
        else datetime.now(UTC),
        "subject_name": candidate.subject_name,
        "subject_type": candidate.subject_type,
        "signal_type": candidate.signal_type,
        "polarity": candidate.polarity,
        "strength": candidate.strength,
        "confidence": Decimal(str(round(candidate.confidence, 3))),
        "freshness_score": _freshness_score(candidate.published_at),
        "value_score": candidate.value_score,
        "summary": candidate.summary,
        "evidence_excerpt": candidate.evidence_excerpt,
        "status": "new",
        "metadata_": candidate.metadata,
    }


def _propagation_id(signal_id: str, propagation: PropagationCandidate) -> str:
    raw = "|".join([signal_id, propagation.target_name, propagation.target_type, propagation.relation_path])
    return f"SP:{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:24]}"


def _propagation_values(signal_id: str, propagation: PropagationCandidate) -> dict[str, Any]:
    return {
        "propagation_id": _propagation_id(signal_id, propagation),
        "signal_id": signal_id,
        "target_name": propagation.target_name,
        "target_type": propagation.target_type,
        "relation_path": propagation.relation_path,
        "direction": propagation.direction,
        "impact_horizon": propagation.impact_horizon,
        "confidence": Decimal(str(round(propagation.confidence, 3))),
        "reasoning": propagation.reasoning,
        "evidence_refs": propagation.evidence_refs,
        "metadata_": propagation.metadata,
    }


def extract_event_signal_records(
    event: Any,
    *,
    kg_paths_by_subject: dict[str, list[KGPath]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """同步入口已关闭。事件 signal 只经研究推导。"""
    del event, kg_paths_by_subject
    raise RuntimeError("新闻、资讯和事件的 signal 必须经 extract_event_signal_records_with_kg 做研究推导，不能用规则抽取。")



async def extract_event_signal_records_with_kg(
    event: Any,
    provider: KGPathProvider | None = None,
    *,
    llm: Any = None,
    prior_lines: list[str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """研究推导之后才有 signal。没有新的一层时返回空，不附带规则传导。"""
    del provider
    from app.signals.research_derivation import derive_candidates, records_from_candidates

    outcome = await derive_candidates(event_to_source_payload(event), llm=llm, prior_lines=prior_lines)
    return records_from_candidates(outcome.candidates), []


async def backfill_event_signals(session: AsyncSession, *, limit: int = 200) -> dict[str, int]:
    from app.signals.evidence_ingestion import _upsert_signal_records
    from app.signals.research_derivation import derive_candidates, records_from_candidates

    result = await session.execute(select(Event).order_by(desc(Event.publish_at)).limit(limit))
    events = result.scalars().all()
    payloads = [event_to_source_payload(event) for event in events]
    await session.rollback()

    records: list[dict[str, Any]] = []
    for payload in payloads:
        outcome = await derive_candidates(payload)
        records.extend(records_from_candidates(outcome.candidates))
    signals_upserted, propagations_upserted = await _upsert_signal_records(session, records, [])
    await session.commit()
    return {
        "events_scanned": len(events),
        "signals_upserted": signals_upserted,
        "propagations_upserted": propagations_upserted,
    }
