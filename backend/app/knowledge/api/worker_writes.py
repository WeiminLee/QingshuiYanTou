"""HTTPS 写入边界：worker 侧算好的结果落 Qdrant / PG。"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from app.knowledge.api._auth import require_api_key
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
