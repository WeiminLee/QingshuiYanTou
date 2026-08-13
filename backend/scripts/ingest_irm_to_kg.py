#!/usr/bin/env python3
"""
IRM 互动易问答 → 知识层证据摄取脚本

从 PostgreSQL announcements 表读取互动易问答（announcement_type LIKE 'irm:%'），
通过 irm_pipeline 构建 evidence 并加入知识层提取队列。

用法：
    uv run python scripts/ingest_irm_to_kg.py                      # 全量
    uv run python scripts/ingest_irm_to_kg.py --limit 5            # 只处理 5 只股票
    uv run python scripts/ingest_irm_to_kg.py --ts-code 000001.SZ  # 单只股票
    uv run python scripts/ingest_irm_to_kg.py --dry-run --limit 5  # 试运行
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# 添加 backend 目录到 path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import text

from app.core.database import engine
from app.data_pipeline.irm_pipeline import process_irm_batch

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("ingest_irm")


async def get_irm_ts_codes(limit: int | None = None) -> list[str]:
    """获取有 IRM 数据的 ts_code 列表。"""
    sql = """
        SELECT DISTINCT ts_code
        FROM announcements
        WHERE announcement_type LIKE 'irm:%'
        ORDER BY ts_code
    """
    async with engine.connect() as conn:
        result = await conn.execute(text(sql))
        codes = [row[0] for row in result.fetchall()]
    if limit:
        codes = codes[:limit]
    logger.info("有 IRM 数据的股票: %d 只%s", len(codes), f" (limit={limit})" if limit else "")
    return codes


async def main():
    parser = argparse.ArgumentParser(description="IRM 互动易问答 → 知识层证据摄取")
    parser.add_argument("--ts-code", type=str, default=None, help="指定个股 ts_code")
    parser.add_argument("--limit", type=int, default=None, help="限制股票数")
    parser.add_argument("--dry-run", action="store_true", help="试运行")
    args = parser.parse_args()

    if args.ts_code:
        ts_codes = [args.ts_code]
        logger.info("指定股票: %s", args.ts_code)
    else:
        ts_codes = await get_irm_ts_codes(limit=args.limit)

    if not ts_codes:
        logger.info("没有需要处理的 IRM 数据")
        return

    if args.dry_run:
        logger.info("=== 试运行模式 ===")
        logger.info("将处理 %d 只股票", len(ts_codes))
        # 统计每只股票的 IRM 记录数
        async with engine.connect() as conn:
            for code in ts_codes:
                result = await conn.execute(
                    text("SELECT count(*) FROM announcements WHERE ts_code = :code AND announcement_type LIKE 'irm:%'"),
                    {"code": code},
                )
                cnt = result.scalar()
                logger.info("  %s: %d 条 IRM 记录", code, cnt)
        logger.info("=== 试运行结束，无实际写入 ===")
        return

    logger.info("开始 IRM 证据摄取: %d 只股票", len(ts_codes))
    result = await process_irm_batch(ts_codes, max_concurrency=4, evidence_first=True)
    logger.info("IRM 证据摄取完成:")
    logger.info("  处理公司: %d", result.get("companies", 0))
    logger.info("  处理记录: %d", result.get("records", 0))
    logger.info("  跳过: %d", result.get("skipped", 0))
    logger.info("  失败: %d", result.get("fail", 0))


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())