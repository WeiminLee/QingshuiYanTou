#!/usr/bin/env python3
"""
sync_stock_basic.py — tinyshare stock_basic → stocks 表

从 tinyshare（兼容 tushare SDK）获取全量 A 股基本信息，
upsert 写入 PostgreSQL stocks 表。

用法:
    python -m scripts.sync_stock_basic
    python -m scripts.sync_stock_basic --limit 100     # 仅测试前 100 条
    python -m scripts.sync_stock_basic --dry-run       # 仅打印，不写入
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date as date_type
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
from sqlalchemy import text

from app.core.database import engine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ── 数据获取 ────────────────────────────────────────────────


def fetch_stock_basic(limit: int | None = None) -> pd.DataFrame:
    """从 tinyshare 获取 stock_basic（全量 A 股）。"""
    import tinyshare as ts
    from app.config import settings

    ts.set_token(settings.tushare_token)
    pro = ts.pro_api()

    fields = "ts_code,symbol,name,area,industry,market,list_date,is_hs"
    df = pro.query("stock_basic", exchange="", list_status="L", fields=fields)

    if df is None or df.empty:
        logger.warning("tinyshare 返回空数据")
        return pd.DataFrame()

    logger.info("tinyshare stock_basic: 获取 %d 条", len(df))

    if limit and limit > 0:
        df = df.head(limit)
        logger.info("  --limit=%d, 截取前 %d 条", limit, len(df))

    return df


# ── upsert 写入 stocks 表 ──────────────────────────────────


def _parse_date(val) -> date_type | None:
    """将 YYYYMMDD 字符串转 date，无效值返回 None。"""
    if pd.isna(val) or not val:
        return None
    s = str(val).strip()[:8]
    if not s.isdigit() or len(s) != 8:
        return None
    try:
        return date_type(int(s[:4]), int(s[4:6]), int(s[6:8]))
    except (ValueError, IndexError):
        return None


async def upsert_stocks(df: pd.DataFrame, dry_run: bool = False) -> int:
    """将 DataFrame 写入 stocks 表（upsert）。"""
    if df.empty:
        return 0

    records = []
    for _, row in df.iterrows():
        ts_code = str(row.get("ts_code", "")).strip()
        if not ts_code:
            continue
        records.append(
            {
                "ts_code": ts_code,
                "symbol": str(row.get("symbol", "")).strip(),
                "name": str(row.get("name", "")).strip(),
                "area": str(row.get("area", "")).strip() or None,
                "industry": str(row.get("industry", "")).strip() or None,
                "market": str(row.get("market", "")).strip() or None,
                "list_date": _parse_date(row.get("list_date")),
                "is_hs": str(row.get("is_hs", "")).strip()[:1] or None,
            }
        )

    logger.info("待写入 stocks: %d 条", len(records))

    if dry_run:
        logger.info("[dry-run] 跳过写入")
        return len(records)

    # 批量 upsert
    sql = text("""
        INSERT INTO stocks (ts_code, symbol, name, area, industry, market, list_date, is_hs)
        VALUES (:ts_code, :symbol, :name, :area, :industry, :market, :list_date, :is_hs)
        ON CONFLICT (ts_code) DO UPDATE SET
            symbol     = EXCLUDED.symbol,
            name       = EXCLUDED.name,
            area       = EXCLUDED.area,
            industry   = EXCLUDED.industry,
            market     = EXCLUDED.market,
            list_date  = EXCLUDED.list_date,
            is_hs      = EXCLUDED.is_hs
    """)

    total = 0
    batch_size = 1000
    for i in range(0, len(records), batch_size):
        batch = records[i : i + batch_size]
        async with engine.begin() as conn:
            result = await conn.execute(sql, batch)
            total += result.rowcount or 0
        done = min(i + batch_size, len(records))
        logger.info("  已写入 %d / %d", done, len(records))

    return total


# ── main ────────────────────────────────────────────────────


async def main(*, limit: int | None = None, dry_run: bool = False) -> int:
    logger.info("=" * 60)
    logger.info("  tinyshare stock_basic → stocks 表")
    logger.info("=" * 60)
    logger.info("  模式: %s", "dry-run" if dry_run else "正式写入")
    logger.info("")

    # 1. 获取数据
    df = fetch_stock_basic(limit=limit)
    if df.empty:
        logger.warning("无可写入数据")
        return 0

    # 2. 写入数据库
    written = await upsert_stocks(df, dry_run=dry_run)

    logger.info("")
    logger.info("=" * 60)
    logger.info("  完成！stocks 表写入 %d 条", written)
    if dry_run:
        logger.info("  （dry-run 模式，未实际写入）")
    logger.info("=" * 60)
    return written


if __name__ == "__main__":
    import asyncio

    parser = argparse.ArgumentParser(description="同步 A 股基本信息到 stocks 表")
    parser.add_argument("--limit", type=int, default=None, help="限制获取条数（测试用）")
    parser.add_argument("--dry-run", action="store_true", help="试运行，不写入数据库")
    args = parser.parse_args()

    asyncio.run(main(limit=args.limit, dry_run=args.dry_run))