from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class UserSnapshotDTO(BaseModel):
    schema_version: str = "user.snapshot.v1"
    user_id: str
    portfolio: list[dict[str, Any]] = Field(default_factory=list)
    watchlist: list[dict[str, Any]] = Field(default_factory=list)
    preferences: list[dict[str, Any]] = Field(default_factory=list)


class UserHitDTO(BaseModel):
    portfolio: list[str] = Field(default_factory=list)
    watchlist: list[str] = Field(default_factory=list)
    preferences: list[str] = Field(default_factory=list)


class SignalMemoryDTO(BaseModel):
    schema_version: str = "signal.memory.v1"
    signal_id: str
    lifecycle_status: str = "active"
    user_status: str = "new"
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None
    reinforced_count: int = 0
    contradicted_count: int = 0
    source_count: int = 1


class ReadinessContextDTO(BaseModel):
    overall_status: str = "unknown"
    answer_boundary: str = ""


class SignalContextDTO(BaseModel):
    schema_version: str = "signal.context.v1"
    signal: dict[str, Any] = Field(default_factory=dict)
    source: dict[str, Any] = Field(default_factory=dict)
    primary_signal: dict[str, Any] = Field(default_factory=dict)
    memory: SignalMemoryDTO | None = None
    user_hits: UserHitDTO = Field(default_factory=UserHitDTO)
    portfolio_hits: list[str] = Field(default_factory=list)
    propagations: list[dict[str, Any]] = Field(default_factory=list)


class AgentContextDTO(BaseModel):
    schema_version: str = "agent.context.v1"
    context_type: str
    route: str
    user_id: str
    thread_id: str
    question: str
    user_snapshot: UserSnapshotDTO | None = None
    signal_context: SignalContextDTO | None = None
    readiness_context: ReadinessContextDTO = Field(default_factory=ReadinessContextDTO)
    prompt_context: str = ""
    warnings: list[str] = Field(default_factory=list)
