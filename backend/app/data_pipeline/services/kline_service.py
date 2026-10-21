"""
KlineService - K线查询服务

从本地 PostgreSQL 查询 K线数据，供 Agent 工具调用。
支持日线/周线/月线聚合。
"""

import logging
from collections import OrderedDict
from datetime import date
from typing import Any

from sqlalchemy import text

from app.core.database import engine

logger = logging.getLogger(__name__)


def _parse_yyyymmdd(value: str) -> date | None:
    """YYYYMMDD → date，无效输入返回 None（asyncpg 的 Date 列不接受字符串参数）"""
    if not value or len(value) < 8 or not value[:8].isdigit():
        return None
    try:
        return date(int(value[:4]), int(value[4:6]), int(value[6:8]))
    except ValueError:
        return None


def _compute_period_pct_chg(
    first_row: dict[str, Any],
    last_row: dict[str, Any],
) -> float:
    """计算聚合周期的涨跌幅。

    使用 period 首条记录的 pre_close 作为基准，末条记录的 close 作为当前值。
    若 pre_close 不可用，回退到首条 open。

    Returns:
        涨跌幅百分比，基准不可用时返回 0。
    """
    base = first_row.get("pre_close") or first_row.get("open", 0)
    close = last_row.get("close", 0)
    if base and base > 0:
        return round((close - base) / base * 100, 2)
    return 0.0


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
            "pct_chg": _compute_period_pct_chg(first, last),
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
            d.pre_close,
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
                    "pre_close": row[6] or 0,
                    "volume": row[7] or 0,
                    "amount": row[8] or 0,
                    "pct_chg": row[9] or 0,
                    "turnover_rate": row[10] or 0,
                }
                for row in rows
            ]

            if frequency == "d":
                return daily_rows

            return _aggregate_kline_rows(daily_rows, frequency)

        except Exception as e:
            logger.warning(f"查询K线失败 {ts_code}: {e}")
            return []


    async def get_market_snapshot(self, trade_date: str = "") -> dict[str, Any]:
        """某一交易日的涨跌家数、两市成交额和主要指数收盘。"""
        raw = trade_date.replace("-", "") if trade_date else ""
        day = _parse_yyyymmdd(raw) if raw else None
        async with engine.connect() as conn:
            if day is None:
                row = (
                    await conn.execute(
                        text(
                            """
                            SELECT MAX(d.trade_date)
                            FROM daily_data d
                            JOIN stocks s ON s.ts_code = d.ts_code
                            WHERE s.name NOT LIKE '%指数%'
                            """
                        )
                    )
                ).fetchone()
                day = row[0] if row else None
            if day is None:
                return shape_market_snapshot("", 0, 0, 0, None, [])
            breadth = (
                await conn.execute(
                    text(
                        """
                        SELECT
                            COUNT(*) FILTER (WHERE d.pct_chg > 0),
                            COUNT(*) FILTER (WHERE d.pct_chg < 0),
                            COUNT(*) FILTER (WHERE d.pct_chg = 0 OR d.pct_chg IS NULL),
                            SUM(d.amount)
                        FROM daily_data d
                        JOIN stocks s ON s.ts_code = d.ts_code
                        WHERE d.trade_date = :day
                          AND s.name NOT LIKE '%指数%'
                        """
                    ),
                    {"day": day},
                )
            ).fetchone()
            index_rows = (
                await conn.execute(
                    text(
                        """
                        SELECT d.ts_code, s.name, d.close, d.pct_chg, d.amount
                        FROM daily_data d
                        JOIN stocks s ON s.ts_code = d.ts_code
                        WHERE d.trade_date = :day
                          AND d.ts_code = ANY(:codes)
                        ORDER BY d.ts_code
                        """
                    ),
                    {"day": day, "codes": list(SNAPSHOT_INDEX_CODES)},
                )
            ).fetchall()
        up, down, flat, amount = breadth if breadth else (0, 0, 0, None)
        indices = [
            {
                "ts_code": row[0],
                "name": row[1],
                "close": row[2],
                "pct_chg": row[3],
                "amount": row[4],
            }
            for row in index_rows
        ]
        return shape_market_snapshot(
            day.strftime("%Y%m%d"),
            int(up or 0),
            int(down or 0),
            int(flat or 0),
            None if amount is None else float(amount),
            indices,
        )


_kline_service: KlineService | None = None


# daily_data.amount 单位是千元；1 亿元 = 100000 千元。
AMOUNT_QIANYUAN_PER_YI = 100_000
SNAPSHOT_INDEX_CODES: tuple[str, ...] = (
    "000001.SH",
    "399001.SZ",
    "399006.SZ",
    "000300.SH",
    "000016.SH",
    "000905.SH",
    "000852.SH",
    "000688.SH",  # 科创50，主页面「科创板」
    "899050.BJ",  # 北证50，主页面「北交所」
)


def shape_market_snapshot(
    trade_date: str,
    up: int,
    down: int,
    flat: int,
    amount_qianyuan: float | None,
    indices: list[dict[str, Any]],
) -> dict[str, Any]:
    """涨跌家数与两市成交额。成交额是个股 amount 合计，已排除名称含「指数」的行。"""
    amount_yi = None
    if amount_qianyuan is not None:
        amount_yi = round(float(amount_qianyuan) / AMOUNT_QIANYUAN_PER_YI, 2)
    return {
        "trade_date": trade_date,
        "up": up,
        "down": down,
        "flat": flat,
        "amount_qianyuan": amount_qianyuan,
        "amount_yi": amount_yi,
        "amount_note": "两市个股成交额合计（daily_data.amount 为千元，amount_yi 为亿元），不含指数行。",
        "indices": indices,
    }


def get_kline_service() -> KlineService:
    """获取 KlineService 单例"""
    global _kline_service
    if _kline_service is None:
        _kline_service = KlineService()
    return _kline_service
