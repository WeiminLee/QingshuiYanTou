"""
MarketService - 市场宽度查询服务

从本地 PostgreSQL 查询市场宽度数据，供 Agent 工具调用。
"""

import logging
from typing import Any

from sqlalchemy import case, func, select

from app.core.database import engine
from app.models.models import DailyData

logger = logging.getLogger(__name__)


class MarketService:
    """市场宽度查询服务"""

    async def get_market_breadth(self, market: str = "A股") -> dict[str, Any]:
        """
        从 PostgreSQL 查询市场宽度数据

        Args:
            market: 市场类型 A股/SZ/SH

        Returns:
            市场宽度数据
        """
        date_stmt = select(func.max(DailyData.trade_date))
        try:
            async with engine.connect() as conn:
                date_result = await conn.execute(date_stmt)
                latest_date = date_result.scalar_one_or_none()
        except Exception as e:
            logger.warning(f"查询最新交易日失败: {e}")
            return {}

        if not latest_date:
            return {}

        if market == "SZ":
            ts_codes_filter = "sz."
        elif market == "SH":
            ts_codes_filter = "sh."
        else:
            ts_codes_filter = None

        def _count_if(cond):
            return func.coalesce(func.sum(case((cond, 1), else_=0)), 0)

        breadth_stmt = select(
            func.count(DailyData.id).label("total"),
            _count_if(DailyData.pct_chg > 0).label("advance"),
            _count_if(DailyData.pct_chg < 0).label("decline"),
            _count_if(DailyData.pct_chg == 0).label("unchanged"),
            _count_if(DailyData.pct_chg >= 9.9).label("limit_up"),
            _count_if(DailyData.pct_chg <= -9.9).label("limit_down"),
        ).where(DailyData.trade_date == latest_date)

        if ts_codes_filter:
            breadth_stmt = breadth_stmt.where(DailyData.ts_code.like(f"{ts_codes_filter}%"))

        try:
            async with engine.connect() as conn:
                result = await conn.execute(breadth_stmt)
                row = result.fetchone()
        except Exception as e:
            logger.warning(f"查询市场宽度失败: {e}")
            return {}

        if not row:
            return {}

        total = row[0] or 0
        advance = row[1] or 0
        decline = row[2] or 0
        unchanged = row[3] or 0
        limit_up = row[4] or 0
        limit_down = row[5] or 0

        return {
            "trade_date": latest_date.strftime("%Y-%m-%d"),
            "total": total,
            "advance_count": advance,
            "decline_count": decline,
            "unchanged_count": unchanged,
            "limit_up_count": limit_up,
            "limit_down_count": limit_down,
            "breadth_pct": round(advance / total * 100, 2) if total > 0 else 0,
        }


_market_service: MarketService | None = None


def get_market_service() -> MarketService:
    """获取 MarketService 单例"""
    global _market_service
    if _market_service is None:
        _market_service = MarketService()
    return _market_service
