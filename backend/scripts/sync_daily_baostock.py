#!/usr/bin/env python3
"""
Baostock K线回补脚本

用 baostock 回补日线数据，替代 akshare 方式。
健壮性保证：
1. 以数据库已有数据为锚点，只回补缺失的日期
2. 只在数据成功入库后才标记完成
3. 跳过北交所(.BJ)、新三板(.NQ)等不支持的交易所
4. baostock 是线程不安全的 C 扩展，串行 asyncio.to_thread + 信号量隔离

用法:
    python -m scripts.sync_daily_baostock
    python -m scripts.sync_daily_baostock --scope tech_mvp
    python -m scripts.sync_daily_baostock --scope all
    python -m scripts.sync_daily_baostock --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

import baostock as bs
from sqlalchemy import text

from app.core.database import engine
from app.data_pipeline.backfill_config import load_backfill_settings, reset_settings_cache

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# 配置
BATCH_SIZE = 500  # 批量 INSERT 行数
CONCURRENCY = 1  # baostock 免费版严格串行
PROGRESS_FILE = Path(__file__).parent / ".daily_baostock_progress"

# 不支持的交易所后缀
UNSUPPORTED_EXCHANGES = {"BJ", "NQ"}  # 北交所、新三板


def _is_supported(ts_code: str) -> bool:
    """判断是否支持获取 K 线数据。"""
    suffix = ts_code.split(".")[-1]
    return suffix not in UNSUPPORTED_EXCHANGES


def _bs_code(ts_code: str) -> str:
    """ts_code → baostock 格式。"""
    symbol, exchange = ts_code.split(".")
    return f"{exchange.lower()}.{symbol}"


# ── 进度追踪 ──────────────────────────────────────────────


def load_progress() -> set[str]:
    if not PROGRESS_FILE.exists():
        return set()
    return set(PROGRESS_FILE.read_text().strip().splitlines())


def mark_done(ts_code: str):
    """标记股票已完成（只在校验通过后调用）。"""
    PROGRESS_FILE.write_text(PROGRESS_FILE.read_text() + f"{ts_code}\n")


def mark_fail(ts_code: str):
    """标记股票失败（写入失败文件）。"""
    fail_file = PROGRESS_FILE.with_suffix(".failed")
    existing = set(fail_file.read_text().strip().splitlines()) if fail_file.exists() else set()
    if ts_code not in existing:
        fail_file.write_text(fail_file.read_text() + f"{ts_code}\n")


# ── 数据获取（每次调用独立登录，asyncio.to_thread 隔离线程）──


def _fetch_baostock_raw(bs_code: str, start_date: str, end_date: str) -> list[dict]:
    """从 baostock 获取日线原始数据。必须在独立线程中调用。"""
    bs.login()
    try:
        rs = bs.query_history_k_data_plus(
            bs_code,
            "date,code,open,high,low,close,volume,amount",
            start_date=start_date,
            end_date=end_date,
            frequency="d",
            adjustflag="3",  # 不复权
        )
        if rs.error_code != "0":
            raise RuntimeError(f"baostock error: {rs.error_code} {rs.error_msg}")

        rows = []
        while rs.next():
            row = rs.get_row_data()
            if row[0]:
                rows.append(row)
        return rows
    finally:
        bs.logout()


def _process_rows(ts_code: str, rows: list[list]) -> list[dict]:
    """将 baostock 原始行转换为入库记录。"""
    records = []
    prev_close = None
    # baostock 返回字段: date,code,open,high,low,close,volume,amount
    for row in rows:
        trade_date_str = row[0]
        open_price = float(row[2]) if row[2] else 0.0
        high_price = float(row[3]) if row[3] else 0.0
        low_price = float(row[4]) if row[4] else 0.0
        close_price = float(row[5]) if row[5] else 0.0
        vol = float(row[6]) if row[6] else 0.0
        amount = float(row[7]) if row[7] else 0.0

        pre_close = prev_close if prev_close is not None else close_price
        change = close_price - pre_close
        pct_chg = (change / pre_close * 100) if pre_close else 0.0
        is_suspended = vol == 0

        records.append(
            {
                "ts_code": ts_code,
                "trade_date": datetime.strptime(trade_date_str, "%Y-%m-%d").date(),
                "open": open_price,
                "high": high_price,
                "low": low_price,
                "close": close_price,
                "pre_close": pre_close,
                "change": round(change, 3),
                "pct_chg": round(pct_chg, 2),
                "vol": vol,
                "amount": amount,
                "is_suspended": is_suspended,
            }
        )
        prev_close = close_price
    return records


# ── 数据入库 ──────────────────────────────────────────────


async def _batch_insert(data: list[dict]) -> int:
    """批量 INSERT daily_data。"""
    if not data:
        return 0
    stmt = text("""
        INSERT INTO daily_data (
            ts_code, trade_date, open, high, low, close, pre_close,
            change, pct_chg, vol, amount, is_suspended
        ) VALUES (
            :ts_code, :trade_date, :open, :high, :low, :close, :pre_close,
            :change, :pct_chg, :vol, :amount, :is_suspended
        ) ON CONFLICT (ts_code, trade_date) DO NOTHING
    """)
    try:
        async with engine.begin() as conn:
            result = await conn.execute(stmt, data)
            return result.rowcount if result.rowcount else 0
    except Exception as e:
        logger.warning(f"批量插入失败，降级逐条: {e}")
        saved = 0
        for rec in data:
            try:
                async with engine.begin() as conn:
                    result = await conn.execute(stmt, [rec])
                    saved += result.rowcount if result.rowcount else 0
            except Exception:
                pass
        return saved


# ── 单股同步 ──────────────────────────────────────────────


async def sync_stock(
    ts_code: str,
    start_date_str: str,
    end_date_str: str,
) -> dict[str, Any]:
    """同步单只股票 K 线。

    Returns:
        {"status": "ok"|"skip"|"fail", "saved": int, "msg": str}
    """
    # 1. 检查交易所支持
    if not _is_supported(ts_code):
        return {"status": "skip", "saved": 0, "msg": "unsupported exchange"}

    # 2. 查询已有数据的时间范围
    async with engine.connect() as conn:
        r = await conn.execute(
            text("""
            SELECT MIN(trade_date), MAX(trade_date)
            FROM daily_data WHERE ts_code = :ts
        """),
            {"ts": ts_code},
        )
        row = r.fetchone()
        min_d, max_d = row[0], row[1]

    # 3. 确定实际需要获取的日期范围
    #    已有数据起始日期 → 目标结束日期（不重复拉取已有部分）
    if min_d is not None:
        # 从已有数据的下一天开始
        actual_start = datetime.strptime(str(min_d), "%Y-%m-%d").date() + timedelta(days=1)
        actual_start_str = actual_start.strftime("%Y-%m-%d")  # YYYY-MM-DD
    else:
        actual_start_str = f"{start_date_str[:4]}-{start_date_str[4:6]}-{start_date_str[6:8]}"

    actual_end_str = f"{end_date_str[:4]}-{end_date_str[4:6]}-{end_date_str[6:8]}"  # YYYY-MM-DD

    # 如果起始日期 > 结束日期，说明已有数据已覆盖目标范围
    if actual_start_str > actual_end_str:
        return {"status": "ok", "saved": 0, "msg": "already up-to-date"}

    # 4. 获取数据（线程隔离，每次独立登录）
    bs_code = _bs_code(ts_code)
    try:
        rows = await asyncio.to_thread(_fetch_baostock_raw, bs_code, actual_start_str, actual_end_str)
    except Exception as e:
        return {"status": "fail", "saved": 0, "msg": str(e)}

    if not rows:
        # baostock 无数据，不标记完成（可能是停牌/退市等）
        return {"status": "skip", "saved": 0, "msg": "no data from baostock"}

    # 5. 转换格式并入库
    records = _process_rows(ts_code, rows)

    total_saved = 0
    for i in range(0, len(records), BATCH_SIZE):
        batch = records[i : i + BATCH_SIZE]
        saved = await _batch_insert(batch)
        total_saved += saved

    return {"status": "ok", "saved": total_saved, "msg": f"{len(rows)} rows, {total_saved} saved"}


# ── 可导出：每日增量同步（供 scheduler 调用）────────────────────────────


async def sync_daily(
    scope: str = "tech_mvp",
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    """每日增量同步：只同步昨天一条 K 线。

    Args:
        scope: 白名单范围，默认 tech_mvp
        start_date: YYYYMMDD，默认昨天
        end_date: YYYYMMDD，默认昨天
    Returns:
        {"ok": int, "skip": int, "fail": int, "saved": int, "total": int}
    """
    today = datetime.now()
    yesterday = (today - timedelta(days=1)).strftime("%Y%m%d")
    sd = start_date or yesterday
    ed = end_date or yesterday

    if scope:
        os.environ["BACKFILL_SCOPE"] = scope
    reset_settings_cache()
    cfg = load_backfill_settings()

    # 覆盖配置中的日期范围
    actual_start = f"{sd[:4]}-{sd[4:6]}-{sd[6:8]}"
    actual_end = f"{ed[:4]}-{ed[4:6]}-{ed[6:8]}"

    async with engine.connect() as conn:
        if cfg.scope == "tech_mvp" and cfg.ts_codes:
            placeholders = ", ".join([f":c{i}" for i in range(len(cfg.ts_codes))])
            params = {f"c{i}": c for i, c in enumerate(cfg.ts_codes)}
            r = await conn.execute(
                text(f"""
                SELECT ts_code FROM stocks
                WHERE ts_code IN ({placeholders})
                ORDER BY ts_code
            """),
                params,
            )
        else:
            r = await conn.execute(text("SELECT ts_code FROM stocks ORDER BY ts_code"))
        all_stocks = [row[0] for row in r.fetchall()]

    stocks = [s for s in all_stocks if _is_supported(s)]

    semaphore = asyncio.Semaphore(1)  # 严格串行
    stats = {"ok": 0, "skip": 0, "fail": 0, "saved": 0, "total": len(stocks)}
    lock = asyncio.Lock()

    async def worker(ts_code: str):
        async with semaphore:
            result = await sync_stock(ts_code, sd, ed)
            async with lock:
                stats[result["status"]] += 1
                stats["saved"] += result["saved"]

    tasks = [worker(s) for s in stocks]
    await asyncio.gather(*tasks)

    logger.info(
        "[sync_daily] K线同步完成: ok=%d skip=%d fail=%d saved=%d",
        stats["ok"],
        stats["skip"],
        stats["fail"],
        stats["saved"],
    )
    return stats


# ── 主入口 ────────────────────────────────────────────────


def format_duration(seconds: int) -> str:
    h, remainder = divmod(seconds, 3600)
    m, s = divmod(remainder, 60)
    return f"{h}:{m:02d}:{s:02d}"


async def main(
    scope: str | None = None,
    dry_run: bool = False,
    concurrency: int = CONCURRENCY,
) -> dict[str, Any]:
    # baostock 免费版严格串行，用信号量控制
    concurrency = 1

    if scope:
        os.environ["BACKFILL_SCOPE"] = scope
    reset_settings_cache()
    cfg = load_backfill_settings()

    start_time = time.time()
    start_date_str = cfg.start_date  # YYYYMMDD
    end_date_str = cfg.end_date  # YYYYMMDD

    # 获取股票列表（白名单过滤）
    async with engine.connect() as conn:
        if cfg.scope == "tech_mvp" and cfg.ts_codes:
            placeholders = ", ".join([f":c{i}" for i in range(len(cfg.ts_codes))])
            params = {f"c{i}": c for i, c in enumerate(cfg.ts_codes)}
            r = await conn.execute(
                text(f"""
                SELECT ts_code FROM stocks
                WHERE ts_code IN ({placeholders})
                ORDER BY ts_code
            """),
                params,
            )
        else:
            r = await conn.execute(text("SELECT ts_code FROM stocks ORDER BY ts_code"))
        all_stocks = [row[0] for row in r.fetchall()]

    # 过滤不支持的交易所
    supported_stocks = [s for s in all_stocks if _is_supported(s)]
    unsupported = len(all_stocks) - len(supported_stocks)

    # 进度过滤（已完成的不再处理，但 dry-run 时跳过）
    if not dry_run:
        done = load_progress()
        todo = [s for s in supported_stocks if s not in done]
    else:
        todo = supported_stocks
        done = set()

    print(f"{'=' * 65}")
    print("  Baostock K线回补")
    print(f"{'=' * 65}")
    print(f"  股票总数:    {len(all_stocks)}")
    print(f"  支持获取:    {len(supported_stocks)}")
    print(f"  不支持:      {unsupported} (BJ/NQ 等)")
    print(f"  已完成:      {len(done)}")
    print(f"  待同步:      {len(todo)}")
    print(f"  日期范围:    {cfg.start_date} ~ {cfg.end_date}")
    print(f"  白名单:      {cfg.scope}")
    print(f"  模式:        {'试运行 (dry-run)' if dry_run else '正式写入'}")
    print(f"  开始时间:    {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    if not todo:
        print("  所有股票已同步完成!")
        return {}

    if dry_run:
        print(f"  [dry-run] 将同步 {len(todo)} 只")
        return {}

    # 并发同步（信号量 = 1 保证串行）
    semaphore = asyncio.Semaphore(concurrency)
    stats = {"ok": 0, "skip": 0, "fail": 0, "saved": 0, "total": len(todo)}
    lock = asyncio.Lock()

    async def worker(ts_code: str, idx: int, total: int):
        async with semaphore:
            result = await sync_stock(ts_code, start_date_str, end_date_str)
            async with lock:
                stats[result["status"]] += 1
                stats["saved"] += result["saved"]
                if idx % 50 == 0 or result["status"] == "fail":
                    elapsed = int(time.time() - start_time)
                    logger.info(
                        f"  [{idx}/{total}] {ts_code}: {result['status']} "
                        f"({result['saved']} saved) | ok={stats['ok']} skip={stats['skip']} fail={stats['fail']} | {format_duration(elapsed)}"
                    )

    tasks = [worker(s, i, len(todo)) for i, s in enumerate(todo)]
    await asyncio.gather(*tasks)

    elapsed = int(time.time() - start_time)
    print()
    print(f"{'=' * 65}")
    print("  回补完成!")
    print(f"{'=' * 65}")
    print(f"  同步完成:     {stats['ok']}")
    print(f"  跳过(无数据): {stats['skip']}")
    print(f"  失败:         {stats['fail']}")
    print(f"  新增入库:     {stats['saved']:,}")
    print(f"  总耗时:       {format_duration(elapsed)}")
    print(f"  完成时间:     {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # 检查失败文件
    fail_file = PROGRESS_FILE.with_suffix(".failed")
    if fail_file.exists():
        failed = set(fail_file.read_text().strip().splitlines())
        if failed:
            print(f"  失败股票:     {len(failed)} 只 (见 {fail_file})")

    return stats


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Baostock K线回补")
    parser.add_argument("--scope", choices=["tech_mvp", "all"], default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--concurrency", type=int, default=CONCURRENCY)
    args = parser.parse_args()

    asyncio.run(
        main(
            scope=args.scope,
            dry_run=args.dry_run,
            concurrency=args.concurrency,
        )
    )
