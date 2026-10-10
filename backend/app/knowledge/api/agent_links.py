"""Agent-facing link-layer read HTTP (pull_history / lookup_*).

Calls app.knowledge.linklayer.queries — no LangChain @tool wrappers.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from app.knowledge.api._auth import require_api_key
from app.knowledge.linklayer import queries as link_queries

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/knowledge/links", tags=["知识 Agent Links"])


class PullHistoryRequest(BaseModel):
    subject: str = Field(min_length=1, max_length=200)
    dimension: str | None = Field(default=None, max_length=200)
    scope: str | None = Field(default=None, max_length=200)
    before: str | None = Field(default=None, max_length=64)
    limit: int = Field(default=100, ge=1, le=500)


class LookupPlayersRequest(BaseModel):
    keyword_norm_text: str = Field(min_length=1, max_length=200)
    top_k: int = Field(default=20, ge=1, le=100)


class LookupProductsRequest(BaseModel):
    company: str = Field(min_length=1, max_length=200)
    top_k: int = Field(default=20, ge=1, le=100)


async def _run(label: str, coro) -> Any:
    try:
        return await coro
    except Exception as exc:  # noqa: BLE001
        logger.exception("agent links op %s failed", label)
        raise HTTPException(500, f"tool failed: {exc}") from exc


@router.post("/history")
async def api_pull_history(
    req: PullHistoryRequest,
    x_api_key: str | None = Header(default=None),
):
    require_api_key(x_api_key)
    return await _run(
        "pull_history",
        link_queries.pull_history(
            subject=req.subject,
            dimension=req.dimension,
            scope=req.scope,
            before=req.before,
            limit=req.limit,
        ),
    )


@router.post("/lookup_players")
async def api_lookup_players(
    req: LookupPlayersRequest,
    x_api_key: str | None = Header(default=None),
):
    require_api_key(x_api_key)
    rows = await _run(
        "lookup_players",
        link_queries.lookup_players(
            keyword_norm_text=req.keyword_norm_text,
            top_k=req.top_k,
        ),
    )
    return {"items": rows, "count": len(rows)}


@router.post("/lookup_products")
async def api_lookup_products(
    req: LookupProductsRequest,
    x_api_key: str | None = Header(default=None),
):
    require_api_key(x_api_key)
    rows = await _run(
        "lookup_products",
        link_queries.lookup_products(
            company=req.company,
            top_k=req.top_k,
        ),
    )
    return {"items": rows, "count": len(rows)}
