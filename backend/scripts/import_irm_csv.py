#!/usr/bin/env python3
"""
IRM CSV 数据导入脚本

从 tushare CSV 文件导入 IRM 历史数据到 announcements 表。
导入后所有数据使用统一的 source_type = "minishare"。

数据格式：source, ts_code, name, trade_date, pub_time, industry, q, a, row_hash
日期范围：2010-10-10 ~ 2026-05-22

去重策略：
- 基于 cninfo_id（irm_{exchange}_{ts_code}_{trade_date}_{row_hash[:16]}）
- ON CONFLICT (cninfo_id) DO NOTHING

用法:
    # 干跑测试（不写入）
    python -m scripts.import_irm_csv --dry-run

    # 正式导入（默认 tech_mvp 白名单）
    python -m scripts.import_irm_csv

    # 全市场导入
    python -m scripts.import_irm_csv --scope all
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

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

CHUNK_SIZE = 10_000
BATCH_SIZE = 500
DEFAULT_CSV_FILE = "/home/lwm/irm-_new_data/tushare_irm_qa_all.csv"


def _source_to_exchange(source: str) -> str:
    """source 字段 → 交易所代码"""
    if not source:
        return "SZ"
    if "sh" in source.lower():
        return "SH"
    return "SZ"


def _parse_trade_date(trade_date) -> datetime.date | None:
    """解析 trade_date（YYYYMMDD）为 date 对象"""
    if not trade_date:
        return None
    s = str(trade_date).strip()
    try:
        return datetime.strptime(s[:8], "%Y%m%d").date()
    except ValueError:
        return None


def _generate_cninfo_id(ts_code: str, trade_date: str, row_hash: str, exchange: str) -> str:
    """生成唯一 cninfo_id

    格式: irm_{exchange}_{ts_code}_{trade_date}_{row_hash[:16]}
    """
    hash_part = row_hash[:16] if row_hash else "unknown"
    return f"irm_{exchange}_{ts_code}_{trade_date}_{hash_part}"


async def _batch_insert(records: list[dict]) -> tuple[int, int]:
    """批量 INSERT，返回 (saved, dup_skipped)"""
    if not records:
        return 0, 0

    stmt = pg_insert(Announcement.__table__).values(records)
    # 使用 (ts_code, ann_date, title) 唯一约束去重
    stmt = stmt.on_conflict_do_nothing(index_elements=["ts_code", "ann_date", "title"])

    try:
        async with engine.begin() as conn:
            result = await conn.execute(stmt)
            saved = result.rowcount if result.rowcount else 0
            return saved, len(records) - saved
    except Exception as e:
        logger.warning(f"批量插入失败: {e}")
        return 0, len(records)


async def sync_csv(
    csv_path: str,
    whitelist: frozenset[str] | None,
    batch_size: int,
    dry_run: bool,
) -> dict[str, int]:
    """同步 CSV 格式的 IRM 数据"""
    import pandas as pd

    counters = {
        "total": 0,
        "replied": 0,
        "filtered_irm": 0,
        "whitelist_skip": 0,
        "saved": 0,
        "dup_skip": 0,
    }
    pending: list[dict] = []

    logger.info(f"读取: {csv_path}")

    for chunk_idx, chunk in enumerate(pd.read_csv(csv_path, chunksize=CHUNK_SIZE)):
        chunk_len = len(chunk)
        counters["total"] += chunk_len

        for _, row in chunk.iterrows():
            question = str(row.get("q", "")).strip()
            answer = str(row.get("a", "")).strip()
            if not question or not answer or question == "nan" or answer == "nan":
                continue

            counters["replied"] += 1

            if not should_save_irm(question, answer):
                counters["filtered_irm"] += 1
                continue

            ts_code = str(row.get("ts_code", "")).strip()
            if not ts_code or "." not in ts_code:
                continue

            if whitelist is not None and ts_code not in whitelist:
                counters["whitelist_skip"] += 1
                continue

            source = str(row.get("source", "")).strip()
            exchange = _source_to_exchange(source)

            trade_date = row.get("trade_date")
            ann_date = _parse_trade_date(trade_date)
            if ann_date is None:
                continue

            trade_date_str = str(trade_date).strip()
            row_hash = str(row.get("row_hash", "")).strip()
            cninfo_id = _generate_cninfo_id(ts_code, trade_date_str, row_hash, exchange)

            source_name = "上证e互动" if exchange == "SH" else "深证互动易"

            pending.append({
                "ann_date": ann_date,
                "ts_code": ts_code,
                "name": str(row.get("name", "")).strip() or None,
                "title": question[:500],
                "type": answer,
                "cninfo_id": cninfo_id,
                "announcement_type": f"irm:{exchange}",
                "source_type": "minishare",
                "source_name": source_name,
                "confidence_tier": "Tier2",
            })

        if not dry_run and pending:
            for i in range(0, len(pending), batch_size):
                batch = pending[i : i + batch_size]
                saved, dup = await _batch_insert(batch)
                counters["saved"] += saved
                counters["dup_skip"] += dup
            pending.clear()
        elif dry_run:
            counters["saved"] += len(pending)
            pending.clear()

        if chunk_idx % 10 == 0:
            logger.info(f"  chunk {chunk_idx}: total={counters['total']:,}, saved={counters['saved']:,}")

    if not dry_run and pending:
        for i in range(0, len(pending), batch_size):
            batch = pending[i : i + batch_size]
            saved, dup = await _batch_insert(batch)
            counters["saved"] += saved
            counters["dup_skip"] += dup

    return counters


async def main(
    csv_file: str = DEFAULT_CSV_FILE,
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

    whitelist: frozenset[str] | None = None
    if cfg.scope == "tech_mvp" and cfg.ts_codes:
        whitelist = cfg.ts_codes

    print(f"{'=' * 65}")
    print(f"  IRM CSV 数据导入")
    print(f"{'=' * 65}")
    print(f"  CSV 文件: {csv_file}")
    print(f"  白名单:   {'tech_mvp (%d 只)' % len(whitelist) if whitelist else '全市场'}")
    print(f"  模式:     {'试运行 (dry-run)' if dry_run else '正式写入'}")
    print(f"  开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    start_time = time.time()
    result = await sync_csv(csv_file, whitelist, batch_size, dry_run)
    elapsed = int(time.time() - start_time)

    print()
    print(f"{'=' * 65}")
    print(f"  导入完成!")
    print(f"{'=' * 65}")
    print(f"  总行数:     {result['total']:,}")
    print(f"  已回复:     {result['replied']:,}")
    print(f"  关键词过滤: {result['filtered_irm']:,}")
    print(f"  白名单跳过: {result['whitelist_skip']:,}")
    print(f"  新增入库:   {result['saved']:,}")
    print(f"  重复跳过:   {result['dup_skip']:,}")
    print(f"  总耗时:     {elapsed}s")
    print(f"  完成时间:   {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="IRM CSV 导入")
    parser.add_argument(
        "--csv-file",
        default=DEFAULT_CSV_FILE,
        help=f"CSV 文件路径 (默认: {DEFAULT_CSV_FILE})",
    )
    parser.add_argument(
        "--scope",
        choices=["tech_mvp", "all"],
        default=None,
        help="覆盖 BACKFILL_SCOPE 配置 (默认: tech_mvp)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=BATCH_SIZE,
        help=f"批量 INSERT 行数 (默认: {BATCH_SIZE})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="试运行：只统计不写入",
    )
    args = parser.parse_args()

    asyncio.run(main(
        csv_file=args.csv_file,
        scope=args.scope,
        batch_size=args.batch_size,
        dry_run=args.dry_run,
    ))
