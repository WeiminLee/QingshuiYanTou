"""
eval_runs 清理脚本

功能：
  - automated_daily 记录 90 天后自动清理（D-05）
  - quarterly_manual 永久保留

用法：
  python scripts/cleanup_eval_runs.py
  python scripts/cleanup_eval_runs.py --dry-run
  python scripts/cleanup_eval_runs.py --days 60
"""

import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import text

from app.core.database import async_session

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

COLLECTION_NAME = "eval_runs"
DEFAULT_DAYS = 90


async def delete_automated_daily_older_than(days: int = DEFAULT_DAYS, dry_run: bool = False) -> int:
    """
    删除 automated_daily 类型超过指定天数的 eval_runs 记录

    Args:
        days: 保留天数（默认 90，D-05）
        dry_run: True=只打印不删除

    Returns:
        删除的记录数
    """
    sql = text(f"""
        DELETE FROM eval_runs
        WHERE run_type = 'automated_daily'
          AND run_at < NOW() - INTERVAL '{days} days'
    """)
    count_sql = text(f"""
        SELECT COUNT(*) FROM eval_runs
        WHERE run_type = 'automated_daily'
          AND run_at < NOW() - INTERVAL '{days} days'
    """)

    async with async_session() as db:
        # 检查表是否存在（eval_runs 可能尚未通过 migration 创建）
        try:
            result = await db.execute(count_sql)
            row = result.fetchone()
            count = row[0] if row else 0
        except Exception as exc:
            if "relation" in str(exc) and "does not exist" in str(exc):
                logger.info("表 eval_runs 尚不存在，跳过清理")
                return 0
            raise

        if dry_run:
            logger.info(f"[DRY-RUN] 将删除 {count} 条 automated_daily 记录（> {days} 天）")
        else:
            await db.execute(sql)
            await db.commit()
            logger.info(f"已删除 {count} 条 automated_daily 记录（> {days} 天）")

    return count


def run_cleanup(days: int = DEFAULT_DAYS, dry_run: bool = False) -> None:
    """同步入口（供 cron 调用）"""
    import asyncio

    try:
        count = asyncio.run(delete_automated_daily_older_than(days=days, dry_run=dry_run))
        if not dry_run:
            logger.info(f"清理完成：删除 {count} 条 | 保留 {days} 天内的 automated_daily 记录")
    except Exception as e:
        logger.exception(f"清理失败: {e}")
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="清理过期 eval_runs 记录")
    parser.add_argument(
        "--days",
        type=int,
        default=DEFAULT_DAYS,
        help=f"保留天数（默认 {DEFAULT_DAYS}）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印，不删除",
    )
    args = parser.parse_args()

    run_cleanup(days=args.days, dry_run=args.dry_run)
