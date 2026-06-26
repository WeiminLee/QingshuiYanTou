"""
StockService - 股票查询服务

从本地 PostgreSQL 查询股票信息，供 Agent 工具调用。
"""

import logging
from typing import Any

from sqlalchemy import text

from app.core.database import engine

logger = logging.getLogger(__name__)


class StockService:
    """股票查询服务"""

    async def get_stock_profile(self, ts_code: str) -> dict[str, Any]:
        """
        从 PostgreSQL 查询股票概况

        Args:
            ts_code: 股票代码，如 300308.SZ

        Returns:
            股票概况数据
        """
        sql = """
        SELECT
            ts_code,
            main_business,
            business_scope
        FROM company_profiles
        WHERE ts_code = :ts_code
        """

        try:
            async with engine.connect() as conn:
                result = await conn.execute(text(sql), {"ts_code": ts_code})
                row = result.fetchone()

            if row is None:
                return {}

            return {
                "ts_code": row[0],
                "main_business": row[1] or "",
                "business_scope": row[2] or "",
            }
        except Exception as e:
            logger.warning(f"查询股票概况失败 {ts_code}: {e}")
            return {}

    async def search_stocks(
        self,
        keyword: str | None = None,
        industry: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """
        搜索股票列表

        Args:
            keyword: 关键词（匹配名称或代码）
            industry: 行业筛选
            limit: 返回数量限制

        Returns:
            股票列表
        """
        sql = "SELECT ts_code, name, industry FROM stocks WHERE 1=1"
        params: dict[str, Any] = {}

        if keyword:
            sql += " AND (name LIKE :keyword OR ts_code LIKE :keyword)"
            params["keyword"] = f"%{keyword}%"
        if industry:
            sql += " AND industry = :industry"
            params["industry"] = industry

        sql += " ORDER BY ts_code LIMIT :limit"
        params["limit"] = limit

        try:
            async with engine.connect() as conn:
                result = await conn.execute(text(sql), params)
                rows = result.fetchall()

            return [{"ts_code": row[0], "name": row[1], "industry": row[2]} for row in rows]
        except Exception as e:
            logger.warning(f"搜索股票失败: {e}")
            return []


# 全局单例
_stock_service: StockService | None = None


def get_stock_service() -> StockService:
    """获取 StockService 单例"""
    global _stock_service
    if _stock_service is None:
        _stock_service = StockService()
    return _stock_service
