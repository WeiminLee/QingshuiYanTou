"""
知识构建层 — 关系 API

路由前缀：/api/v1/knowledge/relation
"""
from __future__ import annotations

import asyncio
from datetime import date as _date
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.knowledge.relation_service import (
    upsert_relation,
    batch_upsert_relations,
    query_relations,
    link_company_to_industry,
    RELATIONSHIP_TYPES,
)

router = APIRouter(prefix="/api/v1/knowledge/relation", tags=["知识构建层"])


# ── Models ───────────────────────────────────────────

class RelationCreate(BaseModel):
    from_entity: str
    to_entity: str
    relationship_type: str
    properties: Optional[dict] = None
    confidence: float = 0.80
    source_type: Optional[str] = None
    source_name: Optional[str] = None
    evidence_url: Optional[str] = None
    article_ref: Optional[str] = None
    notes: Optional[str] = None
    valid_from: Optional[str] = None   # YYYY-MM-DD
    valid_to: Optional[str] = None


class RelationBatchCreate(BaseModel):
    relations: list[RelationCreate]


class RelationResponse(BaseModel):
    from_entity: str
    to_entity: str
    relationship_type: str
    properties: dict
    confidence: float
    source_type: Optional[str]
    source_name: Optional[str]
    evidence_url: Optional[str]
    article_ref: Optional[str]
    notes: Optional[str]
    valid_from: Optional[str]
    valid_to: Optional[str]
    superseded_by: Optional[str]

    @classmethod
    def from_result(cls, r: dict):
        return cls(
            from_entity=r.get("from_entity", ""),
            to_entity=r.get("to_entity", ""),
            relationship_type=r.get("relationship_type", ""),
            properties=r.get("properties") or {},
            confidence=float(r.get("confidence") or 0.80),
            source_type=r.get("source_type"),
            source_name=r.get("source_name"),
            evidence_url=r.get("evidence_url"),
            article_ref=r.get("article_ref"),
            notes=r.get("notes"),
            valid_from=r.get("valid_from"),
            valid_to=r.get("valid_to"),
            superseded_by=str(r.get("superseded_by")) if r.get("superseded_by") else None,
        )


class BatchResult(BaseModel):
    inserted: int
    updated: int


# ── 路由 ──────────────────────────────────────────

@router.post("", response_model=RelationResponse)
async def create_or_update_relation(body: RelationCreate):
    """创建或更新一条关系"""
    if body.relationship_type not in RELATIONSHIP_TYPES:
        raise HTTPException(
            400,
            f"无效 relationship_type，可选值: {sorted(RELATIONSHIP_TYPES)}"
        )

    valid_from = _date.fromisoformat(body.valid_from) if body.valid_from else None
    valid_to = _date.fromisoformat(body.valid_to) if body.valid_to else None

    rel, _ = await asyncio.to_thread(
        upsert_relation,
        from_entity=body.from_entity,
        to_entity=body.to_entity,
        relationship_type=body.relationship_type,
        properties=body.properties,
        confidence=body.confidence,
        source_type=body.source_type,
        source_name=body.source_name,
        evidence_url=body.evidence_url,
        article_ref=body.article_ref,
        notes=body.notes,
        valid_from=valid_from,
        valid_to=valid_to,
    )
    return RelationResponse.from_result(rel)


@router.post("/batch", response_model=BatchResult)
async def batch_create_relations(body: RelationBatchCreate):
    """批量创建/更新关系"""
    results = []
    for item in body.relations:
        if item.relationship_type not in RELATIONSHIP_TYPES:
            raise HTTPException(400, f"无效 relationship_type: {item.relationship_type}")
        valid_from = _date.fromisoformat(item.valid_from) if item.valid_from else None
        valid_to = _date.fromisoformat(item.valid_to) if item.valid_to else None
        results.append(dict(
            from_entity=item.from_entity,
            to_entity=item.to_entity,
            relationship_type=item.relationship_type,
            properties=item.properties,
            confidence=item.confidence,
            source_type=item.source_type,
            source_name=item.source_name,
            evidence_url=item.evidence_url,
            article_ref=item.article_ref,
            notes=item.notes,
            valid_from=valid_from,
            valid_to=valid_to,
        ))

    inserted, updated = await asyncio.to_thread(batch_upsert_relations, results)
    return BatchResult(inserted=inserted, updated=updated)


@router.get("", response_model=list[RelationResponse])
async def list_relations(
    from_entity: Optional[str] = Query(None),
    to_entity: Optional[str] = Query(None),
    relationship_type: Optional[str] = Query(None),
    ts_code: Optional[str] = Query(None),
    valid_at: Optional[str] = Query(None),  # YYYY-MM-DD AS-OF 切片
    active_only: bool = Query(True),         # 仅返回当前有效关系
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """查询关系边列表（默认仅返回当前有效关系，active_only=False 可查全部历史）"""
    if relationship_type and relationship_type not in RELATIONSHIP_TYPES:
        raise HTTPException(
            400,
            f"无效 relationship_type，可选值: {sorted(RELATIONSHIP_TYPES)}"
        )

    valid_at_date = _date.fromisoformat(valid_at) if valid_at else None

    relations = await asyncio.to_thread(
        query_relations,
        from_entity=from_entity,
        to_entity=to_entity,
        relationship_type=relationship_type,
        ts_code=ts_code,
        valid_at=valid_at_date,
        active_only=active_only,
        limit=limit,
        offset=offset,
    )
    return [RelationResponse.from_result(r) for r in relations]


@router.post("/company-industry", response_model=RelationResponse)
async def link_company_to_industry_api(
    ts_code: str,
    company_name: str,
    ths_code: str,
    industry_name: str,
    source_type: str,
    source_name: str,
    valid_from: Optional[str] = None,
    properties: Optional[dict] = None,
):
    """快捷接口：建立 [公司] -[BELONGS_TO]-> [行业] 关系"""
    vf = _date.fromisoformat(valid_from) if valid_from else None
    rel, _ = await asyncio.to_thread(
        link_company_to_industry,
        ts_code=ts_code,
        company_name=company_name,
        ths_code=ths_code,
        industry_name=industry_name,
        source_type=source_type,
        source_name=source_name,
        valid_from=vf,
        properties=properties,
    )
    return RelationResponse.from_result(rel)
