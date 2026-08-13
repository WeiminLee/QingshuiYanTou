from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.readiness.schemas import ReadinessSource, ReadinessSummary
from app.readiness.service import DataReadinessService

router = APIRouter(tags=["数据可用性"])


@router.get("", response_model=ReadinessSummary)
async def get_readiness_summary() -> ReadinessSummary:
    return await DataReadinessService().get_all()


@router.get("/{source}", response_model=ReadinessSource)
async def get_readiness_source(source: str) -> ReadinessSource:
    item = await DataReadinessService().get_source(source)
    if item is None:
        raise HTTPException(status_code=404, detail=f"unknown readiness source: {source}")
    return item
