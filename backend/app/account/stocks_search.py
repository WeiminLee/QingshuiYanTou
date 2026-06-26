"""股票搜索：复用现有 stocks 表（来自 Tushare stock_basic 同步）"""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.account.schemas import StockSearchItem
from app.models.models import Stock


async def search(session: AsyncSession, q: str, limit: int = 10) -> list[StockSearchItem]:
    """在 stocks 表里做模糊匹配：ts_code 前缀 OR name 包含 q
    q 为空时按 ts_code 升序返回前 limit 条
    limit 上限 20
    """
    limit = max(1, min(limit, 20))
    q = (q or "").strip()
    stmt = select(Stock)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Stock.name.ilike(like), Stock.ts_code.ilike(f"{q}%")))
    stmt = stmt.order_by(Stock.ts_code).limit(limit)
    result = await session.execute(stmt)
    rows = result.scalars().all()
    return [
        StockSearchItem(
            ts_code=r.ts_code,
            name=r.name or "",
            industry=r.industry,
        )
        for r in rows
    ]
