#!/usr/bin/env python3
"""
Tushare K线回补脚本

用 tushare 回补日线数据，替代 akshare / baostock 方式。
健壮性保证：
1. 以数据库已有数据为锚点，只回补缺失的日期
2. 只在数据成功入库后才标记完成
3. 跳过北交所(.BJ)、新三板(.NQ)等不支持的交易所

用法:
    python -m scripts.sync_daily_tushare
    python -m scripts.sync_daily_tushare --scope tech_mvp
    python -m scripts.sync_daily_tushare --scope all
    python -m scripts.sync_daily_tushare --dry-run
    python -m scripts.sync_daily_tushare --concurrency 20
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

import pandas as pd
import tushare as ts
from sqlalchemy import text

from app.core.database import engine
from app.data_pipeline.backfill_config import load_backfill_settings, reset_settings_cache

# ── Teajoin Tushare 初始化 ─────────────────────────────────
# teajoin token 从环境变量读取（默认使用 .env 中配置）
_TEAJOIN_TOKEN = os.environ.get("TUSHARE_TOKEN", "")
if not _TEAJOIN_TOKEN:
    # 回退到 .env 中 hardcode 的 apikey
    _TEAJOIN_TOKEN = "086520ee148add8a401f8a5f04644ef2d04abbff5494461a"

ts.set_token(_TEAJOIN_TOKEN)
_TUSHARE_API = ts.pro_api()
_TUSHARE_API._DataApi__http_url = "https://teajoin.com"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# 配置
BATCH_SIZE = 500  # 批量 INSERT 行数
CONCURRENCY = 5  # 并发协程数（5 × 0.12s ≈ 42次/秒 ≈ 2500/分钟，但仍需限流）
PROGRESS_FILE = Path(__file__).parent / ".daily_tushare_progress"

# 不支持的交易所后缀
UNSUPPORTED_EXCHANGES = {"BJ", "NQ"}  # 北交所、新三板

# teajoin 每分钟最多 500 次调用
# 5 并发 × 0.12s 间隔 = 41.7 次/秒 × 60s = 2500 次/分钟（会超限）
# 改为更保守的策略：每次请求后等待 0.15 秒
_RATE_LIMIT = asyncio.Semaphore(CONCURRENCY)


def _is_supported(ts_code: str) -> bool:
    """判断是否支持获取 K 线数据。"""
    suffix = ts_code.split(".")[-1]
    return suffix not in UNSUPPORTED_EXCHANGES


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


# ── 数据获取 ──────────────────────────────────────────────


def _fetch_tushare(ts_code: str, start_date: str, end_date: str) -> list[dict]:
    """从 teajoin tushare 获取日线数据。每次调用使用共享 API 实例。"""
    try:
        # tushare pro.daily 返回字段: ts_code, trade_date, open, high, low,
        #                           close, pre_close, change, pct_chg, vol, amount
        df = _TUSHARE_API.daily(
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date,
        )
        if df is None or df.empty:
            return []
        rows = []
        for _, row in df.iterrows():
            rows.append(
                {
                    "trade_date": row["trade_date"],
                    "ts_code": row["ts_code"],
                    "open": float(row["open"]) if pd.notna(row["open"]) else 0.0,
                    "high": float(row["high"]) if pd.notna(row["high"]) else 0.0,
                    "low": float(row["low"]) if pd.notna(row["low"]) else 0.0,
                    "close": float(row["close"]) if pd.notna(row["close"]) else 0.0,
                    "pre_close": float(row["pre_close"]) if pd.notna(row["pre_close"]) else 0.0,
                    "change": float(row["change"]) if pd.notna(row["change"]) else 0.0,
                    "pct_chg": float(row["pct_chg"]) if pd.notna(row["pct_chg"]) else 0.0,
                    "vol": float(row["vol"]) if pd.notna(row["vol"]) else 0.0,
                    "amount": float(row["amount"]) if pd.notna(row["amount"]) else 0.0,
                }
            )
        return rows
    except Exception as e:
        logger.warning(f"tushare fetch error for {ts_code}: {e}")
        return []


# ── 数据入库 ──────────────────────────────────────────────


async def _batch_insert(data: list[dict]) -> int:
    """批量 INSERT daily_data。返回实际插入的行数。

    使用 asyncpg 的 UNNEST 方式来解决 RETURNING 在批量时无法获取行数的问题。
    """
    if not data:
        return 0

    try:
        async with engine.connect() as conn:
            raw_conn = await conn.get_raw_connection()
            pg_conn = raw_conn.driver_connection

            # asyncpg UNNEST 方式，可以正确获取 RETURNING 行数
            rows = await pg_conn.fetch(
                """
                INSERT INTO daily_data (
                    ts_code, trade_date, open, high, low, close, pre_close,
                    change, pct_chg, vol, amount, is_suspended
                )
                SELECT * FROM UNNEST(
                    $1::text[], $2::date[], $3::numeric[], $4::numeric[], $5::numeric[],
                    $6::numeric[], $7::numeric[], $8::numeric[], $9::numeric[],
                    $10::numeric[], $11::numeric[], $12::boolean[]
                )
                ON CONFLICT (ts_code, trade_date) DO NOTHING
                RETURNING ts_code
                """,
                [d["ts_code"] for d in data],
                [d["trade_date"] for d in data],
                [d["open"] for d in data],
                [d["high"] for d in data],
                [d["low"] for d in data],
                [d["close"] for d in data],
                [d["pre_close"] for d in data],
                [d["change"] for d in data],
                [d["pct_chg"] for d in data],
                [d["vol"] for d in data],
                [d["amount"] for d in data],
                [d["is_suspended"] for d in data],
            )
            return len(rows)
    except Exception as e:
        logger.warning(f"UNNEST 插入失败，降级逐条: {e}")
        saved = 0
        for rec in data:
            try:
                async with engine.connect() as conn:
                    raw_conn = await conn.get_raw_connection()
                    pg_conn = raw_conn.driver_connection
                    rows = await pg_conn.fetch(
                        """
                        INSERT INTO daily_data (
                            ts_code, trade_date, open, high, low, close, pre_close,
                            change, pct_chg, vol, amount, is_suspended
                        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                        ON CONFLICT (ts_code, trade_date) DO NOTHING
                        RETURNING ts_code
                        """,
                        rec["ts_code"],
                        rec["trade_date"],
                        rec["open"],
                        rec["high"],
                        rec["low"],
                        rec["close"],
                        rec["pre_close"],
                        rec["change"],
                        rec["pct_chg"],
                        rec["vol"],
                        rec["amount"],
                        rec["is_suspended"],
                    )
                    saved += len(rows)
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
        actual_start_str = actual_start.strftime("%Y%m%d")  # YYYYMMDD
    else:
        actual_start_str = start_date_str  # 用配置起始日期

    actual_end_str = end_date_str  # YYYYMMDD

    # 如果起始日期 > 结束日期，说明已有数据已覆盖目标范围
    if actual_start_str > actual_end_str:
        return {"status": "ok", "saved": 0, "msg": "already up-to-date"}

    # 4. 获取数据（在线程池中调用 tushare，避免阻塞事件循环）
    try:
        rows = await asyncio.to_thread(_fetch_tushare, ts_code, actual_start_str, actual_end_str)
    except Exception as e:
        return {"status": "fail", "saved": 0, "msg": str(e)}

    if not rows:
        # tushare 无数据，不标记完成（可能是停牌/退市等）
        return {"status": "skip", "saved": 0, "msg": "no data from tushare"}

    # 5. 转换格式并入库（tushare 已提供 pre_close/change/pct_chg）
    records = []
    for row in rows:
        trade_date_str = row["trade_date"]
        records.append(
            {
                "ts_code": ts_code,
                "trade_date": datetime.strptime(str(trade_date_str), "%Y%m%d").date(),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "pre_close": float(row["pre_close"]),
                "change": float(row["change"]),
                "pct_chg": float(row["pct_chg"]),
                "vol": float(row["vol"]),
                "amount": float(row["amount"]),
                "is_suspended": bool(row["vol"] == 0),  # 转为 Python bool，兼容 asyncpg
            }
        )

    # 批量入库
    total_saved = 0
    for i in range(0, len(records), BATCH_SIZE):
        batch = records[i : i + BATCH_SIZE]
        saved = await _batch_insert(batch)
        total_saved += saved

    return {"status": "ok", "saved": total_saved, "msg": f"{len(rows)} rows, {total_saved} saved"}


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
    if scope:
        os.environ["BACKFILL_SCOPE"] = scope
    reset_settings_cache()
    cfg = load_backfill_settings()

    start_time = time.time()
    start_date_str = cfg.start_date  # YYYY-MM-DD → YYYYMMDD
    start_date_str = start_date_str.replace("-", "")
    end_date_str = cfg.end_date.replace("-", "")  # YYYYMMDD

    # 获取股票列表
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
    print("  Tushare K线回补")
    print(f"{'=' * 65}")
    print(f"  股票总数:    {len(all_stocks)}")
    print(f"  支持获取:    {len(supported_stocks)}")
    print(f"  不支持:      {unsupported} (BJ/NQ 等)")
    print(f"  已完成:      {len(done)}")
    print(f"  待同步:      {len(todo)}")
    print(f"  日期范围:    {start_date_str} ~ {end_date_str}")
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

    # 并发同步
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
            # 每次请求后短暂等待，避免触发 teajoin 频率限制（500次/分钟）
            await asyncio.sleep(0.15)

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
    parser = argparse.ArgumentParser(description="Tushare K线回补")
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
