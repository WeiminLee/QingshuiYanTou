"""
知识构建层 — 实体 API

路由前缀：/api/v1/knowledge/entity
"""
import asyncio
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional

from app.knowledge.entity_service import (
    upsert_entity,
    batch_upsert_entities,
    get_entity,
    query_entities,
    generate_entity_id,
    ENTITY_TYPES,
)

router = APIRouter(prefix="/api/v1/knowledge/entity", tags=["知识构建层"])


# ── Request / Response Models ────────────────────────────────

class EntityCreate(BaseModel):
    entity_type: str
    name: str
    ts_code: Optional[str] = None
    metric_name: Optional[str] = None
    event_date: Optional[str] = None
    properties: Optional[dict] = None
    confidence: float = 0.80
    source_type: Optional[str] = None
    source_name: Optional[str] = None
    evidence_url: Optional[str] = None
    valid_from: Optional[str] = None  # YYYY-MM-DD
    valid_to: Optional[str] = None
    parser_version: str = "v1.0"


class EntityBatchCreate(BaseModel):
    entities: list[EntityCreate]


class EntityResponse(BaseModel):
    entity_id: str
    entity_type: str
    name: str
    ts_code: Optional[str]
    properties: dict
    confidence: float
    source_type: Optional[str]
    source_name: Optional[str]
    evidence_url: Optional[str]
    valid_from: Optional[str]
    valid_to: Optional[str]
    superseded_by: Optional[str]

    @classmethod
    def from_orm(cls, e):
        # 兼容 dict（旧 ORM 对象）和 plain dict（Neo4j 返回）
        if isinstance(e, dict):
            d = e
        else:
            d = {
                "entity_id": e.entity_id,
                "entity_type": e.entity_type,
                "name": e.name,
                "ts_code": e.ts_code,
                "properties": e.properties or {},
                "confidence": float(e.confidence or 0.80),
                "source_type": e.source_type,
                "source_name": e.source_name,
                "evidence_url": e.evidence_url,
                "valid_from": str(e.valid_from) if e.valid_from else None,
                "valid_to": str(e.valid_to) if e.valid_to else None,
                "superseded_by": e.superseded_by,
            }
        return cls(
            entity_id=d["entity_id"],
            entity_type=d["entity_type"],
            name=d["name"],
            ts_code=d.get("ts_code"),
            properties=d.get("properties") or {},
            confidence=float(d.get("confidence") or 0.80),
            source_type=d.get("source_type"),
            source_name=d.get("source_name"),
            evidence_url=d.get("evidence_url"),
            valid_from=d.get("valid_from"),
            valid_to=d.get("valid_to"),
            superseded_by=d.get("superseded_by"),
        )


class BatchResult(BaseModel):
    inserted: int
    updated: int


# ── 路由 ────────────────────────────────────────────────

@router.post("", response_model=EntityResponse)
async def create_or_update_entity(body: EntityCreate):
    """创建或更新一条实体（自动生成 entity_id）"""
    if body.entity_type not in ENTITY_TYPES:
        raise HTTPException(400, f"无效 entity_type，可选值: {sorted(ENTITY_TYPES)}")

    entity_id = generate_entity_id(
        entity_type=body.entity_type,
        name=body.name,
        ts_code=body.ts_code,
        metric_name=body.metric_name,
        event_date=body.event_date,
    )

    from datetime import date
    valid_from = date.fromisoformat(body.valid_from) if body.valid_from else None
    valid_to = date.fromisoformat(body.valid_to) if body.valid_to else None

    # 同步函数，放到线程池执行
    loop = asyncio.get_event_loop()
    entity, is_new = await loop.run_in_executor(
        None,
        lambda: upsert_entity(
            entity_id=entity_id,
            entity_type=body.entity_type,
            name=body.name,
            ts_code=body.ts_code,
            properties=body.properties,
            confidence=body.confidence,
            source_type=body.source_type,
            source_name=body.source_name,
            evidence_url=body.evidence_url,
            valid_from=valid_from,
            valid_to=valid_to,
            parser_version=body.parser_version,
        )
    )
    return EntityResponse.from_orm(entity)


@router.post("/batch", response_model=BatchResult)
async def batch_create_entities(body: EntityBatchCreate):
    """批量创建/更新实体"""
    from datetime import date as _date
    results = []
    for item in body.entities:
        if item.entity_type not in ENTITY_TYPES:
            raise HTTPException(400, f"无效 entity_type: {item.entity_type}")
        entity_id = generate_entity_id(
            entity_type=item.entity_type,
            name=item.name,
            ts_code=item.ts_code,
            metric_name=item.metric_name,
            event_date=item.event_date,
        )
        valid_from = _date.fromisoformat(item.valid_from) if item.valid_from else None
        valid_to = _date.fromisoformat(item.valid_to) if item.valid_to else None
        results.append(dict(
            entity_id=entity_id,
            entity_type=item.entity_type,
            name=item.name,
            ts_code=item.ts_code,
            properties=item.properties,
            confidence=item.confidence,
            source_type=item.source_type,
            source_name=item.source_name,
            evidence_url=item.evidence_url,
            valid_from=valid_from,
            valid_to=valid_to,
            parser_version=item.parser_version,
        ))

    loop = asyncio.get_event_loop()
    inserted, updated = await loop.run_in_executor(
        None, lambda: batch_upsert_entities(results)
    )
    return BatchResult(inserted=inserted, updated=updated)


@router.get("/by-id/{entity_id}", response_model=EntityResponse)
async def get_entity_by_id(entity_id: str):
    """根据 entity_id 查询实体"""
    loop = asyncio.get_event_loop()
    entity = await loop.run_in_executor(None, lambda: get_entity(entity_id))
    if not entity:
        raise HTTPException(404, f"实体不存在: {entity_id}")
    return EntityResponse.from_orm(entity)


@router.get("", response_model=list[EntityResponse])
async def list_entities(
    entity_type: Optional[str] = Query(None),
    ts_code: Optional[str] = Query(None),
    name_keyword: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """条件查询实体列表"""
    if entity_type and entity_type not in ENTITY_TYPES:
        raise HTTPException(400, f"无效 entity_type，可选值: {sorted(ENTITY_TYPES)}")

    loop = asyncio.get_event_loop()
    entities = await loop.run_in_executor(
        None,
        lambda: query_entities(
            entity_type=entity_type,
            ts_code=ts_code,
            name_keyword=name_keyword,
            limit=limit,
            offset=offset,
        ),
    )
    return [EntityResponse.from_orm(e) for e in entities]
