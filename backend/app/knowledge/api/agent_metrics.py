"""Agent-facing metric / graph-walk HTTP (dsh plugin boundary).

Wraps existing LangChain tool implementations via .ainvoke so Knowledge HTTP
stays the only DB-facing surface for the Cordis plugin. Tool names kept:
compare_metric / metric_trend / rollup_metric (+ related_nodes / propagate_along
for 传导面).
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from app.knowledge.api._auth import require_api_key

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/knowledge/agent", tags=["知识 Agent 预期差"])


class CompareMetricRequest(BaseModel):
    dimension: str = Field(min_length=1, max_length=200)
    scope: str | None = Field(default=None, max_length=200)
    as_of: str | None = Field(default=None, max_length=64)
    top_k: int = Field(default=30, ge=1, le=100)


class MetricTrendRequest(BaseModel):
    subject: str = Field(min_length=1, max_length=200)
    dimension: str | None = Field(default=None, max_length=200)
    limit: int = Field(default=50, ge=1, le=200)


class RollupMetricRequest(BaseModel):
    parent: str = Field(min_length=1, max_length=200)
    scope: str | None = Field(default=None, max_length=200)
    top_k: int = Field(default=30, ge=1, le=100)


class RelatedNodesRequest(BaseModel):
    keyword: str = Field(min_length=1, max_length=200)
    layer: str | None = Field(default=None, max_length=64)
    top_k: int = Field(default=20, ge=1, le=100)


class PropagateAlongRequest(BaseModel):
    start: str = Field(min_length=1, max_length=200)
    max_hops: int = Field(default=1, ge=1, le=3)
    min_cooccur: int = Field(default=5, ge=1, le=1000)
    top_k: int = Field(default=20, ge=1, le=100)


async def _ainvoke(tool: Any, payload: dict[str, Any]) -> Any:
    try:
        return await tool.ainvoke(payload)
    except Exception as exc:  # noqa: BLE001
        logger.exception("agent tool %s failed", getattr(tool, "name", tool))
        raise HTTPException(500, f"tool failed: {exc}") from exc


@router.post("/compare_metric")
async def api_compare_metric(
    req: CompareMetricRequest,
    x_api_key: str | None = Header(default=None),
):
    require_api_key(x_api_key)
    from app.reasoning.tools.knowledge.metric_ops import compare_metric

    return await _ainvoke(
        compare_metric,
        {
            "dimension": req.dimension,
            "scope": req.scope,
            "as_of": req.as_of,
            "top_k": req.top_k,
        },
    )


@router.post("/metric_trend")
async def api_metric_trend(
    req: MetricTrendRequest,
    x_api_key: str | None = Header(default=None),
):
    require_api_key(x_api_key)
    from app.reasoning.tools.knowledge.metric_ops import metric_trend

    return await _ainvoke(
        metric_trend,
        {
            "subject": req.subject,
            "dimension": req.dimension,
            "limit": req.limit,
        },
    )


@router.post("/rollup_metric")
async def api_rollup_metric(
    req: RollupMetricRequest,
    x_api_key: str | None = Header(default=None),
):
    require_api_key(x_api_key)
    from app.reasoning.tools.knowledge.metric_ops import rollup_metric

    return await _ainvoke(
        rollup_metric,
        {
            "parent": req.parent,
            "scope": req.scope,
            "top_k": req.top_k,
        },
    )


@router.post("/related_nodes")
async def api_related_nodes(
    req: RelatedNodesRequest,
    x_api_key: str | None = Header(default=None),
):
    require_api_key(x_api_key)
    from app.reasoning.tools.knowledge.graph_walk import related_nodes

    payload: dict[str, Any] = {"keyword": req.keyword, "top_k": req.top_k}
    if req.layer:
        payload["layer"] = req.layer
    return await _ainvoke(related_nodes, payload)


@router.post("/propagate_along")
async def api_propagate_along(
    req: PropagateAlongRequest,
    x_api_key: str | None = Header(default=None),
):
    require_api_key(x_api_key)
    from app.reasoning.tools.knowledge.graph_walk import propagate_along

    return await _ainvoke(
        propagate_along,
        {
            "start": req.start,
            "max_hops": req.max_hops,
            "min_cooccur": req.min_cooccur,
            "top_k": req.top_k,
        },
    )
