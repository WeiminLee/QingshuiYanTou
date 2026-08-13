"""
备选池维护脚本 (candidate_pool)

用法:
  # 从 watchlist 导入
  python scripts/sync_candidate_pool.py --from-watchlist

  # 从 stock_scores 按评分阈值筛选
  python scripts/sync_candidate_pool.py --from-scores --min-total-score 70

  # 手动添加股票
  python scripts/sync_candidate_pool.py --add 000001.SZ,000002.SZ --reason "测试"

  # 手动移除股票
  python scripts/sync_candidate_pool.py --remove 000001.SZ,000003.SZ

  # 查看当前备选池
  python scripts/sync_candidate_pool.py --list

  # 清空并重新初始化（从watchlist + 评分筛选）
  python scripts/sync_candidate_pool.py --rebuild
"""

import argparse
import sys
import os
from datetime import datetime

# 确保能从项目根目录 import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from app.core.database import async_session
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s %(message)s")
logger = logging.getLogger("sync_candidate_pool")


async def from_watchlist(session):
    """从 watchlist 导入到备选池"""
    result = await session.execute(
        text("""
            INSERT INTO candidate_pool (ts_code, name, source, reason)
            SELECT w.ts_code, w.name, 'watchlist', '从自选股导入'
            FROM watchlist w
            WHERE NOT EXISTS (
                SELECT 1 FROM candidate_pool cp WHERE cp.ts_code = w.ts_code
            )
            ON CONFLICT (ts_code) DO NOTHING
            RETURNING ts_code, name
        """)
    )
    rows = result.fetchall()
    await session.commit()
    logger.info("从 watchlist 导入 %d 只股票到备选池", len(rows))
    for r in rows:
        logger.info("  + %s %s", r.ts_code, r.name)
    return len(rows)


async def from_scores(session, min_total_score: float):
    """从 stock_scores 按评分阈值筛选最近一个交易日的数据"""
    result = await session.execute(
        text("""
            INSERT INTO candidate_pool (ts_code, name, source, reason)
            SELECT s.ts_code, s.name, 'score', '评分筛选: total_score >= ' || :min_score::text
            FROM stock_scores s
            WHERE s.trade_date = (
                SELECT MAX(trade_date) FROM stock_scores
            )
            AND s.total_score >= :min_score
            AND NOT EXISTS (
                SELECT 1 FROM candidate_pool cp WHERE cp.ts_code = s.ts_code
            )
            ON CONFLICT (ts_code) DO NOTHING
            RETURNING ts_code, name, total_score
        """),
        {"min_score": min_total_score},
    )
    rows = result.fetchall()
    await session.commit()
    logger.info(
        "从 stock_scores(>=%.1f) 导入 %d 只股票到备选池",
        min_total_score,
        len(rows),
    )
    for r in rows:
        logger.info("  + %s %s (score=%.1f)", r.ts_code, r.name, r[2] if len(r) > 2 else "?")
    return len(rows)


async def add_manual(session, ts_codes: list[str], reason: str | None):
    """手动添加股票到备选池"""
    for code in ts_codes:
        # 先查 stocks 表确认存在
        stock = await session.execute(
            text("SELECT ts_code, name FROM stocks WHERE ts_code = :code"),
            {"code": code},
        )
        row = stock.fetchone()
        if not row:
            logger.warning("股票 %s 不存在于 stocks 表，跳过", code)
            continue

        await session.execute(
            text("""
                INSERT INTO candidate_pool (ts_code, name, source, reason)
                VALUES (:code, :name, 'manual', :reason)
                ON CONFLICT (ts_code) DO UPDATE SET
                    source = 'manual',
                    reason = :reason,
                    is_active = TRUE,
                    updated_at = now()
            """),
            {"code": row.ts_code, "name": row.name, "reason": reason or "手动添加"},
        )
        logger.info("  + %s %s", row.ts_code, row.name)

    await session.commit()


async def remove(session, ts_codes: list[str]):
    """从备选池移除股票（硬删除）"""
    result = await session.execute(
        text("DELETE FROM candidate_pool WHERE ts_code = ANY(:codes) RETURNING ts_code, name"),
        {"codes": ts_codes},
    )
    rows = result.fetchall()
    await session.commit()
    logger.info("从备选池移除 %d 只股票", len(rows))
    for r in rows:
        logger.info("  - %s %s", r.ts_code, r.name)


async def list_pool(session):
    """列出当前备选池"""
    result = await session.execute(
        text("""
            SELECT cp.ts_code, cp.name, cp.source, cp.reason, cp.is_active, cp.added_at
            FROM candidate_pool cp
            ORDER BY cp.added_at DESC
        """)
    )
    rows = result.fetchall()
    if not rows:
        logger.info("备选池为空")
        return

    logger.info("备选池共 %d 只股票:", len(rows))
    logger.info("%-12s %-10s %-12s %-30s %s", "代码", "名称", "来源", "理由", "激活")
    logger.info("-" * 70)
    for r in rows:
        active = "✓" if r.is_active else "✗"
        logger.info("%-12s %-10s %-12s %-30s %s", r.ts_code, r.name or "", r.source, r.reason or "", active)


async def rebuild(session, min_total_score: float = 70):
    """清空备选池，从 watchlist 和评分筛选重新构建"""
    # 清空
    await session.execute(text("DELETE FROM candidate_pool"))
    await session.commit()
    logger.info("备选池已清空")

    # 从 watchlist 导入
    wl_count = await from_watchlist(session)

    # 从评分筛选
    sc_count = await from_scores(session, min_total_score)

    logger.info("备选池重建完成，共 %d 只股票（watchlist: %d, scores: %d）", wl_count + sc_count, wl_count, sc_count)


async def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description="备选池维护脚本")
    parser.add_argument("--from-watchlist", action="store_true", help="从 watchlist 导入")
    parser.add_argument("--from-scores", action="store_true", help="从 stock_scores 按评分筛选")
    parser.add_argument("--min-total-score", type=float, default=70.0, help="评分筛选阈值 (默认 70)")
    parser.add_argument("--add", type=str, help="手动添加股票，逗号分隔")
    parser.add_argument("--remove", type=str, help="移除股票，逗号分隔")
    parser.add_argument("--reason", type=str, default=None, help="添加理由")
    parser.add_argument("--list", action="store_true", help="列出备选池")
    parser.add_argument("--rebuild", action="store_true", help="清空并重新构建")

    args = parser.parse_args(argv)

    async with async_session() as session:
        if args.rebuild:
            await rebuild(session, args.min_total_score)
        elif args.from_watchlist:
            await from_watchlist(session)
        elif args.from_scores:
            await from_scores(session, args.min_total_score)
        elif args.add:
            ts_codes = [c.strip() for c in args.add.split(",") if c.strip()]
            await add_manual(session, ts_codes, args.reason)
        elif args.remove:
            ts_codes = [c.strip() for c in args.remove.split(",") if c.strip()]
            await remove(session, ts_codes)
        elif args.list:
            await list_pool(session)
        else:
            # 默认：列出备选池
            await list_pool(session)


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
