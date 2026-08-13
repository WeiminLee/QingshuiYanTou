#!/usr/bin/env python3
"""
sync_company_profile.py — tinyshare stock_company → company_profiles 表

从 tinyshare（兼容 tushare SDK）获取全量 A 股公司概况数据，
upsert 写入 PostgreSQL company_profiles 表。

用法:
    python -m scripts.sync_company_profile
    python -m scripts.sync_company_profile --limit 100     # 仅测试前 100 条
    python -m scripts.sync_company_profile --dry-run       # 仅打印，不写入
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


def fetch_company_profiles(limit: int | None = None) -> pd.DataFrame:
    """从 tinyshare 获取 stock_company（全量 A 股公司概况）。

    分别获取 SSE（上交所）和 SZSE（深交所）数据，合并后去重。
    """
    import tinyshare as ts
    from app.config import settings

    ts.set_token(settings.tushare_token)
    pro = ts.pro_api()

    fields = (
        "ts_code,com_name,chairman,manager,secretary,reg_capital,"
        "setup_date,province,city,introduction,website,email,office,"
        "business_scope,employees,main_business,exchange"
    )

    # 分别获取两个交易所数据
    dfs: list[pd.DataFrame] = []
    for exchange in ("SSE", "SZSE"):
        df = pro.stock_company(exchange=exchange, fields=fields)
        if df is not None and not df.empty:
            dfs.append(df)
            logger.info("tinyshare stock_company (%s): 获取 %d 条", exchange, len(df))

    if not dfs:
        logger.warning("tinyshare 返回空数据")
        return pd.DataFrame()

    df = pd.concat(dfs, ignore_index=True)
    # 按 ts_code 去重（后出现的覆盖前面的）
    df = df.drop_duplicates(subset="ts_code", keep="last")
    df = df.reset_index(drop=True)

    logger.info("合并后总量: %d 条（去重后）", len(df))

    if limit and limit > 0:
        df = df.head(limit)
        logger.info("  --limit=%d, 截取前 %d 条", limit, len(df))

    return df


# ── upsert 写入 company_profiles 表 ────────────────────────


def _parse_int(val) -> int | None:
    """将值转为 int，无效值返回 None。"""
    if pd.isna(val) or val is None:
        return None
    try:
        return int(float(str(val).strip()))
    except (ValueError, TypeError):
        return None


def _clean_str(val) -> str | None:
    """清理字符串，空值返回 None。"""
    if pd.isna(val) or val is None:
        return None
    s = str(val).strip()
    return s if s else None


async def upsert_company_profiles(df: pd.DataFrame, dry_run: bool = False) -> int:
    """将 DataFrame 写入 company_profiles 表（upsert）。"""
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
                "com_name": _clean_str(row.get("com_name")),
                "com_id": None,
                "chairman": _clean_str(row.get("chairman")),
                "manager": _clean_str(row.get("manager")),
                "secretary": _clean_str(row.get("secretary")),
                "reg_capital": _clean_str(row.get("reg_capital")),
                "setup_date": _clean_str(row.get("setup_date")),
                "province": _clean_str(row.get("province")),
                "city": _clean_str(row.get("city")),
                "introduction": _clean_str(row.get("introduction")),
                "website": _clean_str(row.get("website")),
                "email": _clean_str(row.get("email")),
                "office": _clean_str(row.get("office")),
                "business_scope": _clean_str(row.get("business_scope")),
                "employees": _parse_int(row.get("employees")),
                "main_business": _clean_str(row.get("main_business")),
                "exchange": _clean_str(row.get("exchange")),
            }
        )

    logger.info("待写入 company_profiles: %d 条", len(records))

    if dry_run:
        logger.info("[dry-run] 跳过写入")
        return len(records)

    # 批量 upsert
    sql = text("""
        INSERT INTO company_profiles (
            ts_code, com_name, com_id, chairman, manager, secretary,
            reg_capital, setup_date, province, city, introduction,
            website, email, office, business_scope, employees,
            main_business, exchange
        ) VALUES (
            :ts_code, :com_name, :com_id, :chairman, :manager, :secretary,
            :reg_capital, :setup_date, :province, :city, :introduction,
            :website, :email, :office, :business_scope, :employees,
            :main_business, :exchange
        )
        ON CONFLICT (ts_code) DO UPDATE SET
            com_name       = EXCLUDED.com_name,
            chairman       = EXCLUDED.chairman,
            manager        = EXCLUDED.manager,
            secretary      = EXCLUDED.secretary,
            reg_capital    = EXCLUDED.reg_capital,
            setup_date     = EXCLUDED.setup_date,
            province       = EXCLUDED.province,
            city           = EXCLUDED.city,
            introduction   = EXCLUDED.introduction,
            website        = EXCLUDED.website,
            email          = EXCLUDED.email,
            office         = EXCLUDED.office,
            business_scope = EXCLUDED.business_scope,
            employees      = EXCLUDED.employees,
            main_business  = EXCLUDED.main_business,
            exchange       = EXCLUDED.exchange,
            updated_at     = now()
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


async def main(*, limit: int | None = None, dry_run: bool = False) -> int:
    logger.info("=" * 60)
    logger.info("  tinyshare stock_company → company_profiles 表")
    logger.info("=" * 60)
    logger.info("  模式: %s", "dry-run" if dry_run else "正式写入")
    logger.info("")

    # 1. 获取数据
    df = fetch_company_profiles(limit=limit)
    if df.empty:
        logger.warning("无可写入数据")
        return 0

    # 2. 写入数据库
    written = await upsert_company_profiles(df, dry_run=dry_run)

    # 3. 统计非空字段
    if not dry_run and written > 0:
        async with engine.connect() as conn:
            fields = [
                "main_business", "website", "employees", "chairman",
                "manager", "province", "city", "introduction", "email",
            ]
            stats = []
            for f in fields:
                r = await conn.execute(
                    text(f"SELECT count(*) FROM company_profiles WHERE {f} IS NOT NULL")
                )
                cnt = r.scalar()
                stats.append(f"    {f}: {cnt}/{written}")
            logger.info("字段覆盖统计:")
            for s in stats:
                logger.info(s)

    logger.info("")
    logger.info("=" * 60)
    logger.info("  完成！company_profiles 表写入 %d 条", written)
    if dry_run:
        logger.info("  （dry-run 模式，未实际写入）")
    logger.info("=" * 60)
    return written


if __name__ == "__main__":
    import asyncio

    parser = argparse.ArgumentParser(description="同步 A 股公司概况到 company_profiles 表")
    parser.add_argument("--limit", type=int, default=None, help="限制获取条数（测试用）")
    parser.add_argument("--dry-run", action="store_true", help="试运行，不写入数据库")
    args = parser.parse_args()

    asyncio.run(main(limit=args.limit, dry_run=args.dry_run))