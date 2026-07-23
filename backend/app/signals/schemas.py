from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class SignalListItem(BaseModel):
    signal_id: str
    title: str
    summary: str
    source_type: str
    published_at: datetime | None = None
    signal_kind: str = "observed"
    event_date: datetime | str | None = None
    subject_name: str
    signal_type: str
    polarity: str
    value_score: int
    confidence: float
    portfolio_hits: list[str] = Field(default_factory=list)
    lead_days: int | None = None
    alert_level: str | None = None
    impact_scope: list[str] = Field(default_factory=list)


class SignalListResponse(BaseModel):
    items: list[SignalListItem]
    total: int


class SignalPathEdge(BaseModel):
    src: str
    rel_type: str
    tgt: str
    weight: float
    text: str = ""


class SignalPathOut(BaseModel):
    nodes: list[str] = Field(default_factory=list)
    edges: list[SignalPathEdge] = Field(default_factory=list)
    hops: int
    confidence: float


class SignalPropagationOut(BaseModel):
    target_name: str
    target_type: str
    relation_path: str
    direction: str
    impact_horizon: str
    confidence: float
    reasoning: str
    evidence_refs: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    signal_path: SignalPathOut | None = None


class SignalUserHits(BaseModel):
    portfolio: list[str] = Field(default_factory=list)
    watchlist: list[str] = Field(default_factory=list)
    preferences: list[str] = Field(default_factory=list)


class SignalMemoryOut(BaseModel):
    schema_version: str = "signal.memory.v1"
    signal_id: str
    lifecycle_status: str = "active"
    user_status: str = "new"
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None
    reinforced_count: int = 0
    contradicted_count: int = 0
    source_count: int = 1


class SignalDetail(BaseModel):
    schema_version: str = "signal.context.v1"
    signal_id: str
    title: str
    summary: str
    source_type: str
    source_title: str | None = None
    source_url: str | None = None
    published_at: datetime | None = None
    signal_kind: str = "observed"
    event_date: datetime | str | None = None
    subject_name: str
    subject_type: str
    signal_type: str
    polarity: str
    strength: int
    confidence: float
    value_score: int
    evidence_excerpt: str | None = None
    status: str
    portfolio_hits: list[str] = Field(default_factory=list)
    source: dict[str, Any] = Field(default_factory=dict)
    primary_signal: dict[str, Any] = Field(default_factory=dict)
    catalyst: dict[str, Any] = Field(default_factory=dict)
    memory: SignalMemoryOut | None = None
    user_hits: SignalUserHits = Field(default_factory=SignalUserHits)
    propagations: list[SignalPropagationOut] = Field(default_factory=list)


class SignalStatusUpdate(BaseModel):
    status: str
