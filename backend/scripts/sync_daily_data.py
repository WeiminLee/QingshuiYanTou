#!/usr/bin/env python3
"""
全量同步A股日线行情数据（从2023-01-01至今）
数据源：akshare新浪财经接口
"""

import asyncio
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import akshare as ak
import pandas as pd
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

sys.path.insert(0, str(Path(__file__).parent.parent))
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.core.database import async_session
from app.data_pipeline.backfill_config import load_backfill_settings

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# 配置参数
# START_DATE / END_DATE 现已由 app.data_pipeline.backfill_config 提供
CONCURRENCY = 3  # 并发请求数（降低以避免限流）
RETRY_TIMES = 5  # 失败重试次数
BATCH_SIZE = 100  # 批量入库大小

# 进度文件，记录已完成的股票
PROGRESS_FILE = Path(__file__).parent / ".daily_sync_progress"
if not PROGRESS_FILE.exists():
    PROGRESS_FILE.touch()


def load_completed_stocks() -> set:
    """加载已完成的股票列表"""
    with open(PROGRESS_FILE, encoding="utf-8") as f:
        return set(line.strip() for line in f if line.strip())


def save_completed_stock(ts_code: str):
    """保存已完成的股票"""
    with open(PROGRESS_FILE, "a", encoding="utf-8") as f:
        f.write(f"{ts_code}\n")


@retry(
    stop=stop_after_attempt(RETRY_TIMES),
    wait=wait_exponential(multiplier=2, min=5, max=30),
    retry=retry_if_exception_type((Exception,)),
    before_sleep=lambda s: logger.warning(
        f"请求失败，第{s.attempt_number}次重试，等待 {5 * (2 ** (s.attempt_number - 1))} 秒: {s.fn.__name__}"
    ),
)
def get_stock_daily(ts_code: str, start_date: str, end_date: str) -> list[dict[str, Any]]:
    """
    获取单只股票的日线数据
    :param ts_code: 带后缀的股票代码，比如600519.SH
    :param start_date: 起始日期，格式YYYYMMDD
    :param end_date: 结束日期，格式YYYYMMDD
    :return: 适配后的日线数据列表
    """
    # 提取股票代码，去掉后缀
    symbol = ts_code.split(".")[0]
    # 获取数据
    df = ak.stock_zh_a_hist(
        symbol=symbol,
        period="daily",
        start_date=start_date,
        end_date=end_date,
        adjust="",  # 不复权
    )
    if df.empty:
        return []

    # 字段适配
    data = []
    for _, row in df.iterrows():
        # 转换日期
        trade_date = datetime.strptime(str(row["日期"]), "%Y-%m-%d").date()
        # 计算前收盘价：收盘价 - 涨跌额
        pre_close = row["收盘"] - row["涨跌额"] if pd.notna(row["涨跌额"]) else row["收盘"]
        # 判断是否停牌：成交量为0则停牌
        is_suspended = row["成交量"] == 0

        data.append(
            {
                "ts_code": ts_code,
                "trade_date": trade_date,
                "open": row["开盘"] if pd.notna(row["开盘"]) else 0,
                "high": row["最高"] if pd.notna(row["最高"]) else 0,
                "low": row["最低"] if pd.notna(row["最低"]) else 0,
                "close": row["收盘"] if pd.notna(row["收盘"]) else 0,
                "pre_close": pre_close,
                "change": row["涨跌额"] if pd.notna(row["涨跌额"]) else 0,
                "pct_chg": row["涨跌幅"] if pd.notna(row["涨跌幅"]) else 0,
                "vol": row["成交量"] if pd.notna(row["成交量"]) else 0,
                "amount": row["成交额"] if pd.notna(row["成交额"]) else 0,
                "is_suspended": is_suspended,
            }
        )
    return data


async def save_batch(session: AsyncSession, data: list[dict[str, Any]]):
    """批量保存日线数据"""
    if not data:
        return
    # 批量插入，冲突则跳过（根据ts_code和trade_date唯一约束）
    await session.execute(
        text("""
            INSERT INTO daily_data (
                ts_code, trade_date, open, high, low, close, pre_close,
                change, pct_chg, vol, amount, is_suspended
            ) VALUES (
                :ts_code, :trade_date, :open, :high, :low, :close, :pre_close,
                :change, :pct_chg, :vol, :amount, :is_suspended
            ) ON CONFLICT (ts_code, trade_date) DO NOTHING
        """),
        data,
    )
    await session.commit()


async def sync_single_stock(semaphore: asyncio.Semaphore, ts_code: str, start_date: str, end_date: str):
    """同步单只股票的日线数据"""
    async with semaphore:
        try:
            # 调用同步接口（同步函数用线程池执行）
            loop = asyncio.get_running_loop()
            data = await loop.run_in_executor(None, get_stock_daily, ts_code, start_date, end_date)
            if not data:
                logger.debug(f"{ts_code} 无数据，跳过")
                save_completed_stock(ts_code)
                return 0

            # 批量入库
            async with async_session() as sess:
                for i in range(0, len(data), BATCH_SIZE):
                    batch = data[i : i + BATCH_SIZE]
                    await save_batch(sess, batch)

            save_completed_stock(ts_code)
            logger.info(f"✅ {ts_code} 同步完成，共 {len(data)} 条记录")
            return len(data)
        except Exception as e:
            logger.error(f"❌ {ts_code} 同步失败: {str(e)}", exc_info=True)
            return 0


async def main(argv: list[str] | None = None):
    import argparse
    import os

    parser = argparse.ArgumentParser(description="A股日线行情同步 (akshare 新浪)")
    parser.add_argument("--scope", choices=["tech_mvp", "all"], default=None)
    parser.add_argument("--start-date", default=None)
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.scope:
        os.environ["BACKFILL_SCOPE"] = args.scope
    if args.start_date:
        os.environ["BACKFILL_START_DATE"] = args.start_date
    if args.end_date:
        os.environ["BACKFILL_END_DATE"] = args.end_date
    from app.data_pipeline.backfill_config import reset_settings_cache

    reset_settings_cache()
    cfg = load_backfill_settings()
    start_date = cfg.start_date

    logger.info("=" * 80)
    logger.info("🚀 开始同步A股日线行情数据，起始日期: %s", start_date)
    logger.info("=" * 80)

    # 1. 获取所有股票列表
    async with async_session() as sess:
        res = await sess.execute(text("SELECT ts_code, name FROM stocks ORDER BY ts_code"))
        stocks = res.all()
    total_stocks = len(stocks)
    if total_stocks == 0:
        logger.error("股票列表为空，请先同步股票基础数据")
        return

    # 2. 按 backfill scope 过滤
    if cfg.scope == "tech_mvp":
        in_scope = [s for s in stocks if s.ts_code in cfg.ts_codes]
        logger.info("backfill scope=tech_mvp, %d/%d 命中白名单", len(in_scope), total_stocks)
        stocks = in_scope
        total_stocks = len(stocks)

    # 3. 过滤已完成的股票
    completed = load_completed_stocks()
    todo_stocks = [s for s in stocks if s.ts_code not in completed]
    todo_count = len(todo_stocks)
    completed_count = len(completed)

    logger.info(f"总股票数: {total_stocks}, 已完成: {completed_count}, 待同步: {todo_count}")
    if todo_count == 0:
        logger.info("🎉 所有股票已同步完成！")
        return

    # 4. 同步时间范围
    end_date = cfg.end_date
    logger.info(f"同步时间范围: {start_date} ~ {end_date}")

    if args.dry_run:
        logger.info("[dry-run] 将同步 %d 只: %s ...", todo_count, [s.ts_code for s in todo_stocks[:10]])
        return

    # 5. 并发同步
    semaphore = asyncio.Semaphore(CONCURRENCY)
    tasks = []
    for stock in todo_stocks:
        task = sync_single_stock(semaphore, stock.ts_code, start_date, end_date)
        tasks.append(task)

    # 执行任务
    logger.info(f"开始并发同步，并发数: {CONCURRENCY}")
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # 统计结果
    total_records = sum(r for r in results if isinstance(r, int))
    failed_count = sum(1 for r in results if isinstance(r, Exception))

    logger.info("=" * 80)
    logger.info("✅ 同步任务完成！")
    logger.info(f"本次同步股票数: {len([r for r in results if isinstance(r, int) and r >= 0])}")
    logger.info(f"本次新增记录数: {total_records:,} 条")
    logger.info(f"失败股票数: {failed_count} 只")

    # 统计总数据量
    async with async_session() as sess:
        res = await sess.execute(text("SELECT COUNT(*) FROM daily_data"))
        total = res.scalar_one()
        res = await sess.execute(text("SELECT MIN(trade_date), MAX(trade_date) FROM daily_data"))
        min_date, max_date = res.fetchone()
        logger.info(f"📊 当前总日线数据量: {total:,} 条")
        logger.info(f"📅 数据覆盖范围: {min_date} ~ {max_date}")


if __name__ == "__main__":
    asyncio.run(main())
