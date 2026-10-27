from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import httpx

from app.core.database import async_session
from app.signals.evidence_ingestion import _upsert_signal_records, extract_evidence_signal_records_with_kg
from app.signals.kg_propagation import KGPathProvider

logger = logging.getLogger(__name__)


def _json_default(value: Any) -> str:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"not JSON serializable: {type(value).__name__}")


async def _upsert_signals(
    signals: list[dict[str, Any]], propagations: list[dict[str, Any]]
) -> tuple[int, int]:
    """worker 经 HTTP 写面；API/scheduler 进程直接落库。"""
    api_url = os.environ.get("KNOWLEDGE_API_URL", "").rstrip("/")
    if api_url:
        body = json.dumps({"signals": signals, "propagations": propagations}, default=_json_default)
        async with httpx.AsyncClient(timeout=60.0, trust_env=False) as client:
            resp = await client.post(
                f"{api_url}/api/v1/knowledge/signal/upsert",
                content=body,
                headers={
                    "X-API-Key": os.environ.get("KNOWLEDGE_API_KEY", ""),
                    "Content-Type": "application/json",
                },
            )
            resp.raise_for_status()
            data = resp.json()
        return int(data.get("signals_upserted", 0)), int(data.get("propagations_upserted", 0))

    async with async_session() as session:
        result = await _upsert_signal_records(session, signals, propagations)
        await session.commit()
    return result


async def ingest_evidence_signals(
    evidence: dict[str, Any],
    *,
    kg_provider: KGPathProvider | None = None,
) -> dict[str, int]:
    signals, propagations = await extract_evidence_signal_records_with_kg(evidence, provider=kg_provider)
    if not signals and not propagations:
        return {"signals_upserted": 0, "propagations_upserted": 0}
    signals_upserted, propagations_upserted = await _upsert_signals(signals, propagations)
    return {
        "signals_upserted": signals_upserted,
        "propagations_upserted": propagations_upserted,
    }


async def ingest_event_signals(events: list[Any]) -> dict[str, int]:
    """新闻、资讯、事件先做研究推导，有新的一层才写入 signals。"""
    from app.signals.event_ingestion import event_to_source_payload
    from app.signals.research_derivation import derive_candidates, empty_derivation_stats, records_from_candidates

    totals = empty_derivation_stats()
    if not events:
        return {"events_scanned": 0, "signals_upserted": 0, "propagations_upserted": 0, **totals}

    records: list[dict[str, Any]] = []
    for event in events:
        outcome = await derive_candidates(event_to_source_payload(event))
        for key in totals:
            totals[key] += outcome.stats.get(key, 0)
        records.extend(records_from_candidates(outcome.candidates))

    if not records:
        logger.info("event signal derivation wrote nothing: %s", totals)
        return {"events_scanned": len(events), "signals_upserted": 0, "propagations_upserted": 0, **totals}

    signals_upserted, propagations_upserted = await _upsert_signals(records, [])
    logger.info(
        "event signal derivation scanned=%s upserted=%s %s",
        len(events),
        signals_upserted,
        totals,
    )
    return {
        "events_scanned": len(events),
        "signals_upserted": signals_upserted,
        "propagations_upserted": propagations_upserted,
        **totals,
    }
