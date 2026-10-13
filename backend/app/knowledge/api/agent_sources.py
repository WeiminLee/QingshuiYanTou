# backend/app/knowledge/api/agent_sources.py
"""Agent-facing 源材料 HTTP（get_announcement / get_irm / find_events / get_event_detail）。

薄壳调 data_pipeline services（ReportService / news_service）；参数语义对齐旧
@tool 工具面。结构化优先——不做 markdown 拼装，正文级内容仍走 fetch_evidence。
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from app.data_pipeline.services.news_service import get_event_detail, search_events
from app.data_pipeline.services.report_service import get_report_service
from app.knowledge.api._auth import require_api_key

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/knowledge/sources", tags=["知识 Agent 源材料"])


class AnnouncementRequest(BaseModel):
    ts_code: str | None = Field(default=None, max_length=16)
    keyword: str | None = Field(default=None, max_length=200)
    start_date: str | None = Field(default=None, max_length=8)
    end_date: str | None = Field(default=None, max_length=8)
    page_size: int = Field(default=10, ge=1, le=50)


class IrmRequest(BaseModel):
    ts_code: str | None = Field(default=None, max_length=16)
    keyword: str | None = Field(default=None, max_length=200)
    start_date: str | None = Field(default=None, max_length=8)
    end_date: str | None = Field(default=None, max_length=8)
    page_size: int = Field(default=20, ge=1, le=200)


class EventsRequest(BaseModel):
    query: str | None = Field(default=None, max_length=300)
    tags: list[str] | None = Field(default=None, max_length=10)
    date_from: str | None = Field(default=None, max_length=8)
    date_to: str | None = Field(default=None, max_length=8)
    top_n: int = Field(default=10, ge=1, le=30)


class EventDetailRequest(BaseModel):
    event_id: str = Field(min_length=3, max_length=64)


async def _run(label: str, coro) -> Any:
    try:
        return await coro
    except Exception as exc:  # noqa: BLE001
        logger.exception("agent sources op %s failed", label)
        raise HTTPException(500, f"tool failed: {exc}") from exc


@router.post("/announcement")
async def api_get_announcement(
    req: AnnouncementRequest,
    x_api_key: str | None = Header(default=None),
):
    require_api_key(x_api_key)
    items = await _run(
        "get_announcement",
        get_report_service().search_announcements(
            ts_code=req.ts_code,
            keyword=req.keyword,
            start_date=req.start_date,
            end_date=req.end_date,
            limit=req.page_size,
        ),
    )
    return {"items": items, "count": len(items)}


@router.post("/irm")
async def api_get_irm(
    req: IrmRequest,
    x_api_key: str | None = Header(default=None),
):
    require_api_key(x_api_key)
    items = await _run(
        "get_irm",
        get_report_service().search_irm(
            ts_code=req.ts_code,
            keyword=req.keyword,
            start_date=req.start_date,
            end_date=req.end_date,
            limit=req.page_size,
        ),
    )
    return {"items": items, "count": len(items)}


@router.post("/events")
async def api_find_events(
    req: EventsRequest,
    x_api_key: str | None = Header(default=None),
):
    require_api_key(x_api_key)
    return await _run(
        "find_events",
        search_events(
            query=req.query,
            tags=req.tags,
            date_from=req.date_from,
            date_to=req.date_to,
            top_n=req.top_n,
        ),
    )


@router.post("/event_detail")
async def api_get_event_detail(
    req: EventDetailRequest,
    x_api_key: str | None = Header(default=None),
):
    require_api_key(x_api_key)
    return await _run("get_event_detail", get_event_detail(req.event_id))
