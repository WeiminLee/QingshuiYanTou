from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import desc, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.signals.models import Signal, SignalPropagation
from app.signals.path import build_signal_path

_ALLOWED_STATUSES = {"new", "viewed", "reviewed", "dismissed", "archived"}


def _to_float(value: Decimal | float | int | None) -> float:
    if value is None:
        return 0.0
    return float(value)


def _metadata_dict(metadata: Any) -> dict[str, Any]:
    return metadata if isinstance(metadata, dict) else {}


def _metadata_text(metadata: Any, keys: tuple[str, ...], default: str) -> str:
    values = _metadata_dict(metadata)
    for key in keys:
        value = values.get(key)
        if isinstance(value, str) and value:
            return value
    return default


def _metadata_int(metadata: Any, key: str, default: int) -> int:
    value = _metadata_dict(metadata).get(key, default)
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _portfolio_hits(metadata: Any) -> list[str]:
    values = _metadata_dict(metadata)
    user_hits = values.get("user_hits")
    if isinstance(user_hits, dict) and isinstance(user_hits.get("portfolio"), list):
        hits = user_hits.get("portfolio", [])
    else:
        hits = values.get("portfolio_hits", [])
    return [str(item) for item in hits] if isinstance(hits, list) else []


def _title(row: Signal) -> str:
    return row.source_title or row.summary


def _catalyst_metadata(metadata: Any) -> dict[str, Any]:
    catalyst = _metadata_dict(metadata).get("catalyst", {})
    return catalyst if isinstance(catalyst, dict) else {}


async def list_signals(
    session: AsyncSession,
    *,
    scope: str = "all",
    source_type: str | None = None,
    signal_type: str | None = None,
    status: str | None = None,
    signal_kind: str | None = None,
    include_kinds: list[str] | None = None,
    window_days: int | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[dict], int]:
    filters = []
    if source_type:
        filters.append(Signal.source_type == source_type)
    if signal_type:
        filters.append(Signal.signal_type == signal_type)
    if status:
        filters.append(Signal.status == status)
    if signal_kind:
        filters.append(Signal.signal_kind == signal_kind)
    elif include_kinds:
        filters.append(Signal.signal_kind.in_(include_kinds))
    if window_days is not None:
        today = date.today()
        filters.append(Signal.event_date >= today)
        filters.append(Signal.event_date <= today + timedelta(days=window_days))
    if scope == "risk":
        filters.append(Signal.polarity == "risk")
    if scope == "portfolio":
        filters.append(Signal.metadata_["portfolio_hits"].astext != None)  # noqa: E711

    count_stmt = select(func.count()).select_from(Signal)
    stmt = select(Signal)
    if filters:
        count_stmt = count_stmt.where(*filters)
        stmt = stmt.where(*filters)

    total_result = await session.execute(count_stmt)
    total = int(total_result.scalar_one() or 0)
    row_result = await session.execute(
        stmt.order_by(
            desc(Signal.value_score),
            desc(func.coalesce(Signal.published_at, Signal.detected_at)),
        )
        .offset(offset)
        .limit(limit)
    )
    rows = row_result.scalars().all()
    items = []
    for row in rows:
        catalyst = _catalyst_metadata(row.metadata_)
        items.append(
            {
            "signal_id": row.signal_id,
            "title": _title(row),
            "summary": row.summary,
            "source_type": row.source_type,
            "published_at": row.published_at,
            "signal_kind": row.signal_kind,
            "event_date": row.event_date,
            "subject_name": row.subject_name,
            "signal_type": row.signal_type,
            "polarity": row.polarity,
            "value_score": row.value_score,
            "confidence": _to_float(row.confidence),
            "portfolio_hits": _portfolio_hits(row.metadata_),
            "lead_days": catalyst.get("lead_days"),
            "alert_level": catalyst.get("alert_level"),
            "impact_scope": catalyst.get("impact_scope", []),
            }
        )
    return items, total


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
        "schema_version": "signal.context.v1",
        "signal_id": signal.signal_id,
        "title": _title(signal),
        "summary": signal.summary,
        "source_type": signal.source_type,
        "source_title": signal.source_title,
        "source_url": signal.source_url,
        "published_at": signal.published_at,
        "signal_kind": getattr(signal, "signal_kind", "observed"),
        "event_date": getattr(signal, "event_date", None),
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
        "source": {
            "type": signal.source_type,
            "id": signal.source_id,
            "title": signal.source_title,
            "url": signal.source_url,
            "published_at": signal.published_at,
        },
        "primary_signal": {
            "subject_name": signal.subject_name,
            "subject_type": signal.subject_type,
            "signal_type": signal.signal_type,
            "polarity": signal.polarity,
            "strength": signal.strength,
            "confidence": _to_float(signal.confidence),
            "evidence_excerpt": signal.evidence_excerpt,
        },
        "catalyst": _catalyst_metadata(signal.metadata_),
        "memory": {
            "schema_version": "signal.memory.v1",
            "signal_id": signal.signal_id,
            "lifecycle_status": _metadata_text(signal.metadata_, ("lifecycle_status", "lifecycle"), "active"),
            "user_status": signal.status,
            "first_seen_at": signal.created_at,
            "last_seen_at": signal.updated_at or signal.detected_at,
            "reinforced_count": _metadata_int(signal.metadata_, "reinforced_count", 0),
            "contradicted_count": _metadata_int(signal.metadata_, "contradicted_count", 0),
            "source_count": _metadata_int(signal.metadata_, "source_count", 1),
        },
        "user_hits": {
            "portfolio": [],
            "watchlist": [],
            "preferences": [],
        },
        "propagations": [
            {
                "target_name": p.target_name,
                "target_type": p.target_type,
                "relation_path": p.relation_path,
                "direction": p.direction,
                "impact_horizon": p.impact_horizon,
                "confidence": _to_float(p.confidence),
                "reasoning": p.reasoning,
                "evidence_refs": p.evidence_refs,
                "metadata": p.metadata_,
                "signal_path": build_signal_path(p.metadata_, confidence=_to_float(p.confidence)),
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
