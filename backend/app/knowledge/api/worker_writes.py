"""HTTPS 写入边界：worker 侧算好的结果落 Qdrant / PG。"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from app.core.database import async_session
from app.knowledge.api._auth import require_api_key
from app.knowledge.linklayer.ingest import LinkAction, persist_link_actions
from app.knowledge.linklayer.ingest import _parse_date as _parse_iso
from app.knowledge.linklayer.link_pipeline import run_link_ledger_pipeline
from app.knowledge.vector_client import COLLECTION_CHUNKS, VectorRecord, write_chunk_vector

router = APIRouter(prefix="/api/v1/knowledge", tags=["知识 Worker 写入"])


class VectorUpsertRequest(BaseModel):
    evidence_id: str = Field(min_length=1, max_length=200)
    vector: list[float] = Field(min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)
    collection: str = Field(default=COLLECTION_CHUNKS, max_length=100)


@router.post("/vector/upsert")
async def vector_upsert(req: VectorUpsertRequest, x_api_key: str | None = Header(default=None)):
    require_api_key(x_api_key)
    payload = dict(req.payload)
    payload.setdefault("evidence_id", req.evidence_id)
    record = VectorRecord(
        id=str(uuid.uuid5(uuid.NAMESPACE_DNS, req.evidence_id)),
        vector=req.vector,
        payload=payload,
    )
    if not write_chunk_vector(record, req.collection):
        raise HTTPException(502, "vector write failed")
    return {"ok": True}


class LinkActionPayload(BaseModel):
    layer: str = Field(min_length=1, max_length=40)
    norm_text: str = Field(min_length=1, max_length=500)
    source: str = Field(min_length=1, max_length=40)
    span_start: int = 0
    span_end: int = 0
    published_at: str | None = None
    dimension: str | None = None
    level: int | None = None


class LinkUpsertRequest(BaseModel):
    evidence_id: str = Field(min_length=1, max_length=200)
    actions: list[LinkActionPayload] = Field(default_factory=list)


@router.post("/link/upsert")
async def link_upsert(req: LinkUpsertRequest, x_api_key: str | None = Header(default=None)):
    require_api_key(x_api_key)
    actions = [
        LinkAction(
            layer=a.layer,
            norm_text=a.norm_text,
            source=a.source,
            span_start=a.span_start,
            span_end=a.span_end,
            published_at=_parse_iso(a.published_at),
            dimension=a.dimension,
            level=a.level,
        )
        for a in req.actions
    ]
    async with async_session() as session:
        links = await persist_link_actions(session, req.evidence_id, actions)
        ledger = await run_link_ledger_pipeline(session, req.evidence_id)
    return {"ok": True, "links": links, **ledger}
