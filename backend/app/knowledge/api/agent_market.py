"""Agent-facing market read HTTP (get_kline / get_stock_profile).

Calls data_pipeline services — no LangChain @tool wrappers.
"""
from __future__ import annotations

import datetime as _dt
import logging
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

from app.data_pipeline.services.kline_service import get_kline_service
from app.data_pipeline.services.stock_service import get_stock_service
from app.knowledge.api._auth import require_api_key

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/knowledge/market", tags=["知识 Agent 行情"])


def _default_date_range(start_date: str, end_date: str) -> tuple[str, str]:
    if not end_date:
        end_date = _dt.datetime.now().strftime("%Y%m%d")
    if not start_date:
        end = _dt.datetime.strptime(end_date, "%Y%m%d")
        start_date = (end - _dt.timedelta(days=180)).strftime("%Y%m%d")
    return start_date, end_date


def _format_kline_text(ts_code: str, start: str, end: str, freq: str, rows: list[dict[str, Any]]) -> str:
    if not rows:
        return f"未找到 {ts_code} 在 {start}-{end} 的 K 线数据。"
    first, last = rows[0], rows[-1]
    return (
        f"{ts_code} {freq}K {start}-{end} 共 {len(rows)} 条；"
        f"首收 {first.get('close')}（{first.get('trade_date')}），"
        f"末收 {last.get('close')}（{last.get('trade_date')}）。"
    )


def _format_profile_text(ts_code: str, data: dict[str, Any]) -> str:
    if not data or not data.get("main_business"):
        return f"未找到股票 {ts_code} 的概况信息。"
    lines = [f"## {ts_code} 股票概况", f"- **主营业务**：{data.get('main_business', '')}"]
    if data.get("business_scope"):
        lines.append(f"- **经营范围**：{data['business_scope']}")
    return "\n".join(lines)


@router.get("/kline")
async def api_get_kline(
    ts_code: str = Query(min_length=1, max_length=32),
    start_date: str = Query(default=""),
    end_date: str = Query(default=""),
    freq: str = Query(default="D"),
    x_api_key: str | None = Header(default=None),
):
    require_api_key(x_api_key)
    start_date, end_date = _default_date_range(start_date, end_date)
    frequency = {"D": "d", "W": "w", "M": "m"}.get(freq.upper(), "d")
    try:
        rows = await get_kline_service().get_stock_kline(ts_code, start_date, end_date, frequency)
    except Exception as exc:  # noqa: BLE001
        logger.exception("get_kline failed")
        raise HTTPException(500, f"tool failed: {exc}") from exc
    return {
        "ts_code": ts_code,
        "start_date": start_date,
        "end_date": end_date,
        "freq": freq.upper(),
        "count": len(rows),
        "items": rows,
        "text": _format_kline_text(ts_code, start_date, end_date, freq.upper(), rows),
    }


@router.get("/stock_profile")
async def api_get_stock_profile(
    ts_code: str = Query(min_length=1, max_length=32),
    x_api_key: str | None = Header(default=None),
):
    require_api_key(x_api_key)
    try:
        data = await get_stock_service().get_stock_profile(ts_code)
    except Exception as exc:  # noqa: BLE001
        logger.exception("get_stock_profile failed")
        raise HTTPException(500, f"tool failed: {exc}") from exc
    payload = {
        "ts_code": ts_code,
        "main_business": (data or {}).get("main_business", ""),
        "business_scope": (data or {}).get("business_scope", ""),
        "text": _format_profile_text(ts_code, data or {}),
    }
    return payload


class ConceptTopRequest(BaseModel):
    days: int = Field(default=5, ge=2, le=20)
    top_n: int = Field(default=10, ge=1, le=30)


@router.post("/concept_top")
async def api_concept_top(
    req: ConceptTopRequest,
    x_api_key: str | None = Header(default=None),
):
    """最近 N 个交易日最强概念（指数衰减 + 涨停加成；concept_limit 表）。"""
    from app.core.database import async_session
    from app.knowledge.api import concept as concept_api

    require_api_key(x_api_key)
    days, top_n = req.days, req.top_n
    async with async_session() as db:
        return await concept_api.get_top_concepts(days=days, top_n=top_n, db=db)


class ConceptStocksRequest(BaseModel):
    concept_code: str = Field(min_length=1, max_length=64)
    sort_by: str = Field(default="volume", max_length=16)
    limit: int = Field(default=30, ge=1, le=100)


@router.post("/concept_stocks")
async def api_concept_stocks(
    req: ConceptStocksRequest,
    x_api_key: str | None = Header(default=None),
):
    """概念成分股（支持 TI 代码或概念名，如 885806.TI / CPO）。"""
    from app.core.database import async_session
    from app.knowledge.api import concept as concept_api

    require_api_key(x_api_key)
    sort_by = req.sort_by if req.sort_by in ("volume", "turnover", "pct_chg") else "volume"
    async with async_session() as db:
        return await concept_api.get_concept_stocks(req.concept_code, sort_by=sort_by, limit=req.limit, db=db)


class StockConceptsRequest(BaseModel):
    ts_code: str = Field(min_length=1, max_length=32)


@router.post("/stock_concepts")
async def api_stock_concepts(
    req: StockConceptsRequest,
    x_api_key: str | None = Header(default=None),
):
    """个股所属概念清单（ths_concept_members）。"""
    from app.core.database import async_session
    from app.knowledge.api import concept as concept_api

    require_api_key(x_api_key)
    async with async_session() as db:
        return await concept_api.get_stock_concepts(req.ts_code, db=db)
