#!/usr/bin/env python3
"""
sync_main_business_revenue.py — fina_mainbz_vip → main_business_revenue 表

从 tinyshare（兼容 tushare SDK）获取全市场主营业务构成明细，
upsert 写入 PostgreSQL main_business_revenue 表。

用法:
    python -m scripts.sync_main_business_revenue                              # 默认 2024年报
    python -m scripts.sync_main_business_revenue --period 20240630            # 指定报告期
    python -m scripts.sync_main_business_revenue --type D                     # 按地区分类
    python -m scripts.sync_main_business_revenue --dry-run --limit 100        # 试运行
"""

from __future__ import annotations

import argparse
import logging
import sys
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


def fetch_main_business_revenue(
    period: str,
    bz_type: str = "P",
    limit: int | None = None,
) -> pd.DataFrame:
    """从 tinyshare 获取 fina_mainbz_vip（全市场主营业务构成）。

    Args:
        period: 报告期 YYYYMMDD
        bz_type: 分类方式 P=产品 D=地区 I=行业
        limit: 限制行数
    """
    import tinyshare as ts
    from app.config import settings

    ts.set_token(settings.tushare_token)
    pro = ts.pro_api()

    fields = "ts_code,end_date,bz_item,bz_code,bz_sales,bz_profit,bz_cost,curr_type"
    df = pro.fina_mainbz_vip(period=period, type=bz_type, fields=fields)

    if df is None or df.empty:
        logger.warning("tinyshare fina_mainbz_vip 返回空数据")
        return pd.DataFrame()

    logger.info(
        "tinyshare fina_mainbz_vip (period=%s, type=%s): 获取 %d 行",
        period,
        bz_type,
        len(df),
    )

    if limit and limit > 0:
        df = df.head(limit)
        logger.info("  --limit=%d, 截取前 %d 行", limit, len(df))

    return df


# ── upsert 写入 main_business_revenue 表 ───────────────────


def _parse_float(val) -> float | None:
    """将值转为 float，无效值返回 None。"""
    if pd.isna(val) or val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _clean_str(val) -> str | None:
    """清理字符串，空值返回 None。"""
    if pd.isna(val) or val is None:
        return None
    s = str(val).strip()
    return s if s else None


async def upsert_main_business_revenue(
    df: pd.DataFrame, dry_run: bool = False
) -> int:
    """将 DataFrame 写入 main_business_revenue 表（upsert）。"""
    if df.empty:
        return 0

    records = []
    for _, row in df.iterrows():
        ts_code = str(row.get("ts_code", "")).strip()
        if not ts_code:
            continue
        end_date = _clean_str(row.get("end_date"))
        bz_item = _clean_str(row.get("bz_item"))
        bz_code = _clean_str(row.get("bz_code"))
        if not end_date or not bz_item or not bz_code:
            continue
        records.append(
            {
                "ts_code": ts_code,
                "end_date": end_date,
                "bz_item": bz_item,
                "bz_code": bz_code,
                "bz_sales": _parse_float(row.get("bz_sales")),
                "bz_profit": _parse_float(row.get("bz_profit")),
                "bz_cost": _parse_float(row.get("bz_cost")),
                "curr_type": _clean_str(row.get("curr_type")) or "CNY",
            }
        )

    logger.info("待写入 main_business_revenue: %d 行", len(records))

    if dry_run:
        logger.info("[dry-run] 跳过写入")
        return len(records)

    # 批量 upsert
    sql = text("""
        INSERT INTO main_business_revenue (
            ts_code, end_date, bz_item, bz_code,
            bz_sales, bz_profit, bz_cost, curr_type
        ) VALUES (
            :ts_code, to_date(:end_date, 'YYYYMMDD'), :bz_item, :bz_code,
            :bz_sales, :bz_profit, :bz_cost, :curr_type
        )
        ON CONFLICT (ts_code, end_date, bz_item, bz_code) DO UPDATE SET
            bz_sales   = EXCLUDED.bz_sales,
            bz_profit  = EXCLUDED.bz_profit,
            bz_cost    = EXCLUDED.bz_cost,
            curr_type  = EXCLUDED.curr_type
    """)

    total = 0
    batch_size = 1000
    for i in range(0, len(records), batch_size):
        batch = records[i : i + batch_size]
        async with engine.begin() as conn:
            await conn.execute(sql, batch)
        total += len(batch)
        logger.info("  已写入 %d / %d", total, len(records))

    return total


# ── main ────────────────────────────────────────────────────


async def main(
    *,
    period: str = "20241231",
    bz_type: str = "P",
    limit: int | None = None,
    dry_run: bool = False,
) -> int:
    type_label = {"P": "按产品", "D": "按地区", "I": "按行业"}.get(bz_type, bz_type)

    logger.info("=" * 60)
    logger.info("  tinyshare fina_mainbz_vip → main_business_revenue 表")
    logger.info("=" * 60)
    logger.info("  报告期:    %s", period)
    logger.info("  分类方式:  %s (%s)", bz_type, type_label)
    logger.info("  模式:      %s", "dry-run" if dry_run else "正式写入")
    logger.info("")

    # 1. 获取数据
    df = fetch_main_business_revenue(period=period, bz_type=bz_type, limit=limit)
    if df.empty:
        logger.warning("无可写入数据")
        return 0

    # 2. 写入数据库
    written = await upsert_main_business_revenue(df, dry_run=dry_run)

    # 3. 统计
    if not dry_run and written > 0:
        async with engine.connect() as conn:
            r = await conn.execute(
                text("SELECT count(DISTINCT ts_code) FROM main_business_revenue")
            )
            stock_count = r.scalar()
            logger.info("覆盖股票数: %d 只", stock_count)

    logger.info("")
    logger.info("=" * 60)
    logger.info("  完成！main_business_revenue 表写入 %d 行", written)
    if dry_run:
        logger.info("  （dry-run 模式，未实际写入）")
    logger.info("=" * 60)
    return written


if __name__ == "__main__":
    import asyncio

    parser = argparse.ArgumentParser(
        description="同步全市场主营业务构成到 main_business_revenue 表"
    )
    parser.add_argument(
        "--period", default="20241231", help="报告期 YYYYMMDD (默认: 20241231)"
    )
    parser.add_argument(
        "--type", default="P", choices=["P", "D", "I"],
        help="分类方式: P=产品 D=地区 I=行业 (默认: P)",
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="限制行数（测试用）"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="试运行，不写入数据库"
    )
    args = parser.parse_args()

    asyncio.run(
        main(
            period=args.period,
            bz_type=args.type,
            limit=args.limit,
            dry_run=args.dry_run,
        )
    )