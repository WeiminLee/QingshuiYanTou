from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.signals.models import Signal, SignalPropagation

_ALLOWED_STATUSES = {"new", "viewed", "reviewed", "dismissed", "archived"}


def _to_float(value: Decimal | float | int | None) -> float:
    if value is None:
        return 0.0
    return float(value)


def _portfolio_hits(metadata: dict[str, Any] | None) -> list[str]:
    hits = (metadata or {}).get("portfolio_hits", [])
    return [str(item) for item in hits] if isinstance(hits, list) else []


def _title(row: Signal) -> str:
    return row.source_title or row.summary


async def list_signals(
    session: AsyncSession,
    *,
    scope: str = "all",
    source_type: str | None = None,
    signal_type: str | None = None,
    status: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[dict], int]:
    stmt = select(Signal)
    if source_type:
        stmt = stmt.where(Signal.source_type == source_type)
    if signal_type:
        stmt = stmt.where(Signal.signal_type == signal_type)
    if status:
        stmt = stmt.where(Signal.status == status)
    if scope == "risk":
        stmt = stmt.where(Signal.polarity == "risk")
    if scope == "portfolio":
        stmt = stmt.where(Signal.metadata_["portfolio_hits"].astext != None)  # noqa: E711

    count_result = await session.execute(stmt)
    all_rows = count_result.scalars().all()
    rows = sorted(
        all_rows,
        key=lambda r: (r.value_score, r.published_at or r.detected_at),
        reverse=True,
    )[offset : offset + limit]
    items = [
        {
            "signal_id": row.signal_id,
            "title": _title(row),
            "summary": row.summary,
            "source_type": row.source_type,
            "published_at": row.published_at,
            "subject_name": row.subject_name,
            "signal_type": row.signal_type,
            "polarity": row.polarity,
            "value_score": row.value_score,
            "confidence": _to_float(row.confidence),
            "portfolio_hits": _portfolio_hits(row.metadata_),
        }
        for row in rows
    ]
    return items, len(all_rows)


async def get_signal_detail(session: AsyncSession, signal_id: str) -> dict | None:
    signal_result = await session.execute(select(Signal).where(Signal.signal_id == signal_id))
    signal = signal_result.scalar_one_or_none()
    if signal is None:
        return None

    prop_result = await session.execute(
        select(SignalPropagation)
        .where(SignalPropagation.signal_id == signal_id)
        .order_by(desc(SignalPropagation.confidence))
    )
    propagations = prop_result.scalars().all()
    return {
        "signal_id": signal.signal_id,
        "title": _title(signal),
        "summary": signal.summary,
        "source_type": signal.source_type,
        "source_title": signal.source_title,
        "source_url": signal.source_url,
        "published_at": signal.published_at,
        "subject_name": signal.subject_name,
        "subject_type": signal.subject_type,
        "signal_type": signal.signal_type,
        "polarity": signal.polarity,
        "strength": signal.strength,
        "confidence": _to_float(signal.confidence),
        "value_score": signal.value_score,
        "evidence_excerpt": signal.evidence_excerpt,
        "status": signal.status,
        "portfolio_hits": _portfolio_hits(signal.metadata_),
        "propagations": [
            {
                "target_name": p.target_name,
                "target_type": p.target_type,
                "relation_path": p.relation_path,
                "direction": p.direction,
                "impact_horizon": p.impact_horizon,
                "confidence": _to_float(p.confidence),
                "reasoning": p.reasoning,
            }
            for p in propagations
        ],
    }


async def update_signal_status(session: AsyncSession, signal_id: str, status: str) -> dict | None:
    if status not in _ALLOWED_STATUSES:
        raise ValueError(f"invalid signal status: {status}")
    await session.execute(update(Signal).where(Signal.signal_id == signal_id).values(status=status))
    await session.commit()
    return await get_signal_detail(session, signal_id)

