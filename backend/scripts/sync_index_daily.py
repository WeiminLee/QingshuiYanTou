"""主要指数日线：tinyshare（mintree 网关）→ daily_data。

不调用 tushare 官方接口。minishare 的授权码没有指数日线，所以用 tinyshare。
个股任务的 pro.daily 对指数代码会空返回，所以这里单独拉指数。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import text

from app.core.database import engine
from scripts.sync_daily_tushare import (
    _batch_insert,
    _get_tinyshare_api,
    _wait_for_tinyshare_slot,
)

logger = logging.getLogger(__name__)

# stocks.ts_code 外键已有这些指数；get_kline 读的是 daily_data，不是 index_daily。
INDEX_TS_CODES: tuple[str, ...] = (
    "000001.SH",  # 上证综合指数
    "399001.SZ",  # 深证成份指数
    "399006.SZ",  # 创业板指数
    "000300.SH",  # 沪深300
    "000016.SH",  # 上证50
    "000905.SH",  # 中证500
    "000852.SH",  # 中证1000
    "000688.SH",  # 科创50
    "899050.BJ",  # 北证50
)
DEFAULT_INDEX_START = "20260801"


def index_fetch_outcome(start: str, end: str, row_count: int) -> str:
    """交易日区间空返回是失败；纯周末空返回是正常。有行则成功。"""
    if row_count > 0:
        return "ok"
    start_day = datetime.strptime(start, "%Y%m%d").date()
    end_day = datetime.strptime(end, "%Y%m%d").date()
    cursor = start_day
    while cursor <= end_day:
        if cursor.weekday() < 5:
            return "fail"
        cursor += timedelta(days=1)
    return "ok"


def next_index_start(max_trade_date: date | None, default: str = DEFAULT_INDEX_START) -> str:
    """已有最大交易日的次日；没有行则从 default（YYYYMMDD）起。"""
    if max_trade_date is None:
        return default
    return (max_trade_date + timedelta(days=1)).strftime("%Y%m%d")


def _num(value: Any) -> float:
    if value is None or value == "":
        return 0.0
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if number != number:
        return 0.0
    return number


def rows_from_index_frame(ts_code: str, frame_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """index_daily 行 → daily_data 插入记录。成交量为 0 视为停牌。"""
    records: list[dict[str, Any]] = []
    for row in frame_rows:
        vol = _num(row.get("vol"))
        records.append(
            {
                "ts_code": ts_code,
                "trade_date": datetime.strptime(str(row["trade_date"]), "%Y%m%d").date(),
                "open": _num(row.get("open")),
                "high": _num(row.get("high")),
                "low": _num(row.get("low")),
                "close": _num(row.get("close")),
                "pre_close": _num(row.get("pre_close")),
                "change": _num(row.get("change")),
                "pct_chg": _num(row.get("pct_chg")),
                "vol": vol,
                "amount": _num(row.get("amount")),
                "is_suspended": vol == 0,
            }
        )
    return records


def _fetch_index_rows(ts_code: str, start_date: str, end_date: str) -> list[dict[str, Any]]:
    df = _get_tinyshare_api().index_daily(
        ts_code=ts_code,
        start_date=start_date,
        end_date=end_date,
    )
    if df is None or getattr(df, "empty", True):
        return []
    return df.to_dict("records")


async def _fetch_index_rows_with_retry(ts_code: str, start_date: str, end_date: str) -> list[dict[str, Any]]:
    for attempt in range(1, 4):
        await _wait_for_tinyshare_slot()
        try:
            return await asyncio.to_thread(_fetch_index_rows, ts_code, start_date, end_date)
        except Exception as exc:
            if "429" not in str(exc) or attempt == 3:
                raise
            await asyncio.sleep(2**attempt)
    raise RuntimeError("index_daily retry exhausted")


async def _max_trade_date(ts_code: str) -> date | None:
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text("SELECT MAX(trade_date) FROM daily_data WHERE ts_code = :ts"),
                {"ts": ts_code},
            )
        ).fetchone()
    return row[0] if row else None


async def _listed_codes(codes: tuple[str, ...]) -> set[str]:
    """daily_data.ts_code 外键指向 stocks。不在股票表里的指数不能写入。"""
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text("SELECT ts_code FROM stocks WHERE ts_code = ANY(:codes)"),
                {"codes": list(codes)},
            )
        ).fetchall()
    return {row[0] for row in rows}


async def sync_indices(
    codes: tuple[str, ...] = INDEX_TS_CODES,
    *,
    end_date: str | None = None,
) -> dict[str, Any]:
    """把主要指数从各自 daily_data 最大日期的次日补到 end_date。"""
    end = end_date or date.today().strftime("%Y%m%d")
    saved = 0
    ok = 0
    failed: list[str] = []
    listed = await _listed_codes(codes)
    for ts_code in codes:
        if ts_code not in listed:
            logger.info("index_daily %s skipped: not in stocks", ts_code)
            ok += 1
            continue
        start = next_index_start(await _max_trade_date(ts_code))
        if start > end:
            ok += 1
            continue
        try:
            frame_rows = await _fetch_index_rows_with_retry(ts_code, start, end)
        except Exception as exc:
            logger.warning("index_daily %s failed: %s", ts_code, exc)
            failed.append(ts_code)
            continue
        records = rows_from_index_frame(ts_code, frame_rows)
        if index_fetch_outcome(start, end, len(records)) == "fail":
            logger.warning("index_daily %s returned no rows for %s-%s", ts_code, start, end)
            failed.append(ts_code)
            continue
        if records:
            saved += await _batch_insert(records)
        ok += 1
    return {"ok": ok, "fail": len(failed), "saved": saved, "failed": failed, "total": len(codes)}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    result = asyncio.run(sync_indices())
    print(result)


if __name__ == "__main__":
    main()
