#!/usr/bin/env python3
"""
Minishare IRM 历史数据回补脚本

使用 minishare 的 irm_qa_sz / irm_qa_sh 接口按天拉取互动易数据。
替代 akshare 逐股票抓取的方式，速度更快、更稳定。

数据流：
1. 按天调 minishare irm_qa_sz / irm_qa_sh 获取全市场 IRM 问答
2. 关键词过滤 (irm_filter.should_save)
3. 白名单过滤 (backfill_config)
4. 批量 INSERT (pg_insert + ON CONFLICT DO NOTHING)

用法:
    # 回补指定日期范围（默认从 irm_local 最新日期的下一天到今天）
    python -m scripts.sync_minishare_irm_history

    # 指定日期范围
    python -m scripts.sync_minishare_irm_history --start-date 20260619 --end-date 20260622

    # 全市场（不限白名单）
    python -m scripts.sync_minishare_irm_history --scope all

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

from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.database import engine
from app.data_pipeline.irm_filter import should_save as should_save_irm
from app.data_pipeline.progress import (
    PARTIAL,
    SUCCESS,
    IngestionProgressTracker,
)
from app.models.models import Announcement
from app.data_pipeline.backfill_config import load_backfill_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# 常量
BATCH_SIZE = 500


# ── 数据转换 ──────────────────────────────────────────────


def _source_to_exchange(source: str) -> str:
    """source 字段 → 交易所代码。"""
    if not source:
        return "SZ"
    if "sh" in source.lower():
        return "SH"
    return "SZ"


def _parse_trade_date(trade_date) -> datetime.date | None:
    """解析 trade_date 为 date 对象。"""
    if not trade_date:
        return None
    s = str(trade_date).strip()
    try:
        return datetime.strptime(s[:8], "%Y%m%d").date()
    except ValueError:
        return None


def _generate_cninfo_id(ts_code: str, trade_date, row_hash: str) -> str:
    """生成唯一 cninfo_id。"""
    hash_part = row_hash[:24] if row_hash else "unknown"
    return f"irm_ms_{ts_code}_{trade_date}_{hash_part}"


# ── 批量插入 ──────────────────────────────────────────────


async def _batch_insert(records: list[dict]) -> tuple[int, int]:
    """批量 INSERT，返回 (saved, dup_skipped)。"""
    if not records:
        return 0, 0

    stmt = pg_insert(Announcement.__table__).values(records)
    # 同时处理两个唯一约束
    stmt = stmt.on_conflict_do_nothing(index_elements=["ts_code", "ann_date", "title"])

    try:
        async with engine.begin() as conn:
            result = await conn.execute(stmt)
            saved = result.rowcount if result.rowcount else 0
            return saved, len(records) - saved
    except Exception as e:
        # 降级逐条插入，同时处理两个约束
        saved = 0
        for rec in records:
            try:
                async with engine.begin() as conn:
                    stmt = pg_insert(Announcement.__table__).values([rec])
                    stmt = stmt.on_conflict_do_nothing(index_elements=["cninfo_id"])
                    result = await conn.execute(stmt)
                    saved += result.rowcount if result.rowcount else 0
            except Exception:
                # 如果 cninfo_id 约束也失败，尝试 (ts_code, ann_date, title)
                try:
                    async with engine.begin() as conn:
                        stmt = pg_insert(Announcement.__table__).values([rec])
                        stmt = stmt.on_conflict_do_nothing(index_elements=["ts_code", "ann_date", "title"])
                        result = await conn.execute(stmt)
                        saved += result.rowcount if result.rowcount else 0
                except Exception:
                    pass
        return saved, len(records) - saved


# ── 按天同步 ──────────────────────────────────────────────


def _fetch_day_irm(minishare_pro, trade_date: str) -> list[dict]:
    """拉取单天的 IRM 数据（SZ + SH）。"""
    records = []
    for api_name, source_tag in [("irm_qa_sz", "irm_qa_sz"), ("irm_qa_sh", "irm_qa_sh")]:
        try:
            df = getattr(minishare_pro, api_name)(trade_date=trade_date)
            if df is not None and not df.empty:
                for _, row in df.iterrows():
                    records.append({
                        "source": source_tag,
                        "ts_code": str(row.get("ts_code", "")).strip(),
                        "name": str(row.get("name", "")).strip(),
                        "trade_date": row.get("trade_date"),
                        "pub_time": str(row.get("pub_time", "")).strip(),
                        "industry": str(row.get("industry", "")).strip(),
                        "q": str(row.get("q", "")).strip(),
                        "a": str(row.get("a", "")).strip(),
                        "row_hash": str(row.get("row_hash", "")).strip(),
                    })
        except Exception as e:
            logger.warning(f"{api_name} {trade_date} 失败: {e}")
    return records


async def sync_day(
    trade_date: str,
    minishare_pro,
    whitelist: frozenset[str] | None,
    batch_size: int,
    dry_run: bool,
) -> dict[str, int]:
    """同步单天 IRM 数据。"""
    counters = {
        "total": 0,
        "replied": 0,
        "filtered_irm": 0,
        "whitelist_skip": 0,
        "saved": 0,
        "dup_skip": 0,
    }

    # 同步拉取
    records = await asyncio.to_thread(_fetch_day_irm, minishare_pro, trade_date)
    counters["total"] = len(records)

    if not records:
        return counters

    pending: list[dict] = []
    for rec in records:
        question = rec["q"]
        answer = rec["a"]
        if not question or not answer or question == "nan" or answer == "nan":
            continue

        counters["replied"] += 1

        # 关键词过滤
        if not should_save_irm(question, answer):
            counters["filtered_irm"] += 1
            continue

        # ts_code
        ts_code = rec["ts_code"]
        if not ts_code or "." not in ts_code:
            continue

        # 白名单过滤
        if whitelist is not None and ts_code not in whitelist:
            counters["whitelist_skip"] += 1
            continue

        # 解析日期
        exchange = _source_to_exchange(rec["source"])
        ann_date = _parse_trade_date(rec["trade_date"])
        if ann_date is None:
            continue

        # cninfo_id
        row_hash = rec.get("row_hash", "")
        cninfo_id = _generate_cninfo_id(ts_code, rec["trade_date"], row_hash)

        source_name = "上证e互动" if exchange == "SH" else "深证互动易"

        pending.append({
            "ann_date": ann_date,
            "ts_code": ts_code,
            "name": rec["name"] or None,
            "title": question[:500],
            "type": answer,
            "cninfo_id": cninfo_id,
            "announcement_type": f"irm:{exchange}",
            "source_type": "minishare",
            "source_name": source_name,
            "confidence_tier": "Tier2",
        })

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


async def get_latest_irm_date() -> str | None:
    """查询数据库中 IRM 数据的最新日期。"""
    from sqlalchemy import text
    async with engine.connect() as conn:
        r = await conn.execute(text(
            "SELECT MAX(ann_date) FROM announcements WHERE source_type LIKE 'irm%'"
        ))
        latest = r.scalar()
        if latest:
            return latest.strftime("%Y%m%d")
    return None


async def main(
    start_date_str: str | None = None,
    end_date_str: str | None = None,
    scope: str | None = None,
    batch_size: int = BATCH_SIZE,
    dry_run: bool = False,
) -> dict[str, Any]:
    """主函数"""
    if scope:
        os.environ["BACKFILL_SCOPE"] = scope
    from app.data_pipeline.backfill_config import reset_settings_cache
    reset_settings_cache()
    cfg = load_backfill_settings()

    start_time = time.time()

    # 确定日期范围
    if start_date_str:
        start_date = datetime.strptime(start_date_str, "%Y%m%d")
    else:
        # 默认：从数据库最新 IRM 日期的下一天开始
        latest = await get_latest_irm_date()
        if latest:
            start_date = datetime.strptime(latest, "%Y%m%d") + timedelta(days=1)
        else:
            start_date = datetime.strptime(cfg.start_date, "%Y%m%d")

    if end_date_str:
        end_date = datetime.strptime(end_date_str, "%Y%m%d")
    else:
        end_date = datetime.now()

    start_str = start_date.strftime("%Y%m%d")
    end_str = end_date.strftime("%Y%m%d")

    # 白名单
    whitelist: frozenset[str] | None = None
    if cfg.scope == "tech_mvp" and cfg.ts_codes:
        whitelist = cfg.ts_codes

    print(f"{'=' * 65}")
    print(f"  Minishare IRM 数据回补")
    print(f"{'=' * 65}")
    print(f"  日期范围:  {start_str} ~ {end_str}")
    print(f"  白名单:    {'tech_mvp (%d 只)' % len(whitelist) if whitelist else '全市场'}")
    print(f"  批量大小:  {batch_size}")
    print(f"  模式:      {'试运行 (dry-run)' if dry_run else '正式写入'}")
    print(f"  开始时间:  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    if start_date > end_date:
        print("  日期范围无效：起始日期 > 结束日期，无需同步")
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

    # 进度追踪
    tracker = IngestionProgressTracker(
        source="irm_minishare",
        task_name="irm_daily_backfill",
        scope=f"{start_str}_{end_str}",
    )
    if not dry_run:
        await tracker.ensure_tables()
        run_ctx = await tracker.start_run(
            from_watermark=start_str,
            to_watermark=end_str,
            metadata={"source": "minishare"},
        )

    # 逐日同步
    total_counters = {
        "total": 0, "replied": 0, "filtered_irm": 0,
        "whitelist_skip": 0, "saved": 0, "dup_skip": 0,
    }
    current = start_date
    days_done = 0

    while current <= end_date:
        date_str = current.strftime("%Y%m%d")
        result = await sync_day(date_str, minishare_pro, whitelist, batch_size, dry_run)

        for k in total_counters:
            total_counters[k] += result.get(k, 0)
        days_done += 1

        if result["total"] > 0 or result["saved"] > 0:
            logger.info(
                f"  {date_str}: total={result['total']}, saved={result['saved']}, "
                f"filtered={result['filtered_irm']}, wl_skip={result['whitelist_skip']}, "
                f"dup={result['dup_skip']}"
            )

        if not dry_run:
            await tracker.save_checkpoint(
                last_success_watermark=date_str,
                last_status="running",
            )

        current += timedelta(days=1)

    # 完成
    elapsed = int(time.time() - start_time)
    print()
    print(f"{'=' * 65}")
    print(f"  回补完成!")
    print(f"{'=' * 65}")
    print(f"  天数:         {days_done}")
    print(f"  总行数:       {total_counters['total']:,}")
    print(f"  已回复:       {total_counters['replied']:,}")
    print(f"  关键词过滤:   {total_counters['filtered_irm']:,}")
    print(f"  白名单跳过:   {total_counters['whitelist_skip']:,}")
    print(f"  新增入库:     {total_counters['saved']:,}")
    print(f"  重复跳过:     {total_counters['dup_skip']:,}")
    print(f"  总耗时:       {format_duration(elapsed)}")
    print(f"  完成时间:     {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    if not dry_run:
        await tracker.finish_run(
            run_ctx,
            status=SUCCESS if total_counters["saved"] > 0 or total_counters["total"] == 0 else PARTIAL,
            total_items=days_done,
            processed_items=days_done,
            success_count=total_counters["saved"],
            skipped_count=total_counters["filtered_irm"] + total_counters["whitelist_skip"] + total_counters["dup_skip"],
            downloaded_count=0,
            fail_count=0,
            current_watermark=end_str,
            last_item_id=end_str,
        )

    return total_counters


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Minishare IRM 数据回补")
    parser.add_argument("--start-date", help="起始日期 YYYYMMDD (默认: 数据库最新日期+1)")
    parser.add_argument("--end-date", help="结束日期 YYYYMMDD (默认: 今天)")
    parser.add_argument("--scope", choices=["tech_mvp", "all"], default=None,
                        help="覆盖 BACKFILL_SCOPE 配置")
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    parser.add_argument("--dry-run", action="store_true", help="试运行")
    args = parser.parse_args()

    asyncio.run(main(
        start_date_str=args.start_date,
        end_date_str=args.end_date,
        scope=args.scope,
        batch_size=args.batch_size,
        dry_run=args.dry_run,
    ))
