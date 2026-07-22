from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import Event
from app.signals.extractor import RuleSignalExtractor, SignalCandidate, SourcePayload, stable_signal_id
from app.signals.kg_propagation import KGPath, KGPathProvider, Neo4jKGPathProvider, build_kg_propagations
from app.signals.models import Signal, SignalPropagation
from app.signals.propagation import PropagationCandidate, build_lightweight_propagations


def event_to_source_payload(event: Any) -> SourcePayload:
    return SourcePayload(
        source_type="news",
        source_id=str(event.event_id),
        title=event.title or "",
        content=event.content or "",
        summary=event.summary or "",
        published_at=event.publish_at,
        url=event.url,
        metadata=dict(getattr(event, "metadata_", None) or {}),
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
        "metadata": candidate.metadata,
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
        "metadata": propagation.metadata,
    }


def extract_event_signal_records(
    event: Any,
    *,
    kg_paths_by_subject: dict[str, list[KGPath]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    payload = event_to_source_payload(event)
    candidates = RuleSignalExtractor().extract(payload)
    signals: list[dict[str, Any]] = []
    propagations: list[dict[str, Any]] = []
    for candidate in candidates:
        signal_values = _signal_values(candidate)
        signals.append(signal_values)
        kg_paths = (kg_paths_by_subject or {}).get(candidate.subject_name, [])
        propagation_candidates = build_kg_propagations(candidate, kg_paths) if kg_paths else []
        if not propagation_candidates:
            propagation_candidates = build_lightweight_propagations(candidate)
        for propagation in propagation_candidates:
            propagations.append(_propagation_values(signal_values["signal_id"], propagation))
    return signals, propagations


async def build_event_kg_paths_by_subject(
    candidates: list[SignalCandidate],
    provider: KGPathProvider | None = None,
) -> dict[str, list[KGPath]]:
    provider = provider or Neo4jKGPathProvider()
    result: dict[str, list[KGPath]] = {}
    for subject in dict.fromkeys(candidate.subject_name for candidate in candidates if candidate.subject_name):
        result[subject] = await provider.fetch_paths(subject, max_hops=2)
    return result


async def extract_event_signal_records_with_kg(
    event: Any,
    provider: KGPathProvider | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    payload = event_to_source_payload(event)
    candidates = RuleSignalExtractor().extract(payload)
    kg_paths_by_subject = await build_event_kg_paths_by_subject(candidates, provider)
    return extract_event_signal_records(event, kg_paths_by_subject=kg_paths_by_subject)


async def backfill_event_signals(session: AsyncSession, *, limit: int = 200) -> dict[str, int]:
    result = await session.execute(select(Event).order_by(desc(Event.publish_at)).limit(limit))
    events = result.scalars().all()

    signals_upserted = 0
    propagations_upserted = 0
    for event in events:
        signals, propagations = await extract_event_signal_records_with_kg(event)
        for values in signals:
            stmt = insert(Signal).values(**values)
            stmt = stmt.on_conflict_do_update(
                index_elements=["signal_id"],
                set_={
                    "detected_at": values["detected_at"],
                    "freshness_score": values["freshness_score"],
                    "value_score": values["value_score"],
                    "summary": values["summary"],
                    "evidence_excerpt": values["evidence_excerpt"],
                    "metadata": values["metadata"],
                },
            )
            await session.execute(stmt)
            signals_upserted += 1
        for values in propagations:
            stmt = insert(SignalPropagation).values(**values)
            stmt = stmt.on_conflict_do_update(
                index_elements=["propagation_id"],
                set_={
                    "confidence": values["confidence"],
                    "reasoning": values["reasoning"],
                    "evidence_refs": values["evidence_refs"],
                    "metadata": values["metadata"],
                },
            )
            await session.execute(stmt)
            propagations_upserted += 1

    await session.commit()
    return {
        "events_scanned": len(events),
        "signals_upserted": signals_upserted,
        "propagations_upserted": propagations_upserted,
    }
