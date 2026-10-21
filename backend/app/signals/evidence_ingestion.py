from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import case, type_coerce
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.mongodb import get_mongo_db
from app.knowledge.evidence import EVIDENCE_COLLECTION
from app.signals.event_ingestion import _propagation_values, _signal_values
from app.signals.extractor import RuleSignalExtractor, SignalCandidate, SourcePayload
from app.signals.kg_propagation import KGPath, KGPathProvider, build_kg_propagations
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
    if provider is None:
        # Neo4j 已除役（2026-10-13）：无路径提供者 → 走 lightweight 传导
        return {}
    result: dict[str, list[KGPath]] = {}
    for subject in dict.fromkeys(candidate.subject_name for candidate in candidates if candidate.subject_name):
        result[subject] = await provider.fetch_paths(subject, max_hops=2)
    return result


async def extract_evidence_signal_records_with_kg(
    evidence: dict[str, Any],
    provider: KGPathProvider | None = None,
    *,
    llm: Any = None,
    prior_lines: list[str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    from app.signals.research_derivation import derive_candidates, evidence_needs_research, records_from_candidates

    source_type = str(evidence.get("source_type") or "")
    if evidence_needs_research(source_type):
        # 公告 / IRM / 新闻：先推导。没有新层就不写，也不退回规则传导。
        # 模型或水位查询失败要抛出，让 signal 任务重试；不能记成一次完成的空结果。
        payload = evidence_to_source_payload(evidence)
        outcome = await derive_candidates(payload, llm=llm, prior_lines=prior_lines)
        if outcome.stats.get("derivation_failed"):
            reason = ",".join(outcome.rejected) or "llm"
            raise RuntimeError(f"signal derivation failed for {payload.source_id}: {reason}")
        return records_from_candidates(outcome.candidates), []

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


def signal_conflict_updates(values: dict[str, Any]) -> dict[str, Any]:
    """已有的二阶导句子保持原句。后一次推导只刷新时间与分数，不把句子改弱。

    metadata 的 else 必须带 JSONB 类型。裸 dict 进 CASE 后，asyncpg 按 jsonb
    参数调用 .encode()，整批插入失败，过门的句子被丢掉。
    """
    locked = Signal.metadata_["derivation"].astext == "second_order"
    return {
        "detected_at": values["detected_at"],
        "freshness_score": values["freshness_score"],
        "value_score": values["value_score"],
        "summary": case((locked, Signal.summary), else_=values["summary"]),
        "evidence_excerpt": case((locked, Signal.evidence_excerpt), else_=values["evidence_excerpt"]),
        "metadata": case((locked, Signal.metadata_), else_=type_coerce(values["metadata_"], JSONB)),
    }


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
            set_=signal_conflict_updates(values),
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
