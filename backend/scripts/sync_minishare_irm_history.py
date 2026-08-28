#!/usr/bin/env python3
"""
Minishare IRM 历史数据回补脚本

使用 minishare 的 irm_qa_sz / irm_qa_sh 接口按候选池逐只股票拉取互动易数据。
替代按天全市场遍历的方式，只获取候选池关心的股票，效率更高。

数据流：
1. 从 candidate_pool 加载股票列表
2. 按 ts_code 调用 minishare API（SZ/SH自动分流）
3. 关键词过滤 (irm_filter.should_save)
4. 批量 INSERT (ON CONFLICT DO NOTHING)

用法:
    # 默认从 2025-01-01 到最新，只入库候选池股票
    python -m scripts.sync_minishare_irm_history

    # 指定日期范围
    python -m scripts.sync_minishare_irm_history --start-date 20250601 --end-date 20250630

    # 试运行
    python -m scripts.sync_minishare_irm_history --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import logging
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

# 添加 backend 到 path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.database import engine
from app.data_pipeline.irm_filter import should_save as should_save_irm
from app.models.models import Announcement

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# 常量
BATCH_SIZE = 500


# ── 辅助函数 ──────────────────────────────────────────────


def _parse_trade_date(trade_date) -> datetime.date | None:
    """解析 trade_date 为 date 对象。"""
    if not trade_date:
        return None
    s = str(trade_date).strip()
    try:
        return datetime.strptime(s[:8], "%Y%m%d").date()
    except ValueError:
        return None


def _generate_cninfo_id(ts_code: str, exchange: str, question_time, question: str) -> str:
    """生成唯一 cninfo_id（与 fetcher._save_irm_record 的 _stable_id 公式一致，保证去重）。"""
    q_hash = hashlib.md5(question.encode("utf-8", errors="replace")).hexdigest()[:10]
    raw = "".join([str(exchange), str(ts_code), str(question_time or "-"), str(q_hash)]).encode("utf-8", errors="replace")
    return f"irm_{hashlib.sha1(raw).hexdigest()[:16]}"


def _get_exchange(ts_code: str) -> str:
    """根据 ts_code 后缀判断交易所。"""
    if ts_code.endswith(".SH"):
        return "SH"
    return "SZ"


def _get_api_name(exchange: str) -> str:
    """交易所代码 → minishare API 名称。"""
    if exchange == "SH":
        return "irm_qa_sh"
    return "irm_qa_sz"


# ── 批量插入 ──────────────────────────────────────────────


async def _batch_insert(records: list[dict]) -> tuple[int, int]:
    """批量 INSERT，返回 (saved, dup_skipped)。"""
    if not records:
        return 0, 0

    stmt = pg_insert(Announcement.__table__).values(records)
    stmt = stmt.on_conflict_do_nothing(index_elements=["ts_code", "ann_date", "title"])

    try:
        async with engine.begin() as conn:
            result = await conn.execute(stmt)
            saved = result.rowcount if result.rowcount else 0
            return saved, len(records) - saved
    except Exception:
        saved = 0
        for rec in records:
            try:
                async with engine.begin() as conn:
                    stmt = pg_insert(Announcement.__table__).values([rec])
                    stmt = stmt.on_conflict_do_nothing(index_elements=["cninfo_id"])
                    result = await conn.execute(stmt)
                    saved += result.rowcount if result.rowcount else 0
            except Exception:
                try:
                    async with engine.begin() as conn:
                        stmt = pg_insert(Announcement.__table__).values([rec])
                        stmt = stmt.on_conflict_do_nothing(index_elements=["ts_code", "ann_date", "title"])
                        result = await conn.execute(stmt)
                        saved += result.rowcount if result.rowcount else 0
                except Exception:
                    pass
        return saved, len(records) - saved


# ── 按股票同步 ────────────────────────────────────────────


async def load_candidate_pool_codes() -> list[str]:
    """从 candidate_pool 表加载候选股票代码（仅活跃 target pool）。"""
    async with engine.connect() as conn:
        rows = await conn.execute(text("SELECT ts_code FROM candidate_pool WHERE is_active = true ORDER BY ts_code"))
        return [row[0] for row in rows.fetchall()]


async def get_processed_stocks() -> set[str]:
    """获取已导入 IRM 数据的股票列表。"""
    async with engine.connect() as conn:
        rows = await conn.execute(
            text("SELECT DISTINCT ts_code FROM announcements WHERE announcement_type LIKE 'irm:%'")
        )
        return {row[0] for row in rows.fetchall()}


async def sync_stock(
    ts_code: str,
    minishare_pro,
    start_date: str,
    end_date: str,
    batch_size: int,
    dry_run: bool,
) -> dict[str, int]:
    """同步单只股票的 IRM 数据。"""
    counters = {"fetched": 0, "filtered": 0, "saved": 0, "dup_skip": 0, "error": 0}

    exchange = _get_exchange(ts_code)
    api_name = _get_api_name(exchange)

    # 带重试的 API 调用（429 时退避重试）
    df = None
    for attempt in range(3):
        try:
            df = await asyncio.to_thread(
                getattr(minishare_pro, api_name),
                ts_code=ts_code,
                start_date=start_date,
                end_date=end_date,
            )
            break
        except Exception as e:
            err_msg = str(e)
            if "429" in err_msg or "频率限制" in err_msg:
                wait = 2 ** (attempt + 1)  # 2s, 4s, 8s
                logger.warning(f"{ts_code} 触发频率限制，等待 {wait}s 后重试 (attempt {attempt+1}/3)")
                await asyncio.sleep(wait)
            else:
                logger.warning(f"{ts_code} API 调用失败: {e}")
                counters["error"] = 1
                return counters

    if df is None or df.empty:
        return counters

    counters["fetched"] = len(df)
    pending: list[dict] = []

    for _, row in df.iterrows():
        question = str(row.get("q", "")).strip()
        answer = str(row.get("a", "")).strip()

        # 空值过滤
        if not question or not answer or question == "nan" or answer == "nan":
            continue

        # 关键词过滤
        if not should_save_irm(question, answer):
            counters["filtered"] += 1
            continue

        # 解析日期
        trade_date_val = row.get("trade_date")
        ann_date = _parse_trade_date(trade_date_val)
        if ann_date is None:
            continue

        # 生成唯一 ID（与每日抓取 _save_irm_record 同公式，避免重复）
        cninfo_id = _generate_cninfo_id(ts_code, exchange, trade_date_val, question)

        source_name = "上证e互动" if exchange == "SH" else "深证互动易"

        pending.append(
            {
                "ann_date": ann_date,
                "ts_code": ts_code,
                "name": str(row.get("name", "")).strip() or None,
                "title": question[:500],
                "type": answer,
                "cninfo_id": cninfo_id,
                "announcement_type": f"irm:{exchange}",
                "source_type": "irm",
                "source_name": source_name,
                "confidence_tier": "Tier2",
            }
        )

    # 批量写入
    if not dry_run and pending:
        for i in range(0, len(pending), batch_size):
            batch = pending[i : i + batch_size]
            saved, dup = await _batch_insert(batch)
            counters["saved"] += saved
            counters["dup_skip"] += dup
    elif dry_run:
        counters["saved"] = len(pending)

    return counters


# ── 主入口 ────────────────────────────────────────────────


def format_duration(seconds: int) -> str:
    h, remainder = divmod(seconds, 3600)
    m, s = divmod(remainder, 60)
    return f"{h}:{m:02d}:{s:02d}"


async def main(
    start_date_str: str | None = None,
    end_date_str: str | None = None,
    batch_size: int = BATCH_SIZE,
    dry_run: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    """主函数"""
    start_time = time.time()

    # 默认日期范围
    if start_date_str:
        start_date = start_date_str
    else:
        start_date = "20250101"

    if end_date_str:
        end_date = end_date_str
    else:
        end_date = datetime.now().strftime("%Y%m%d")

    # 候选池股票
    pool_codes = await load_candidate_pool_codes()
    sz_codes = [c for c in pool_codes if c.endswith(".SZ")]
    sh_codes = [c for c in pool_codes if c.endswith(".SH")]

    # 已处理的股票（跳过，避免重复 API 调用；--force 时强制全量重跑 2 年窗口，靠 ON CONFLICT 去重）
    processed = set() if force else await get_processed_stocks()
    unprocessed = [c for c in pool_codes if c not in processed and (c.endswith(".SZ") or c.endswith(".SH"))]
    already_done = len(pool_codes) - len(unprocessed) - len([c for c in pool_codes if not (c.endswith(".SZ") or c.endswith(".SH"))])

    print(f"{'=' * 65}")
    print("  Minishare IRM 数据回补（按候选池逐只获取）")
    print(f"{'=' * 65}")
    print(f"  日期范围:  {start_date} ~ {end_date}")
    print(f"  候选池:    {len(pool_codes)} 只 (SZ: {len(sz_codes)}, SH: {len(sh_codes)})")
    print(f"  已处理:    {already_done} 只")
    print(f"  待处理:    {len(unprocessed)} 只")
    print(f"  批量大小:  {batch_size}")
    print(f"  模式:      {'试运行 (dry-run)' if dry_run else '正式写入'}")
    print(f"  开始时间:  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    if not unprocessed:
        print("  所有股票已处理完毕，无需同步")
        return {}

    # 初始化 minishare
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).parent.parent / ".env")
    irm_token = os.getenv("MINISHARE_IRM_TOKEN", "")
    if not irm_token:
        print("  错误: MINISHARE_IRM_TOKEN 未配置")
        return {}

    import minishare as ms

    minishare_pro = ms.pro_api(irm_token)

    # 总计数器
    total = {"fetched": 0, "filtered": 0, "saved": 0, "dup_skip": 0, "error": 0}

    # 限速：每分钟最多 90 次 API 调用（留 10 次余量）
    api_calls_in_window = 0
    window_start = time.time()

    for i, ts_code in enumerate(unprocessed):

        # 检查限速窗口（每分钟 90 次）
        api_calls_in_window += 1
        elapsed_in_window = time.time() - window_start
        if api_calls_in_window >= 90:
            if elapsed_in_window < 60:
                sleep_time = 60 - elapsed_in_window
                logger.info(f"  [限速] 已达 90 次/分钟上限，暂停 {sleep_time:.0f}s")
                await asyncio.sleep(sleep_time)
            api_calls_in_window = 0
            window_start = time.time()

        result = await sync_stock(ts_code, minishare_pro, start_date, end_date, batch_size, dry_run)

        for k in total:
            total[k] += result.get(k, 0)

        # 每 50 只打印一次进度
        if (i + 1) % 50 == 0 or result["saved"] > 0:
            elapsed = int(time.time() - start_time)
            rate = (i + 1) / (elapsed or 1) * 60  # 只/分钟
            remaining = (len(unprocessed) - i - 1) / (rate or 1)
            logger.info(
                f"[{i+1}/{len(unprocessed)}] {ts_code}: fetched={result['fetched']}, "
                f"saved={result['saved']}, filtered={result['filtered']}, "
                f"err={result['error']} | "
                f"进度: {rate:.0f}只/分, 预计剩余: {remaining:.0f}分"
            )

    # 完成
    elapsed = int(time.time() - start_time)
    print()
    print(f"{'=' * 65}")
    print("  回补完成!")
    print(f"{'=' * 65}")
    print(f"  处理股票:   {len(unprocessed)}")
    print(f"  API获取:    {total['fetched']:,} 条")
    print(f"  关键词过滤: {total['filtered']:,} 条")
    print(f"  新增入库:   {total['saved']:,} 条")
    print(f"  重复跳过:   {total['dup_skip']:,} 条")
    print(f"  错误:       {total['error']} 只")
    print(f"  总耗时:     {format_duration(elapsed)}")
    print(f"  完成时间:   {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    return total


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Minishare IRM 数据回补（按候选池逐只获取）")
    parser.add_argument("--start-date", help="起始日期 YYYYMMDD (默认: 20250101)")
    parser.add_argument("--end-date", help="结束日期 YYYYMMDD (默认: 今天)")
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    parser.add_argument("--dry-run", action="store_true", help="试运行")
    parser.add_argument("--force", action="store_true", help="强制全量重跑（忽略已处理标记，靠去重跳过重复）")
    args = parser.parse_args()

    asyncio.run(
        main(
            start_date_str=args.start_date,
            end_date_str=args.end_date,
            batch_size=args.batch_size,
            dry_run=args.dry_run,
            force=args.force,
        )
    )
