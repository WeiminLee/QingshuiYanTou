# backend/app/knowledge/api/agent_sources.py
"""Agent-facing 源材料 HTTP（get_announcement / get_irm / find_events / get_event_detail）。

薄壳调 data_pipeline services（ReportService / news_service）；参数语义对齐旧
@tool 工具面。结构化优先——不做 markdown 拼装，正文级内容仍走 fetch_evidence。
"""
from __future__ import annotations

import logging
import re
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from app.data_pipeline.services.news_service import get_event_detail, list_recent_events, search_events
from app.data_pipeline.services.report_service import get_report_service
from app.knowledge.api._auth import require_api_key

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/knowledge/sources", tags=["知识 Agent 源材料"])


_TS_CODE_RE = re.compile(r"^\d{6}\.[A-Za-z]{2,4}$")


def _coerce_query_date(value: object) -> str | None:
    """Agent 常传 YYYY-MM-DD。查询层只用 YYYYMMDD。公告对不上仍 422。"""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    digits = re.sub(r"\D", "", text)
    if len(digits) < 8 or not digits[:8].isdigit():
        raise ValueError("日期用 YYYYMMDD 或 YYYY-MM-DD")
    compact = digits[:8]
    month, day = int(compact[4:6]), int(compact[6:8])
    if month < 1 or month > 12 or day < 1 or day > 31:
        raise ValueError("日期用 YYYYMMDD 或 YYYY-MM-DD")
    return compact


class AnnouncementRequest(BaseModel):
    ts_code: str | None = Field(default=None, max_length=16)
    keyword: str | None = Field(default=None, max_length=200)
    start_date: str | None = Field(default=None, max_length=32)
    end_date: str | None = Field(default=None, max_length=32)
    page_size: int = Field(default=10, ge=1, le=50)

    @field_validator("start_date", "end_date", mode="before")
    @classmethod
    def _dates(cls, value: object) -> str | None:
        return _coerce_query_date(value)


def _blank_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _irm_date(value: Any, name: str) -> tuple[str | None, str | None]:
    if _blank_text(value) is None:
        return None, None
    try:
        return _coerce_query_date(value), None
    except ValueError:
        shown = str(value).strip()[:40]
        return None, f"{name}「{shown}」无法识别，已忽略。日期用 YYYYMMDD 或 YYYY-MM-DD"


def _irm_page_size(value: Any) -> tuple[int, str | None]:
    if _blank_text(value) is None:
        return 20, None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 20, f"page_size「{str(value)[:20]}」无法识别，已按 20 条返回"
    if number < 1:
        return 1, "page_size 小于 1，已按 1 条返回"
    if number > 200:
        return 200, "page_size 超过 200，已按 200 条返回"
    return number, None


def irm_query_from_body(raw: Any) -> tuple[dict[str, Any], str | None]:
    """参数有问题就丢掉有问题的那一项，照常查询，并把说明带回。"""
    notes: list[str] = []
    if not isinstance(raw, dict):
        raw = {}
        notes.append("请求体不是对象，已按不带筛选的条件查询")
    ts_code = _blank_text(raw.get("ts_code"))
    keyword = _blank_text(raw.get("keyword"))
    if ts_code and not _TS_CODE_RE.match(ts_code):
        if keyword is None:
            keyword = ts_code[:200]
            notes.append(f"ts_code「{ts_code[:32]}」不是证券代码，已改按关键词查询")
        else:
            notes.append(f"ts_code「{ts_code[:32]}」不是证券代码，已忽略")
        ts_code = None
    elif ts_code:
        code, suffix = ts_code.split(".", 1)
        ts_code = f"{code}.{suffix.upper()}"
    if keyword and len(keyword) > 200:
        keyword = keyword[:200]
        notes.append("keyword 超过 200 字，已截断")
    start_date, start_note = _irm_date(raw.get("start_date"), "start_date")
    end_date, end_note = _irm_date(raw.get("end_date"), "end_date")
    if start_note:
        notes.append(start_note)
    if end_note:
        notes.append(end_note)
    page_size, page_note = _irm_page_size(raw.get("page_size", 20))
    if page_note:
        notes.append(page_note)
    params = {
        "ts_code": ts_code,
        "keyword": keyword,
        "start_date": start_date,
        "end_date": end_date,
        "limit": page_size,
    }
    return params, ("；".join(notes) or None)


class EventsRequest(BaseModel):
    query: str | None = Field(default=None, max_length=300)
    tags: list[str] | None = Field(default=None, max_length=10)
    date_from: str | None = Field(default=None, max_length=10)
    date_to: str | None = Field(default=None, max_length=10)
    top_n: int = Field(default=10, ge=1, le=30)


class RecentEventsRequest(BaseModel):
    limit: int = Field(default=20, ge=1, le=30)


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
    request: Request,
    x_api_key: str | None = Header(default=None),
):
    """参数不合法时不返回 422：忽略该项并在 note 里说明，其余条件照常查询。"""
    require_api_key(x_api_key)
    raw: Any = {}
    body = await request.body()
    if body:
        try:
            raw = await request.json()
        except Exception:
            raw = None
    params, note = irm_query_from_body(raw)
    items = await _run("get_irm", get_report_service().search_irm(**params))
    payload: dict[str, Any] = {"items": items, "count": len(items)}
    if note:
        payload["note"] = note
    return payload


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


@router.post("/events/recent")
async def api_list_recent_events(
    req: RecentEventsRequest,
    x_api_key: str | None = Header(default=None),
):
    require_api_key(x_api_key)
    return await _run("list_recent_events", list_recent_events(req.limit))


@router.post("/event_detail")
async def api_get_event_detail(
    req: EventDetailRequest,
    x_api_key: str | None = Header(default=None),
):
    require_api_key(x_api_key)
    return await _run("get_event_detail", get_event_detail(req.event_id))
