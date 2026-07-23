from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date, time
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.signals.models import CatalystEvent, Signal, SignalPropagation


@dataclass(frozen=True)
class CatalystEventCandidate:
    event_type: str
    title: str
    event_date: date
    source_type: str
    importance: int
    subjects: list[str]
    event_time: time | None = None
    timezone: str = "Asia/Shanghai"
    source_id: str | None = None
    source_url: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class FixtureCatalystProvider:
    def list_candidates(self, *, today: date | None = None) -> list[CatalystEventCandidate]:
        base = today or date.today()
        return [
            CatalystEventCandidate(
                event_type="conference",
                title="英伟达 GTC 开发者大会",
                event_date=base.fromordinal(base.toordinal() + 5),
                source_type="fixture",
                source_id=f"fixture-nvidia-gtc-{base.isoformat()}",
                importance=90,
                subjects=["AI算力", "GPU", "光模块", "CPO"],
                metadata={"organizer": "NVIDIA", "region": "US"},
            ),
            CatalystEventCandidate(
                event_type="policy_window",
                title="算力基础设施政策窗口",
                event_date=base.fromordinal(base.toordinal() + 3),
                source_type="fixture",
                source_id=f"fixture-compute-policy-{base.isoformat()}",
                importance=78,
                subjects=["AI算力", "数据中心", "国产算力"],
                metadata={"region": "CN"},
            ),
        ]


def _hash_id(prefix: str, raw: str, length: int = 20) -> str:
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:length]
    return f"{prefix}:{digest}"


def stable_catalyst_event_id(candidate: CatalystEventCandidate) -> str:
    source_key = candidate.source_id or candidate.title
    return _hash_id("CAT", f"{candidate.source_type}|{source_key}|{candidate.event_date.isoformat()}")


def stable_catalyst_signal_id(event_id: str, path_nodes: list[str]) -> str:
    path_key = "|".join(path_nodes) if path_nodes else "market"
    return _hash_id("SIG", f"catalyst|{event_id}|{path_key}")


def event_in_window(event_date: date, *, today: date | None = None, window_days: int = 5) -> bool:
    current = today or date.today()
    delta = (event_date - current).days
    return 0 <= delta <= window_days


def _lead_days(event_date: date, today: date) -> int:
    return max(0, (event_date - today).days)


def _freshness_window_score(lead_days: int, window_days: int) -> int:
    if lead_days == 0:
        return 15
    if lead_days <= 2:
        return 12
    if lead_days <= window_days:
        return 8
    return 0


def _hit_boost(user_hits: dict[str, list[str]]) -> int:
    boost = 0
    if user_hits.get("portfolio"):
        boost += 20
    if user_hits.get("watchlist"):
        boost += 12
    if user_hits.get("preferences"):
        boost += 8
    return boost


def _alert_level(value_score: int, *, has_portfolio_hit: bool, importance: int) -> str:
    if value_score >= 80 or (has_portfolio_hit and importance >= 75):
        return "high"
    if value_score >= 60:
        return "medium"
    return "low"


def _impact_scope(user_hits: dict[str, list[str]]) -> list[str]:
    scope = ["market"]
    if user_hits.get("portfolio"):
        scope.insert(0, "portfolio")
    if user_hits.get("watchlist"):
        scope.append("watchlist")
    if user_hits.get("preferences"):
        scope.append("preferences")
    return scope


def build_catalyst_signal_payload(
    event: CatalystEvent,
    *,
    today: date | None = None,
    window_days: int = 5,
    path_nodes: list[str] | None = None,
    subject_name: str | None = None,
    subject_type: str = "concept",
    path_confidence: float = 0.6,
    user_hits: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    current = today or date.today()
    nodes = path_nodes or [event.title, *(event.subjects or [])[:1]]
    hits = user_hits or {"portfolio": [], "watchlist": [], "preferences": []}
    lead_days = _lead_days(event.event_date, current)
    freshness_score = _freshness_window_score(lead_days, window_days)
    score = int(event.importance * 0.45 + path_confidence * 100 * 0.25 + _hit_boost(hits) + freshness_score)
    value_score = max(0, min(100, score))
    alert_level = _alert_level(value_score, has_portfolio_hit=bool(hits.get("portfolio")), importance=event.importance)
    primary_subject = subject_name or (event.subjects[0] if event.subjects else event.title)
    possible_impact = f"{event.title}可能影响{primary_subject}相关链条预期"

    return {
        "signal_id": stable_catalyst_signal_id(event.event_id, nodes),
        "source_type": "catalyst_event",
        "source_id": event.event_id,
        "source_title": event.title,
        "source_url": event.source_url,
        "published_at": None,
        "signal_kind": "catalyst",
        "event_date": event.event_date,
        "subject_name": primary_subject,
        "subject_type": subject_type,
        "signal_type": event.event_type,
        "polarity": "neutral",
        "strength": event.importance,
        "confidence": Decimal(str(round(path_confidence, 3))),
        "freshness_score": freshness_score,
        "value_score": value_score,
        "summary": possible_impact,
        "evidence_excerpt": None,
        "status": "new",
        "metadata": {
            "catalyst": {
                "event_id": event.event_id,
                "lead_days": lead_days,
                "event_type": event.event_type,
                "alert_level": alert_level,
                "impact_scope": _impact_scope(hits),
                "subjects": event.subjects or [],
                "possible_impact": possible_impact,
            },
            "user_hits": hits,
            "portfolio_hits": hits.get("portfolio", []),
            "path_nodes": nodes,
            "lifecycle": "today" if lead_days == 0 else "upcoming",
        },
    }


async def upsert_catalyst_events(
    session: AsyncSession,
    candidates: list[CatalystEventCandidate],
) -> list[CatalystEvent]:
    events: list[CatalystEvent] = []
    for candidate in candidates:
        event_id = stable_catalyst_event_id(candidate)
        result = await session.execute(select(CatalystEvent).where(CatalystEvent.event_id == event_id))
        existing = result.scalar_one_or_none()
        if existing is None:
            event = CatalystEvent(
                event_id=event_id,
                event_type=candidate.event_type,
                title=candidate.title,
                event_date=candidate.event_date,
                event_time=candidate.event_time,
                timezone=candidate.timezone,
                source_type=candidate.source_type,
                source_id=candidate.source_id,
                source_url=candidate.source_url,
                importance=candidate.importance,
                subjects=candidate.subjects,
                metadata_=candidate.metadata,
            )
            session.add(event)
            events.append(event)
        else:
            existing.event_type = candidate.event_type
            existing.title = candidate.title
            existing.event_date = candidate.event_date
            existing.event_time = candidate.event_time
            existing.timezone = candidate.timezone
            existing.source_url = candidate.source_url
            existing.importance = candidate.importance
            existing.subjects = candidate.subjects
            existing.metadata_ = candidate.metadata
            events.append(existing)
    await session.commit()
    return events


async def generate_catalyst_signals(
    session: AsyncSession,
    *,
    today: date | None = None,
    window_days: int = 5,
) -> dict[str, int]:
    current = today or date.today()
    candidates = FixtureCatalystProvider().list_candidates(today=current)
    events = await upsert_catalyst_events(session, candidates)
    generated = 0
    updated = 0

    for event in events:
        if event.status != "scheduled" or not event_in_window(event.event_date, today=current, window_days=window_days):
            continue
        path_nodes = [event.title, *(event.subjects or [])[:2]]
        payload = build_catalyst_signal_payload(
            event,
            today=current,
            window_days=window_days,
            path_nodes=path_nodes,
            subject_name=event.subjects[0] if event.subjects else event.title,
            subject_type="concept" if event.subjects else "event",
            path_confidence=0.72 if event.subjects else 0.6,
        )
        result = await session.execute(select(Signal).where(Signal.signal_id == payload["signal_id"]))
        signal = result.scalar_one_or_none()
        values = dict(payload)
        metadata = values.pop("metadata")
        if signal is None:
            signal = Signal(**values, metadata_=metadata)
            session.add(signal)
            generated += 1
        else:
            for key, value in values.items():
                setattr(signal, key, value)
            signal.metadata_ = metadata
            updated += 1

        if len(path_nodes) >= 2:
            propagation_id = _hash_id("PROP", f"{payload['signal_id']}|{'|'.join(path_nodes)}", length=24)
            prop_result = await session.execute(
                select(SignalPropagation).where(SignalPropagation.propagation_id == propagation_id)
            )
            if prop_result.scalar_one_or_none() is None:
                session.add(
                    SignalPropagation(
                        propagation_id=propagation_id,
                        signal_id=payload["signal_id"],
                        target_name=path_nodes[-1],
                        target_type="concept",
                        relation_path=" -> ".join(path_nodes),
                        direction="uncertain",
                        impact_horizon="short",
                        confidence=Decimal("0.720"),
                        reasoning="未来事件可能提升相关主题关注度，需结合公告、行情和基本面进一步验证。",
                        evidence_refs=[{"type": "catalyst_event", "id": event.event_id}],
                        metadata_={"path_nodes": path_nodes},
                    )
                )

    await session.commit()
    return {"events": len(events), "generated": generated, "updated": updated}
