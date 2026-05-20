"""
股票相关 API

数据来源：本地 PostgreSQL（通过 services 层查询）
已移除云端 API 依赖。
"""
import logging
from fastapi import APIRouter, Depends, Body, HTTPException, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, func, desc

from typing import Optional
from app.core.database import get_db
from app.models.models import Stock, Watchlist, DailyData, AnalysisReport
from app.data_pipeline.services.kline_service import get_kline_service
from app.packages.stock_package import (
    build_stock_package as _build_stock_package,
    build_stock_package_json as _build_stock_package_json,
)
from app.packages.material_package import build_material_package as _build_material_package

router = APIRouter()
logger = logging.getLogger(__name__)


# ── 基础数据 ──────────────────────────────────────────

@router.get("/list")
async def get_stock_list(
    limit: int = 100,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    """获取股票列表（本地 PostgreSQL）"""
    stmt = select(Stock).limit(limit).offset(offset)
    result = await db.execute(stmt)
    stocks = result.scalars().all()
    return {
        "total": limit,
        "items": [
            {"ts_code": s.ts_code, "symbol": s.symbol, "name": s.name,
             "industry": s.industry, "area": s.area}
            for s in stocks
        ],
    }


@router.get("/search")
async def search_stocks(
    q: str = Query(..., min_length=1),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """搜索股票（按代码或名称模糊搜索）"""
    keyword = f"%{q}%"
    stmt = (
        select(Stock)
        .where(
            or_(
                Stock.ts_code.ilike(keyword),
                Stock.name.ilike(keyword),
                Stock.symbol.ilike(keyword),
            )
        )
        .limit(limit)
    )
    result = await db.execute(stmt)
    stocks = result.scalars().all()
    return {
        "items": [
            {"ts_code": s.ts_code, "symbol": s.symbol, "name": s.name,
             "industry": s.industry, "area": s.area}
            for s in stocks
        ],
    }


# ── 自选股 ──────────────────────────────────────────

@router.get("/watchlist")
async def get_watchlist(db: AsyncSession = Depends(get_db)):
    """获取自选股列表（含最新价格 + 最新分析评分）"""
    # 子查询：每只股票最新一条日线数据
    daily_subq = (
        select(
            DailyData.ts_code,
            DailyData.close,
            DailyData.pct_chg,
            func.row_number().over(
                partition_by=DailyData.ts_code,
                order_by=desc(DailyData.trade_date),
            ).label("rn"),
        ).subquery()
    )
    latest_price = (
        select(daily_subq.c.ts_code, daily_subq.c.close, daily_subq.c.pct_chg)
        .where(daily_subq.c.rn == 1)
        .subquery()
    )

    # 子查询：每只股票最新一条分析报告
    report_subq = (
        select(
            AnalysisReport.ts_code,
            AnalysisReport.score,
            func.row_number().over(
                partition_by=AnalysisReport.ts_code,
                order_by=desc(AnalysisReport.created_at),
            ).label("rn"),
        ).subquery()
    )
    latest_report = (
        select(report_subq.c.ts_code, report_subq.c.score)
        .where(report_subq.c.rn == 1)
        .subquery()
    )

    stmt = (
        select(Stock, Watchlist, latest_price.c.close, latest_price.c.pct_chg, latest_report.c.score)
        .join(Watchlist, Stock.ts_code == Watchlist.ts_code)
        .outerjoin(latest_price, Stock.ts_code == latest_price.c.ts_code)
        .outerjoin(latest_report, Stock.ts_code == latest_report.c.ts_code)
        .order_by(desc(Watchlist.added_at))
    )
    result = await db.execute(stmt)
    rows = result.all()

    return {
        "items": [
            {
                "ts_code": stock.ts_code,
                "symbol": stock.symbol,
                "name": stock.name,
                "industry": stock.industry,
                "added_at": watchlist.added_at.isoformat() if watchlist.added_at else None,
                "note": watchlist.note,
                "latest_price": float(price) if price is not None else None,
                "latest_pct_chg": float(pct_chg) if pct_chg is not None else None,
                "score": score,
            }
            for stock, watchlist, price, pct_chg, score in rows
        ],
    }


@router.post("/watchlist")
async def add_to_watchlist(body: dict = Body(...), db: AsyncSession = Depends(get_db)):
    """添加到自选股"""
    ts_code: str = body.get("ts_code", "")
    note: str = body.get("note", "") or ""

    if not ts_code:
        raise HTTPException(status_code=400, detail="ts_code 不能为空")

    stmt = select(Stock).where(Stock.ts_code == ts_code)
    result = await db.execute(stmt)
    stock = result.scalar_one_or_none()
    if not stock:
        raise HTTPException(status_code=404, detail="股票不存在")

    stmt = select(Watchlist).where(Watchlist.ts_code == ts_code)
    result = await db.execute(stmt)
    existing = result.scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=400, detail="股票已在自选股中")

    db.add(Watchlist(ts_code=ts_code, note=note))
    await db.commit()
    return {"detail": "添加成功", "ts_code": ts_code}


@router.delete("/watchlist/{ts_code}")
async def remove_from_watchlist(ts_code: str, db: AsyncSession = Depends(get_db)):
    """从自选股移除"""
    stmt = select(Watchlist).where(Watchlist.ts_code == ts_code)
    result = await db.execute(stmt)
    watchlist = result.scalar_one_or_none()
    if not watchlist:
        raise HTTPException(status_code=404, detail="股票不在自选股中")
    await db.delete(watchlist)
    await db.commit()
    return {"message": "移除成功"}


# ── 情报包（JSON）—— 必须在 /{ts_code} 之前 ─────────────

@router.get("/package/{ts_code}")
async def get_stock_package_json(ts_code: str):
    """
    获取股票基础情报包（JSON 格式）
    """
    return await _build_stock_package_json(ts_code)


# ── 情报包接口（Markdown 文本格式）─────────────────────────────

@router.get("/package/{ts_code}/markdown", response_class=PlainTextResponse)
async def get_stock_package_markdown(ts_code: str):
    """
    获取股票基础情报包（Markdown 文本）
    """
    return await _build_stock_package(ts_code)


@router.get("/material/{ts_code}/markdown", response_class=PlainTextResponse)
async def get_material_package_markdown(ts_code: str):
    """
    获取股票公开材料包（Markdown 文本）
    """
    return await _build_material_package(ts_code)


@router.get("/kline")
async def get_stock_kline(
    ts_code: str = Query(..., description="股票代码，如 000001.SZ"),
    limit: int = Query(60, ge=10, le=120, description="返回最近N个交易日"),
    period: str = Query("D", description="周期，D=日线"),
):
    """
    返回个股日线 K 线数据（本地 PostgreSQL）。
    用于 StockDetailPanel K 线图。
    """
    try:
        service = get_kline_service()
        rows = await service.get_stock_kline(
            ts_code=ts_code,
            start_date="",  # 默认获取最近数据
            end_date="",
            frequency="d",
        )
        periods = [
            {
                "date": item.get("trade_date", ""),
                "open": item.get("open", 0),
                "high": item.get("high", 0),
                "low": item.get("low", 0),
                "close": item.get("close", 0),
                "vol": item.get("volume", 0),
                "pct_chg": item.get("pct_chg", 0),
            }
            for item in rows[-limit:]
        ]
        return {"ts_code": ts_code, "periods": periods}
    except Exception as e:
        logger.error(f"[stocks/kline] failed for {ts_code}: {e}")
        raise HTTPException(status_code=500, detail=f"获取K线数据失败: {str(e)}")


@router.get("/capital-flow")
async def get_capital_flow(
    period: str = Query("D", description="周期，D=日/W=周/M=月"),
    limit: int = Query(20, ge=5, le=50, description="节点数量"),
):
    """
    资金流向数据（已废弃）。
    返回空数据结构，前端 Dashboard 桑基图降级展示。
    """
    return {"nodes": [], "links": [], "period": period, "deprecated": True}


# ── 个股详情 ──────────────────────────────────────────
# 注意：必须在所有特定路径路由之后

@router.get("/{ts_code}")
async def get_stock(ts_code: str, db: AsyncSession = Depends(get_db)):
    """获取股票详情"""
    stmt = select(Stock).where(Stock.ts_code == ts_code)
    result = await db.execute(stmt)
    stock = result.scalar_one_or_none()
    if not stock:
        raise HTTPException(status_code=404, detail="股票不存在")
    return {
        "ts_code": stock.ts_code,
        "symbol": stock.symbol,
        "name": stock.name,
        "industry": stock.industry,
        "area": stock.area,
        "market": stock.market,
        "list_date": stock.list_date,
    }
