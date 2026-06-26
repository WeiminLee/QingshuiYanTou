"""
数据相关 API

数据来源：本地 PostgreSQL（通过 services 层查询）

"""

import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.data_pipeline.services.kline_service import get_kline_service
from app.models.models import DailyData, Stock

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/daily/{ts_code}")
async def get_daily_data(
    ts_code: str,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
):
    """
    获取日线数据（本地 PostgreSQL）。
    """
    from sqlalchemy import and_, select

    if end_date is None:
        end_date = datetime.now().strftime("%Y%m%d")
    if start_date is None:
        start_date = (datetime.now() - timedelta(days=limit + 10)).strftime("%Y%m%d")

    start = datetime.strptime(start_date, "%Y%m%d").date()
    end = datetime.strptime(end_date, "%Y%m%d").date()

    stmt = (
        select(DailyData)
        .where(
            and_(
                DailyData.ts_code == ts_code,
                DailyData.trade_date >= start,
                DailyData.trade_date <= end,
            )
        )
        .order_by(DailyData.trade_date)
        .limit(limit)
    )

    result = await db.execute(stmt)
    data = result.scalars().all()

    return {
        "items": [
            {
                "trade_date": d.trade_date.isoformat() if d.trade_date else None,
                "open": d.open,
                "high": d.high,
                "low": d.low,
                "close": d.close,
                "pre_close": d.pre_close,
                "change": d.change,
                "pct_chg": d.pct_chg,
                "vol": d.vol,
                "amount": d.amount,
                "is_suspended": d.is_suspended,
            }
            for d in data
        ],
        "source": "database",
        "count": len(data),
    }


@router.get("/daily-raw/{ts_code}")
async def get_daily_raw(
    ts_code: str,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 60,
):
    """
    从本地 PostgreSQL 获取日线数据（供 Agent 分析使用）。
    """
    if end_date is None:
        end_date = datetime.now().strftime("%Y%m%d")
    if start_date is None:
        start_date = (datetime.now() - timedelta(days=limit * 2)).strftime("%Y%m%d")

    try:
        service = get_kline_service()
        items = await service.get_stock_kline(
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date,
            frequency="d",
        )
        return {
            "items": items[-limit:] if len(items) > limit else items,
            "total": len(items),
        }
    except Exception as e:
        logger.error(f"本地 K 线获取失败 {ts_code}: {e}")
        return {"items": [], "error": str(e)}


@router.get("/status")
async def get_data_status(db: AsyncSession = Depends(get_db)):
    """获取本地数据状态"""
    from sqlalchemy import func, select

    stmt = select(func.count(Stock.ts_code))
    result = await db.execute(stmt)
    stock_count = result.scalar() or 0

    stmt = select(DailyData.trade_date).order_by(DailyData.trade_date.desc()).limit(1)
    result = await db.execute(stmt)
    latest = result.scalar_one_or_none()

    return {
        "stock_count": stock_count,
        "latest_date": latest.isoformat() if latest else None,
        "data_source": "local",
    }
