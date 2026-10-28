"""HTTPS 写入边界：worker 侧算好的结果落 Qdrant / PG。"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text

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
    # 开放词表聚合锚点 + metric 结构化数值（横向/纵向对比与预期差计算所需）
    parent: str | None = None
    value: str | None = None
    unit: str | None = None
    period: str | None = None


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
            parent=a.parent,
            value=a.value,
            unit=a.unit,
            period=a.period,
        )
        for a in req.actions
    ]
    async with async_session() as session:
        links = await persist_link_actions(session, req.evidence_id, actions)
        ledger = await run_link_ledger_pipeline(session, req.evidence_id)
    return {"ok": True, "links": links, **ledger}


class PriorLinesRequest(BaseModel):
    terms: list[str] = Field(default_factory=list)
    limit: int = Field(8, ge=1, le=50)


@router.post("/signal/prior-lines")
async def signal_prior_lines(req: PriorLinesRequest, x_api_key: str | None = Header(default=None)):
    """worker 侧 signal 推导查水位；worker 不直连 PG。"""
    require_api_key(x_api_key)
    from app.signals.research_derivation import _lookup_prior_signal_lines_db

    return {"lines": await _lookup_prior_signal_lines_db(req.terms, limit=req.limit)}


class SignalRecord(BaseModel):
    signal_id: str = Field(min_length=1, max_length=40)
    source_type: str = Field(min_length=1, max_length=32)
    source_id: str = Field(min_length=1, max_length=128)
    source_title: str | None = None
    source_url: str | None = None
    published_at: datetime | None = None
    signal_kind: str = "observed"
    event_date: date | None = None
    detected_at: datetime | None = None
    subject_name: str
    subject_type: str
    signal_type: str
    polarity: str
    strength: int
    confidence: Decimal
    freshness_score: int
    value_score: int
    summary: str
    evidence_excerpt: str | None = None
    status: str = "new"
    metadata_: dict[str, Any] = Field(default_factory=dict)


class PropagationRecord(BaseModel):
    propagation_id: str = Field(min_length=1, max_length=48)
    signal_id: str = Field(min_length=1, max_length=40)
    target_name: str
    target_type: str
    relation_path: str
    direction: str
    impact_horizon: str
    confidence: Decimal
    reasoning: str
    evidence_refs: list[dict[str, Any]] = Field(default_factory=list)
    metadata_: dict[str, Any] = Field(default_factory=dict)


class SignalUpsertRequest(BaseModel):
    signals: list[SignalRecord] = Field(default_factory=list)
    propagations: list[PropagationRecord] = Field(default_factory=list)


@router.post("/signal/upsert")
async def signal_upsert(req: SignalUpsertRequest, x_api_key: str | None = Header(default=None)):
    """worker 算好的 signal / propagation 经此落库。"""
    require_api_key(x_api_key)
    if not req.signals and not req.propagations:
        return {"signals_upserted": 0, "propagations_upserted": 0}
    from app.signals.evidence_ingestion import _upsert_signal_records

    async with async_session() as session:
        signals_upserted, propagations_upserted = await _upsert_signal_records(
            session,
            [item.model_dump(exclude_none=True) for item in req.signals],
            [item.model_dump(exclude_none=True) for item in req.propagations],
        )
        await session.commit()
    return {
        "signals_upserted": signals_upserted,
        "propagations_upserted": propagations_upserted,
    }


class AnnouncementStoredRequest(BaseModel):
    source_url: str = Field(min_length=1, max_length=1000)
    ann_date: date
    ts_code: str = Field(min_length=1, max_length=20)
    file_path: str = Field(min_length=1, max_length=1000)
    evidence_inputs: int = Field(0, ge=0)


@router.post("/announcement/mark-stored")
async def mark_announcement_stored(
    req: AnnouncementStoredRequest, x_api_key: str | None = Header(default=None)
):
    """PDF worker 下载/建 evidence 后回写 minishare_announcements 台账。

    `evidence_at` 表示“PDF 已被 worker 处理过”，0 条 evidence 也标记，避免
    `announcement_ingestion` 对无正文的提示性公告反复按 60s 超时解析。
    """
    require_api_key(x_api_key)
    async with async_session() as session:
        result = await session.execute(
            text(
                """
                UPDATE minishare_announcements
                SET file_path = :file_path,
                    download_status = 'stored',
                    evidence_at = COALESCE(evidence_at, now())
                WHERE source_url = :source_url
                  AND ann_date = :ann_date
                  AND ts_code = :ts_code
                """
            ),
            {
                "file_path": req.file_path,
                "source_url": req.source_url,
                "ann_date": req.ann_date,
                "ts_code": req.ts_code,
            },
        )
        await session.commit()
    return {"updated": result.rowcount}
