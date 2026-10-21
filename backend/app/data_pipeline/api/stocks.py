"""
股票相关 API

数据来源：本地 PostgreSQL（通过 services 层查询）
已移除云端 API 依赖。
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.models import Stock

router = APIRouter()


# ── 基础数据 ──────────────────────────────────────────


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
            {
                "ts_code": s.ts_code,
                "symbol": s.symbol,
                "name": s.name,
                "industry": s.industry,
                "area": s.area,
            }
            for s in stocks
        ],
    }
