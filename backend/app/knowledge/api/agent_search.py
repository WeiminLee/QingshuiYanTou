"""Agent-facing Knowledge search HTTP (dsh plugin boundary)."""
from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from app.knowledge.api._auth import require_api_key
from app.knowledge.vector_client import (
    semantic_search_chunks,
    semantic_search_entities,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/knowledge", tags=["知识 Agent 检索"])

_VALID_SCOPES = frozenset({"entities", "chunks", "both"})
_SNIPPET_MAX = 200


class SemanticSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    scope: Literal["entities", "chunks", "both"] = "entities"
    ts_code: str | None = Field(default=None, max_length=32)
    top_k: int = Field(default=5, ge=1, le=50)


def _shape_entity(r) -> dict[str, Any]:
    payload = r.payload or {}
    return {
        "entity_id": payload.get("entity_id") or r.id,
        "name": payload.get("entity_name", ""),
        "type": payload.get("entity_type", ""),
        "ts_code": payload.get("ts_code", ""),
        "score": round(float(r.score), 4),
    }


def _shape_chunk(r) -> dict[str, Any]:
    payload = r.payload or {}
    content = payload.get("content", "") or ""
    snippet = content[:_SNIPPET_MAX] + ("…" if len(content) > _SNIPPET_MAX else "")
    return {
        "evidence_id": payload.get("evidence_id", ""),
        "snippet": snippet,
        "source_type": payload.get("source_type", ""),
        "source_name": payload.get("source_name", ""),
        "score": round(float(r.score), 4),
    }


@router.post("/search/semantic")
async def search_semantic(
    req: SemanticSearchRequest,
    x_api_key: str | None = Header(default=None),
):
    require_api_key(x_api_key)
    if req.scope not in _VALID_SCOPES:
        raise HTTPException(400, f"无效 scope={req.scope}")
    result: dict[str, Any] = {}
    if req.scope in ("entities", "both"):
        try:
            hits = semantic_search_entities(req.query, ts_code=req.ts_code, top_k=req.top_k)
            result["entities"] = [_shape_entity(h) for h in hits]
        except Exception as e:  # noqa: BLE001
            logger.warning("semantic_search entities 失败: %s", e)
            result["entities"] = []
    if req.scope in ("chunks", "both"):
        try:
            hits = semantic_search_chunks(req.query, ts_code=req.ts_code, top_k=req.top_k)
            result["chunks"] = [_shape_chunk(h) for h in hits]
        except Exception as e:  # noqa: BLE001
            logger.warning("semantic_search chunks 失败: %s", e)
            result["chunks"] = []
    return result
