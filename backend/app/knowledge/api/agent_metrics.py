"""Agent-facing metric / graph-walk HTTP (dsh plugin boundary).

Calls pure app.knowledge.* services — no LangChain @tool wrappers on this path.
HTTP contracts stable for plugins/qingshui.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from app.knowledge.api._auth import require_api_key
from app.knowledge import agent_graph_ops, agent_metric_ops

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


async def _run(label: str, coro) -> Any:
    try:
        return await coro
    except Exception as exc:  # noqa: BLE001
        logger.exception("agent op %s failed", label)
        raise HTTPException(500, f"tool failed: {exc}") from exc


@router.post("/compare_metric")
async def api_compare_metric(
    req: CompareMetricRequest,
    x_api_key: str | None = Header(default=None),
):
    require_api_key(x_api_key)
    return await _run(
        "compare_metric",
        agent_metric_ops.compare_metric(
            dimension=req.dimension,
            scope=req.scope,
            as_of=req.as_of,
            top_k=req.top_k,
        ),
    )


@router.post("/metric_trend")
async def api_metric_trend(
    req: MetricTrendRequest,
    x_api_key: str | None = Header(default=None),
):
    require_api_key(x_api_key)
    return await _run(
        "metric_trend",
        agent_metric_ops.metric_trend(
            subject=req.subject,
            dimension=req.dimension,
            limit=req.limit,
        ),
    )


@router.post("/rollup_metric")
async def api_rollup_metric(
    req: RollupMetricRequest,
    x_api_key: str | None = Header(default=None),
):
    require_api_key(x_api_key)
    return await _run(
        "rollup_metric",
        agent_metric_ops.rollup_metric(
            parent=req.parent,
            scope=req.scope,
            top_k=req.top_k,
        ),
    )


@router.post("/related_nodes")
async def api_related_nodes(
    req: RelatedNodesRequest,
    x_api_key: str | None = Header(default=None),
):
    require_api_key(x_api_key)
    return await _run(
        "related_nodes",
        agent_graph_ops.related_nodes(
            keyword=req.keyword,
            layer=req.layer,
            top_k=req.top_k,
        ),
    )


@router.post("/propagate_along")
async def api_propagate_along(
    req: PropagateAlongRequest,
    x_api_key: str | None = Header(default=None),
):
    require_api_key(x_api_key)
    return await _run(
        "propagate_along",
        agent_graph_ops.propagate_along(
            start=req.start,
            max_hops=req.max_hops,
            min_cooccur=req.min_cooccur,
            top_k=req.top_k,
        ),
    )
