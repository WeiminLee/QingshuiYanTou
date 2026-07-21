from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class SourceStatus(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    MISSING = "missing"
    FAILED = "failed"


class ThresholdKind(StrEnum):
    NATURAL_DAY = "natural_day"
    TRADING_DAY = "trading_day"


class ReadinessSource(BaseModel):
    source: str
    display_name: str
    status: SourceStatus
    latest_data_date: str | None = None
    latest_success_at: str | None = None
    lag_days: int | None = None
    threshold_days: int
    threshold_kind: ThresholdKind
    coverage_scope: str = "unknown"
    required_for_reasoning: bool = True
    last_error: str | None = None
    recommendation: str


class ReadinessSummary(BaseModel):
    as_of: str
    overall_status: str = Field(pattern="^(fresh|degraded|unavailable)$")
    sources: list[ReadinessSource]
    summary: str
