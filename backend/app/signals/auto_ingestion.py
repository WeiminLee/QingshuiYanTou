from __future__ import annotations

import logging
from typing import Any

from app.core.database import async_session
from app.signals.evidence_ingestion import _upsert_signal_records, extract_evidence_signal_records_with_kg
from app.signals.kg_propagation import KGPathProvider

logger = logging.getLogger(__name__)


async def ingest_evidence_signals(
    evidence: dict[str, Any],
    *,
    kg_provider: KGPathProvider | None = None,
) -> dict[str, int]:
    signals, propagations = await extract_evidence_signal_records_with_kg(evidence, provider=kg_provider)
    if not signals and not propagations:
        return {"signals_upserted": 0, "propagations_upserted": 0}
    async with async_session() as session:
        signals_upserted, propagations_upserted = await _upsert_signal_records(session, signals, propagations)
        await session.commit()
    return {
        "signals_upserted": signals_upserted,
        "propagations_upserted": propagations_upserted,
    }
