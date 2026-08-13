from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.mongodb import get_mongo_db
from app.knowledge.evidence import EVIDENCE_COLLECTION
from app.signals.event_ingestion import _propagation_values, _signal_values
from app.signals.extractor import RuleSignalExtractor, SignalCandidate, SourcePayload
from app.signals.kg_propagation import KGPath, KGPathProvider, Neo4jKGPathProvider, build_kg_propagations
from app.signals.models import Signal, SignalPropagation
from app.signals.propagation import build_lightweight_propagations


def _coerce_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y%m%d"):
            try:
                return datetime.strptime(value[:19], fmt)
            except ValueError:
                continue
    return None


def evidence_to_source_payload(evidence: dict[str, Any]) -> SourcePayload:
    subject_hint = evidence.get("subject_hint") or {}
    source_ref = evidence.get("source_ref") or {}
    metadata = dict(evidence.get("metadata") or {})
    metadata["evidence_id"] = evidence.get("evidence_id")
    metadata["subject_hint"] = dict(subject_hint)
    metadata["source_ref"] = dict(source_ref)
    metadata["original_source_type"] = evidence.get("source_type")

    title = (
        subject_hint.get("title")
        or source_ref.get("title")
        or evidence.get("source_name")
        or evidence.get("source_id")
        or evidence.get("evidence_id")
        or "Evidence"
    )
    url = source_ref.get("pdf_url") or source_ref.get("url") or source_ref.get("source_url")
    source_type = str(evidence.get("source_type") or "evidence")

    return SourcePayload(
        source_type=source_type,
        source_id=str(evidence.get("evidence_id") or evidence.get("source_id") or ""),
        title=str(title),
        content=str(evidence.get("text_excerpt") or ""),
        summary=str(evidence.get("source_name") or ""),
        published_at=_coerce_datetime(evidence.get("publish_date")),
        url=str(url) if url else None,
        metadata=metadata,
    )


def extract_evidence_signal_records(
    evidence: dict[str, Any],
    *,
    kg_paths_by_subject: dict[str, list[KGPath]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    payload = evidence_to_source_payload(evidence)
    candidates = RuleSignalExtractor().extract(payload)
    return _records_from_candidates(candidates, kg_paths_by_subject=kg_paths_by_subject)


async def build_kg_paths_by_subject(
    candidates: list[SignalCandidate],
    provider: KGPathProvider | None = None,
) -> dict[str, list[KGPath]]:
    provider = provider or Neo4jKGPathProvider()
    result: dict[str, list[KGPath]] = {}
    for subject in dict.fromkeys(candidate.subject_name for candidate in candidates if candidate.subject_name):
        result[subject] = await provider.fetch_paths(subject, max_hops=2)
    return result


async def extract_evidence_signal_records_with_kg(
    evidence: dict[str, Any],
    provider: KGPathProvider | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    payload = evidence_to_source_payload(evidence)
    candidates = RuleSignalExtractor().extract(payload)
    kg_paths_by_subject = await build_kg_paths_by_subject(candidates, provider)
    return _records_from_candidates(candidates, kg_paths_by_subject=kg_paths_by_subject)


def _records_from_candidates(
    candidates: list[SignalCandidate],
    *,
    kg_paths_by_subject: dict[str, list[KGPath]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
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


async def _upsert_signal_records(
    session: AsyncSession,
    signals: list[dict[str, Any]],
    propagations: list[dict[str, Any]],
) -> tuple[int, int]:
    from sqlalchemy.dialects.postgresql import insert

    signals_upserted = 0
    propagations_upserted = 0
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
                "metadata": values["metadata_"],
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
                "metadata": values["metadata_"],
            },
        )
        await session.execute(stmt)
        propagations_upserted += 1
    return signals_upserted, propagations_upserted


async def backfill_evidence_signals(
    session: AsyncSession,
    *,
    source_type: str | None = None,
    limit: int = 200,
) -> dict[str, int]:
    db = get_mongo_db()
    query = {"source_type": source_type} if source_type else {}
    cursor = db[EVIDENCE_COLLECTION].find(query, {"_id": 0}).sort("publish_date", -1).limit(limit)

    evidence_scanned = 0
    signals_upserted = 0
    propagations_upserted = 0
    async for evidence in cursor:
        evidence_scanned += 1
        signals, propagations = await extract_evidence_signal_records_with_kg(evidence)
        sig_count, prop_count = await _upsert_signal_records(session, signals, propagations)
        signals_upserted += sig_count
        propagations_upserted += prop_count

    await session.commit()
    return {
        "evidence_scanned": evidence_scanned,
        "signals_upserted": signals_upserted,
        "propagations_upserted": propagations_upserted,
    }
