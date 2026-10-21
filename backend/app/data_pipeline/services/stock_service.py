"""
StockService - 股票查询服务

从本地 PostgreSQL 查询股票信息，供 Agent 工具调用。
"""

import logging
from typing import Any

from sqlalchemy import text

from app.core.database import async_session

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
            # async_session() 解析隔离 contextvar（工具跨 loop 时为 NullPool
            # 临时 engine），直接用全局 engine 会在工具线程 loop 复用主 loop
            # 连接 → asyncpg 'attached to a different loop'。
            async with async_session() as session:
                result = await session.execute(text(sql), {"ts_code": ts_code})
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


_stock_service: StockService | None = None


def get_stock_service() -> StockService:
    """获取 StockService 单例"""
    global _stock_service
    if _stock_service is None:
        _stock_service = StockService()
    return _stock_service
