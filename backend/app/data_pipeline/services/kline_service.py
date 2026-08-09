"""
KlineService - K线查询服务

从本地 PostgreSQL 查询 K线数据，供 Agent 工具调用。
支持日线/周线/月线聚合。
"""

import logging
from collections import OrderedDict
from typing import Any

from sqlalchemy import text

from app.core.database import engine

logger = logging.getLogger(__name__)


def _parse_yyyymmdd(value: str) -> str | None:
    """YYYYMMDD → YYYY-MM-DD，无效输入返回 None"""
    if not value or len(value) < 8 or not value[:8].isdigit():
        return None
    return f"{value[:4]}-{value[4:6]}-{value[6:8]}"


def _aggregate_kline_rows(
    rows: list[dict[str, Any]],
    frequency: str,
) -> list[dict[str, Any]]:
    """将日线 rows 按 frequency 聚合为周线或月线。

    Args:
        rows: 日线记录列表（已按 trade_date 升序）
        frequency: "w" 或 "m"

    Returns:
        聚合后的记录列表，按 period 起始日期升序。
    """
    if not rows:
        return []

    # 分组
    groups: OrderedDict[str, list[dict[str, Any]]] = OrderedDict()
    for row in rows:
        trade_date_str = row.get("trade_date", "")
        try:
            dt = __import__("datetime").datetime.strptime(trade_date_str, "%Y%m%d").date()
        except (ValueError, TypeError):
            continue

        if frequency == "w":
            iso = dt.isocalendar()
            key = f"{iso[0]}-W{iso[1]:02d}"
        elif frequency == "m":
            key = dt.strftime("%Y-%m")
        else:
            continue

        if key not in groups:
            groups[key] = []
        groups[key].append(row)

    # 聚合每个组
    result: list[dict[str, Any]] = []
    for group_key, group_rows in groups.items():
        first = group_rows[0]
        last = group_rows[-1]
        trade_date = first.get("trade_date", "")

        aggregated = {
            "ts_code": first.get("ts_code", ""),
            "trade_date": trade_date,
            "open": first.get("open", 0),
            "high": max(r.get("high", 0) for r in group_rows),
            "low": min(r.get("low", 0) for r in group_rows),
            "close": last.get("close", 0),
            "volume": sum(r.get("volume", 0) for r in group_rows),
            "amount": sum(r.get("amount", 0) for r in group_rows),
            "pct_chg": first.get("pct_chg", 0),
            "turnover_rate": first.get("turnover_rate"),
        }
        result.append(aggregated)

    return result


class KlineService:
    """K线查询服务"""

    async def get_stock_kline(
        self,
        ts_code: str,
        start_date: str,
        end_date: str,
        frequency: str = "d",
    ) -> list[dict[str, Any]]:
        """
        从 PostgreSQL 查询个股K线数据，支持日线/周线/月线聚合。

        Args:
            ts_code: 股票代码，如 300308.SZ
            start_date: 开始日期 YYYYMMDD
            end_date: 结束日期 YYYYMMDD
            frequency: d=日线 w=周线 m=月线

        Returns:
            K线数据列表，按日期升序
        """
        if frequency not in {"d", "w", "m"}:
            logger.warning("不支持的 K 线频率: %s", frequency)
            return []

        start_parsed = _parse_yyyymmdd(start_date)
        end_parsed = _parse_yyyymmdd(end_date)

        sql = """
        SELECT
            d.ts_code,
            d.trade_date,
            d.open,
            d.high,
            d.low,
            d.close,
            d.vol,
            d.amount,
            d.pct_chg,
            db.turnover_rate
        FROM daily_data d
        LEFT JOIN daily_basic db
            ON db.ts_code = d.ts_code AND db.trade_date = d.trade_date
        WHERE d.ts_code = :ts_code
        """

        params: dict[str, Any] = {"ts_code": ts_code}
        if start_parsed:
            sql += " AND d.trade_date >= :start_date"
            params["start_date"] = start_parsed
        if end_parsed:
            sql += " AND d.trade_date <= :end_date"
            params["end_date"] = end_parsed

        sql += " ORDER BY d.trade_date ASC"

        try:
            async with engine.connect() as conn:
                result = await conn.execute(text(sql), params)
                rows = result.fetchall()

            daily_rows = [
                {
                    "ts_code": row[0],
                    "trade_date": row[1].strftime("%Y%m%d") if row[1] else "",
                    "open": row[2] or 0,
                    "high": row[3] or 0,
                    "low": row[4] or 0,
                    "close": row[5] or 0,
                    "volume": row[6] or 0,
                    "amount": row[7] or 0,
                    "pct_chg": row[8] or 0,
                    "turnover_rate": row[9] or 0,
                }
                for row in rows
            ]

            if frequency == "d":
                return daily_rows

            return _aggregate_kline_rows(daily_rows, frequency)

        except Exception as e:
            logger.warning(f"查询K线失败 {ts_code}: {e}")
            return []

    async def get_index_kline(
        self,
        index_codes: list[str],
        start_date: str,
        end_date: str,
    ) -> dict[str, list[dict[str, Any]]]:
        """
        从 PostgreSQL 查询指数K线数据

        Args:
            index_codes: 指数代码列表，如 ["sh.000001", "sz.399001"]
            start_date: 开始日期 YYYYMMDD
            end_date: 结束日期 YYYYMMDD

        Returns:
            {index_code: [kline_items]}
        """
        if not index_codes:
            return {}

        start_parsed = _parse_yyyymmdd(start_date)
        end_parsed = _parse_yyyymmdd(end_date)
        if not start_parsed or not end_parsed:
            return {code: [] for code in index_codes}

        sql = """
        SELECT
            ts_code, trade_date,
            open, high, low, close,
            vol, amount, pct_chg
        FROM index_daily
        WHERE ts_code = ANY(:index_codes)
          AND trade_date >= :start_date
          AND trade_date <= :end_date
        ORDER BY ts_code, trade_date ASC
        """

        result_map: dict[str, list[dict[str, Any]]] = {code: [] for code in index_codes}

        try:
            async with engine.connect() as conn:
                result = await conn.execute(
                    text(sql),
                    {
                        "index_codes": index_codes,
                        "start_date": start_parsed,
                        "end_date": end_parsed,
                    },
                )
                rows = result.fetchall()

            for row in rows:
                code = row[0]
                if code in result_map:
                    result_map[code].append(
                        {
                            "ts_code": code,
                            "trade_date": row[1].strftime("%Y%m%d") if row[1] else "",
                            "open": row[2] or 0,
                            "high": row[3] or 0,
                            "low": row[4] or 0,
                            "close": row[5] or 0,
                            "volume": row[6] or 0,
                            "amount": row[7] or 0,
                            "pct_chg": row[8] or 0,
                        }
                    )
        except Exception as e:
            logger.warning(f"查询指数K线失败: {e}")

        return result_map


_kline_service: KlineService | None = None


def get_kline_service() -> KlineService:
    """获取 KlineService 单例"""
    global _kline_service
    if _kline_service is None:
        _kline_service = KlineService()
    return _kline_service
