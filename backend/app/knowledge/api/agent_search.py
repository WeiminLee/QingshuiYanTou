"""Agent-facing Knowledge search HTTP (dsh plugin boundary)."""
from __future__ import annotations

import logging
from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from app.knowledge import agent_metric_ops
from app.knowledge.api._auth import require_api_key
from app.knowledge.linklayer import queries as link_queries
from app.knowledge.retrieval.facts import get_catalog
from app.knowledge.retrieval.route import numeric_slots_filled, retrieve_bound_or_residual
from app.knowledge.retrieval.search import search_current_facts, search_fact_history
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
    subject: str | None = Field(default=None, max_length=200)
    dimension: str | None = Field(default=None, max_length=200)
    period: str | None = Field(default=None, max_length=64)
    value: str | None = Field(default=None, max_length=64)
    as_of: str | None = Field(default=None, max_length=32)
    fact_view: Literal["current", "history"] = "current"


def search_current_text(query: str, *, as_of: str) -> list[dict]:
    """Current text retrieval: in-force short facts, not the raw chunk."""
    return search_current_facts(query, as_of=as_of)


def search_fact_history_text(*, subject: str, dimension: str | None = None) -> list[dict]:
    """Same facts, including those whose validity interval has ended."""
    return search_fact_history(subject=subject, dimension=dimension)


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
    chunk: dict[str, Any] = {
        "evidence_id": payload.get("evidence_id", ""),
        "snippet": snippet,
        "source_type": payload.get("source_type", ""),
        "source_name": payload.get("source_name", ""),
        "score": round(float(r.score), 4),
    }
    publish_date = payload.get("publish_date")
    if publish_date:
        chunk["publish_date"] = str(publish_date)
    title = None
    subject_hint = payload.get("subject_hint")
    if isinstance(subject_hint, dict):
        title = subject_hint.get("title")
    if not title:
        metadata = payload.get("metadata")
        if isinstance(metadata, dict):
            title = metadata.get("title")
    if title:
        chunk["title"] = title
    source_ref = payload.get("source_ref")
    if isinstance(source_ref, dict) and source_ref.get("pdf_url"):
        chunk["pdf_url"] = source_ref["pdf_url"]
    return chunk


@router.post("/search/semantic")
async def search_semantic(
    req: SemanticSearchRequest,
    x_api_key: str | None = Header(default=None),
):
    require_api_key(x_api_key)
    if req.scope not in _VALID_SCOPES:
        raise HTTPException(400, f"无效 scope={req.scope}")
    if numeric_slots_filled(req.subject, req.dimension, req.period, req.value):
        as_of = req.as_of or date.today().isoformat()
        return await retrieve_bound_or_residual(
            query=req.query,
            subject=req.subject,
            dimension=req.dimension,
            period=req.period,
            value=req.value,
            compare_metric=agent_metric_ops.compare_metric,
            pull_history=link_queries.pull_history,
            search_residual=lambda query: search_current_text(query, as_of=as_of),
        )
    result: dict[str, Any] = {}
    if req.scope in ("entities", "both"):
        try:
            hits = semantic_search_entities(req.query, ts_code=req.ts_code, top_k=req.top_k)
            result["entities"] = [_shape_entity(h) for h in hits]
        except Exception as e:  # noqa: BLE001
            logger.warning("semantic_search entities 失败: %s", e)
            result["entities"] = []
    if req.scope in ("chunks", "both"):
        if get_catalog().facts():
            as_of = req.as_of or date.today().isoformat()
            if req.fact_view == "history":
                result["facts"] = search_fact_history_text(subject=req.subject or "", dimension=req.dimension)
            else:
                result["facts"] = search_current_text(req.query, as_of=as_of)
        else:
            try:
                hits = semantic_search_chunks(req.query, ts_code=req.ts_code, top_k=req.top_k)
                result["chunks"] = [_shape_chunk(h) for h in hits]
            except Exception as e:  # noqa: BLE001
                logger.warning("semantic_search chunks 失败: %s", e)
                result["chunks"] = []
    return result
