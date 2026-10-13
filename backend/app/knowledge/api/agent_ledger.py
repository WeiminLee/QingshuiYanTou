# backend/app/knowledge/api/agent_ledger.py
"""Agent-facing 判断台账 HTTP（write_observation / write_finding / history / search / watermark）。

写工具只在此面暴露（插件 tools.ts 直连）；Data MCP 第一期只读，不包装写端点。
薄壳模式同 agent_links.py：require_api_key + agent_ledger_ops 共享函数。
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from app.knowledge import agent_ledger_ops
from app.knowledge.api._auth import require_api_key

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/knowledge/ledger", tags=["知识 Agent 台账"])


class SpanRef(BaseModel):
    evidence_id: str = Field(min_length=3, max_length=128)
    span_start: int = Field(default=0, ge=0)
    span_end: int = Field(default=0, ge=0)
    obs_id: str | None = Field(default=None, max_length=32)


class SaveObservationRequest(BaseModel):
    subject_ts_code: str = Field(min_length=1, max_length=32)
    dimension: str = Field(min_length=1, max_length=100)
    evidence_id: str = Field(min_length=3, max_length=128)
    span_start: int = Field(ge=0)
    span_end: int = Field(ge=0)
    stage_raw: str | None = Field(default=None, max_length=300)
    stage_level: int | None = Field(default=None, ge=0, le=20)
    dimension_scope: str | None = Field(default=None, max_length=200)
    subject_name: str | None = Field(default=None, max_length=200)
    event_date: str | None = Field(default=None, max_length=32)
    published_at: str | None = Field(default=None, max_length=64)
    metric_value: dict | None = None


class SaveFindingRequest(BaseModel):
    subject_ts_code: str = Field(min_length=1, max_length=32)
    dimension: str = Field(min_length=1, max_length=100)
    kind: str = Field(min_length=1, max_length=24)
    judgment: str = Field(min_length=1, max_length=4000)
    supports: list[SpanRef] = Field(min_length=1, max_length=20)
    dimension_scope: str | None = Field(default=None, max_length=200)
    from_state: dict | None = None
    to_state: dict | None = None
    delta: dict | None = None
    contradicts: list[SpanRef] = Field(default_factory=list, max_length=20)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    supersedes: str | None = Field(default=None, max_length=32)
    created_by: dict | None = None


class HistoryRequest(BaseModel):
    subject: str = Field(min_length=1, max_length=200)
    dimension: str | None = Field(default=None, max_length=200)
    scope: str | None = Field(default=None, max_length=200)
    before: str | None = Field(default=None, max_length=64)
    limit: int = Field(default=50, ge=1, le=200)


class SearchRequest(BaseModel):
    dimension: str | None = Field(default=None, max_length=200)
    kind: str | None = Field(default=None, max_length=24)
    status: str | None = Field(default=None, max_length=16)
    since: str | None = Field(default=None, max_length=64)
    limit: int = Field(default=50, ge=1, le=200)


class WatermarkRequest(BaseModel):
    subject_ts_code: str = Field(min_length=1, max_length=32)
    dimension: str = Field(min_length=1, max_length=200)
    dimension_scope: str | None = Field(default=None, max_length=200)


async def _run(label: str, coro) -> Any:
    try:
        return await coro
    except Exception as exc:  # noqa: BLE001
        logger.exception("agent ledger op %s failed", label)
        raise HTTPException(500, f"tool failed: {exc}") from exc


@router.post("/observation")
async def api_save_observation(
    req: SaveObservationRequest,
    x_api_key: str | None = Header(default=None),
):
    require_api_key(x_api_key)
    return await _run(
        "save_observation",
        agent_ledger_ops.save_observation(
            subject_ts_code=req.subject_ts_code,
            dimension=req.dimension,
            evidence_id=req.evidence_id,
            span_start=req.span_start,
            span_end=req.span_end,
            stage_raw=req.stage_raw,
            stage_level=req.stage_level,
            dimension_scope=req.dimension_scope,
            subject_name=req.subject_name,
            event_date=req.event_date,
            published_at=req.published_at,
            metric_value=req.metric_value,
        ),
    )


@router.post("/finding")
async def api_save_finding(
    req: SaveFindingRequest,
    x_api_key: str | None = Header(default=None),
):
    require_api_key(x_api_key)
    return await _run(
        "save_finding",
        agent_ledger_ops.save_finding(
            subject_ts_code=req.subject_ts_code,
            dimension=req.dimension,
            kind=req.kind,
            judgment=req.judgment,
            supports=[s.model_dump() for s in req.supports],
            dimension_scope=req.dimension_scope,
            from_state=req.from_state,
            to_state=req.to_state,
            delta=req.delta,
            contradicts=[c.model_dump() for c in req.contradicts],
            confidence=req.confidence,
            supersedes=req.supersedes,
            created_by=req.created_by,
        ),
    )


@router.post("/history")
async def api_history_findings(
    req: HistoryRequest,
    x_api_key: str | None = Header(default=None),
):
    require_api_key(x_api_key)
    return await _run(
        "history_findings",
        agent_ledger_ops.history_findings(
            subject=req.subject,
            dimension=req.dimension,
            scope=req.scope,
            before=req.before,
            limit=req.limit,
        ),
    )


@router.post("/search")
async def api_search_findings(
    req: SearchRequest,
    x_api_key: str | None = Header(default=None),
):
    require_api_key(x_api_key)
    return await _run(
        "search_findings",
        agent_ledger_ops.search_findings(
            dimension=req.dimension,
            kind=req.kind,
            status=req.status,
            since=req.since,
            limit=req.limit,
        ),
    )


@router.post("/watermark")
async def api_read_watermark(
    req: WatermarkRequest,
    x_api_key: str | None = Header(default=None),
):
    require_api_key(x_api_key)
    return await _run(
        "read_watermark",
        agent_ledger_ops.read_watermark(
            subject_ts_code=req.subject_ts_code,
            dimension=req.dimension,
            dimension_scope=req.dimension_scope,
        ),
    )
