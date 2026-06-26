#!/usr/bin/env python3
"""
全量同步股票基础信息到stocks表（使用akshare数据源）
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import logging
from datetime import date as date_type

import akshare as ak
import pandas as pd
from sqlalchemy import text

from app.core.database import engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger(__name__)


def _parse_date(val) -> date_type | None:
    """安全解析日期"""
    if val is None or val == "":
        return None
    try:
        if pd.isna(val):
            return None
        dt = pd.to_datetime(val)
        return dt.date()
    except Exception:
        return None


async def sync_stock_basic():
    logger.info("开始同步全量A股股票基础信息...")

    all_stocks = []

    # 1. 沪市主板
    logger.info("获取沪市主板...")
    sh_df = ak.stock_info_sh_name_code(symbol="主板A股")
    logger.info(f"沪市主板: {len(sh_df)} 只")
    for _, row in sh_df.iterrows():
        stock_name = row.get("证券简称") or row.get("证券名称", "")
        all_stocks.append(
            {
                "ts_code": f"{row['证券代码']}.SH",
                "symbol": row["证券代码"],
                "name": stock_name,
                "area": row.get("省份", ""),
                "industry": row.get("所属行业", ""),
                "market": "沪市",
                "list_date": _parse_date(row["上市日期"]),
                "is_hs": "",
            }
        )

    # 2. 科创板（沪市）
    logger.info("获取科创板...")
    sh_kcb_df = ak.stock_info_sh_name_code(symbol="科创板")
    logger.info(f"沪市科创板: {len(sh_kcb_df)} 只")
    for _, row in sh_kcb_df.iterrows():
        stock_name = row.get("证券简称") or row.get("证券名称", "")
        all_stocks.append(
            {
                "ts_code": f"{row['证券代码']}.SH",
                "symbol": row["证券代码"],
                "name": stock_name,
                "area": row.get("省份", ""),
                "industry": row.get("所属行业", ""),
                "market": "沪市",
                "list_date": _parse_date(row["上市日期"]),
                "is_hs": "",
            }
        )

    # 3. 深市A股
    logger.info("获取深市A股...")
    sz_df = ak.stock_info_sz_name_code(symbol="A股列表")
    logger.info(f"深市A股: {len(sz_df)} 只")
    for _, row in sz_df.iterrows():
        all_stocks.append(
            {
                "ts_code": f"{row['A股代码']}.SZ",
                "symbol": row["A股代码"],
                "name": row["A股简称"],
                "area": "",
                "industry": row.get("所属行业", ""),
                "market": "深市",
                "list_date": _parse_date(row.get("A股上市日期")),
                "is_hs": "",
            }
        )

    # 4. 北证A股 (跳过 - 接口不稳定)
    # try:
    #     logger.info("获取北证A股...")
    #     bj_df = ak.stock_info_bj_name_code()
    #     logger.info(f"北证A股: {len(bj_df)} 只")
    #     for _, row in bj_df.iterrows():
    #         all_stocks.append({
    #             "ts_code": f"{row['证券代码']}.BJ",
    #             "symbol": row['证券代码'],
    #             "name": row['证券简称'],
    #             "area": "",
    #             "industry": row.get('行业分类', ''),
    #             "market": "北证",
    #             "list_date": _parse_date(row['上市日期']),
    #             "is_hs": '',
    #         })
    # except Exception as e:
    #     logger.warning(f"北证获取失败: {e}")

    if not all_stocks:
        logger.error("没有获取到任何股票数据，退出")
        return

    logger.info(f"合计获取到 {len(all_stocks)} 只A股股票，开始入库...")

    # 5. 批量插入数据库
    async with engine.begin() as conn:
        # 先清空旧数据
        await conn.execute(text("TRUNCATE TABLE stocks RESTART IDENTITY CASCADE"))
        logger.info("已清空旧数据")

        # 批量插入
        await conn.execute(
            text("""
                INSERT INTO stocks (ts_code, symbol, name, area, industry, market, list_date, is_hs)
                VALUES (:ts_code, :symbol, :name, :area, :industry, :market, :list_date, :is_hs)
            """),
            all_stocks,
        )
        logger.info("✅ 插入完成!")

    # 验证结果
    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT COUNT(*) FROM stocks"))
        total = result.scalar()
        result = await conn.execute(text("SELECT market, COUNT(*) FROM stocks GROUP BY market ORDER BY market"))

        logger.info("📊 股票基础信息同步完成!")
        logger.info(f"  总股票数: {total} 只")
        for row in result.fetchall():
            logger.info(f"    * {row[0]}: {row[1]} 只")


if __name__ == "__main__":
    asyncio.run(sync_stock_basic())
