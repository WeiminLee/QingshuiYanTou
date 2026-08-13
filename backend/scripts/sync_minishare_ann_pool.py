#!/usr/bin/env python3
"""
Minishare 公告历史数据回补脚本（改进并发版）

改进点：
1. RateLimiter 替代全局锁：API 调用限速 100 次/分钟，但不阻塞 PDF 下载
2. 同一股票内 PDF 并发下载：先批量保存元数据，再用 asyncio.gather 并发下载 PDF
3. 去重机制不变：ON CONFLICT DO NOTHING + 股票级跳过

用法:
    python -m scripts.sync_minishare_ann_pool --concurrency 8
    python -m scripts.sync_minishare_ann_pool --start-date 20250601 --end-date 20250630
    python -m scripts.sync_minishare_ann_pool --dry-run
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

from app.data_pipeline.announcement_filter import (
    DOC_TYPE_SAVE as ANN_DOC_TYPE_SAVE,
    classify_title as classify_ann_title,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

DEFAULT_CONCURRENCY = 20
API_RATE_PER_MINUTE = 300  # minishare API 限速


# ── Rate Limiter ──────────────────────────────────────────


class RateLimiter:
    """Token bucket 限速器，确保 API 调用不超过指定速率。"""

    def __init__(self, max_per_minute: int):
        self.interval = 60.0 / max_per_minute
        self._next_available = 0.0
        self._lock = asyncio.Lock()

    async def wait(self):
        async with self._lock:
            now = time.monotonic()
            if now < self._next_available:
                await asyncio.sleep(self._next_available - now)
            self._next_available = max(now, self._next_available) + self.interval


# ── 辅助函数 ──────────────────────────────────────────────


def _get_exchange(ts_code: str) -> str:
    return "SH" if ts_code.endswith(".SH") else "SZ"


# ── 数据库操作 ────────────────────────────────────────────


async def load_candidate_pool_codes() -> list[str]:
    from sqlalchemy import text
    from app.core.database import engine

    async with engine.connect() as conn:
        rows = await conn.execute(
            text("SELECT ts_code FROM candidate_pool WHERE is_active = true ORDER BY ts_code")
        )
        return [row[0] for row in rows.fetchall()]


async def get_processed_stocks() -> set[str]:
    """获取已在 minishare_announcements 中有数据的股票列表（股票级去重）。"""
    from sqlalchemy import text
    from app.core.database import engine

    async with engine.connect() as conn:
        rows = await conn.execute(
            text("SELECT DISTINCT ts_code FROM minishare_announcements")
        )
        return {row[0] for row in rows.fetchall()}


async def get_failed_records() -> dict[str, list[dict]]:
    """获取下载失败的公告记录，按股票代码分组。

    返回 {ts_code: [{url, title, ann_date, doc_type}, ...]}
    """
    from sqlalchemy import text
    from app.core.database import engine

    async with engine.connect() as conn:
        rows = await conn.execute(
            text("""
                SELECT ts_code, source_url, title, ann_date, ann_types
                FROM minishare_announcements
                WHERE download_status = 'failed' OR file_path IS NULL
                ORDER BY ts_code, ann_date
            """)
        )
    result: dict[str, list[dict]] = {}
    for row in rows.fetchall():
        ts_code = row[0]
        if ts_code not in result:
            result[ts_code] = []
        result[ts_code].append({
            "url": row[1] or "",
            "title": row[2] or "",
            "ann_date": row[3].strftime("%Y%m%d") if row[3] else "",
            "doc_type": row[4] or "",
        })
    return result


async def retry_failed_stock(
    ts_code: str,
    records: list[dict],
    fetcher: Any,
) -> dict[str, int]:
    """重试单只股票的失败 PDF 下载。

    只下载 PDF，不调用 API 获取列表，不保存元数据。
    """
    counters = {"retry_total": len(records), "pdf_ok": 0, "pdf_fail": 0, "skipped": 0}

    async def _download_one(rec: dict) -> bool:
        url = rec.get("url", "")
        if not url:
            return False
        try:
            result = await fetcher._download_minishare_pdf(
                url=url,
                ts_code=ts_code,
                title=rec["title"],
                ann_date=rec["ann_date"],
                doc_type=rec.get("doc_type", ""),
            )
            return result
        except Exception as e:
            logger.warning("%s 重试 PDF 下载失败 [%s]: %s", ts_code, rec["title"][:40], e)
            return False

    results = await asyncio.gather(
        *[_download_one(rec) for rec in records],
        return_exceptions=True,
    )
    for ok in results:
        if ok is True:
            counters["pdf_ok"] += 1
        else:
            counters["pdf_fail"] += 1

    return counters


# ── 单股票同步 ────────────────────────────────────────────


async def sync_stock(
    ts_code: str,
    minishare_pro: Any,
    fetcher: Any | None,
    start_date: str,
    end_date: str,
    dry_run: bool,
    rate_limiter: RateLimiter,
) -> dict[str, int]:
    """同步单只股票的公告数据。"""
    counters = {"fetched": 0, "filtered": 0, "saved": 0, "dup_skip": 0, "error": 0, "pdf_ok": 0, "pdf_fail": 0}

    try:
        # 限速：等待 API 调用许可（不阻塞 PDF 下载）
        await rate_limiter.wait()
        df = minishare_pro.anns_d(
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date,
            limit=5000,
            offset=0,
        )
    except Exception as e:
        logger.warning("%s API 调用失败: %s", ts_code, e)
        counters["error"] += 1
        return counters

    if df is None or len(df) == 0:
        return counters

    records = []
    for _, row in df.iterrows():
        ann_date = str(row.get("ann_date", "")).strip()
        title = str(row.get("title", "")).strip()
        if not ann_date or not title:
            continue
        records.append({
            "ann_date": ann_date,
            "ts_code": ts_code,
            "name": str(row.get("name", "")),
            "title": title,
            "type": str(row.get("type", "")),
            "ann_types": str(row.get("ann_types", "")),
            "url": str(row.get("url", "")),
        })

    counters["fetched"] = len(records)

    # 关键词过滤
    filtered_records = []
    for rec in records:
        doc_type, action = classify_ann_title(rec["title"])
        if action == ANN_DOC_TYPE_SAVE:
            rec["doc_type"] = doc_type
            filtered_records.append(rec)
        else:
            counters["filtered"] += 1

    if not filtered_records:
        return counters

    # 试运行模式：只统计
    if dry_run:
        counters["saved"] = len(filtered_records)
        return counters

    # ── 第 1 步：批量保存元数据（不下载 PDF，快速） ──
    new_records = []
    for rec in filtered_records:
        try:
            result = await fetcher._save_minishare_ann(rec, ts_code, skip_download=True)
            if result is True:
                counters["saved"] += 1
                new_records.append(rec)
            elif result is None:
                counters["dup_skip"] += 1
            else:
                counters["error"] += 1
        except Exception as e:
            logger.warning("%s 保存元数据失败: %s", ts_code, e)
            counters["error"] += 1

    # ── 第 2 步：并发下载所有新记录的 PDF ──
    if new_records:
        async def _download_one(rec: dict) -> bool:
            url = rec.get("url", "")
            if not url:
                return False
            try:
                result = await fetcher._download_minishare_pdf(
                    url=url,
                    ts_code=ts_code,
                    title=rec["title"],
                    ann_date=rec["ann_date"],
                    doc_type=rec.get("doc_type", rec.get("type", "")),
                )
                return result
            except Exception as e:
                logger.warning("%s PDF 下载失败 [%s]: %s", ts_code, rec["title"][:40], e)
                return False

        results = await asyncio.gather(
            *[_download_one(rec) for rec in new_records],
            return_exceptions=True,
        )
        for ok in results:
            if ok is True:
                counters["pdf_ok"] += 1
            else:
                counters["pdf_fail"] += 1

    return counters


# ── 主函数 ────────────────────────────────────────────────


def format_duration(seconds: int) -> str:
    h, remainder = divmod(seconds, 3600)
    m, s = divmod(remainder, 60)
    return f"{h}:{m:02d}:{s:02d}"


async def main(
    start_date_str: str | None = None,
    end_date_str: str | None = None,
    concurrency: int = DEFAULT_CONCURRENCY,
    dry_run: bool = False,
    limit: int = 0,
    retry_only: bool = False,
) -> dict[str, Any]:
    """主函数"""
    start_time = time.time()

    start_date = start_date_str or "20250101"
    end_date = end_date_str or datetime.now().strftime("%Y%m%d")

    pool_codes = await load_candidate_pool_codes()
    sz_codes = [c for c in pool_codes if c.endswith(".SZ")]
    sh_codes = [c for c in pool_codes if c.endswith(".SH")]

    # 已处理的股票（跳过，避免重复 API 调用）
    processed = await get_processed_stocks()
    unprocessed = [c for c in pool_codes if c not in processed and (c.endswith(".SZ") or c.endswith(".SH"))]
    if limit and limit > 0:
        unprocessed = unprocessed[:limit]
    already_done = len(pool_codes) - len(unprocessed) - len([c for c in pool_codes if not (c.endswith(".SZ") or c.endswith(".SH"))])

    print(f"{'=' * 65}")
    print("  Minishare 公告数据回补（改进并发版）")
    print(f"{'=' * 65}")
    print(f"  日期范围:  {start_date} ~ {end_date}")
    print(f"  候选池:    {len(pool_codes)} 只 (SZ: {len(sz_codes)}, SH: {len(sh_codes)})")
    print(f"  已处理:    {already_done} 只")
    print(f"  待处理:    {len(unprocessed)} 只")
    print(f"  并发数:    {concurrency}")
    print(f"  API 限速:  {API_RATE_PER_MINUTE} 次/分钟")
    if retry_only:
        print(f"  模式:      {'重试下载失败的 PDF (试运行)' if dry_run else '重试下载失败的 PDF'}")
    else:
        print(f"  模式:      {'试运行 (dry-run)' if dry_run else '正式写入 + PDF 下载'}")
    print(f"  开始时间:  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    # ── 第 1 阶段：重试下载失败的 PDF ──
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
    anns_token = os.getenv("MINISHARE_ANNS_TOKEN", "")
    if not anns_token:
        print("  错误: MINISHARE_ANNS_TOKEN 未配置")
        return {}

    fetcher = None
    if not dry_run:
        from app.data_pipeline.fetcher import DataFetcher
        fetcher = DataFetcher()

    retry_records = await get_failed_records()
    retry_stocks = list(retry_records.keys())
    total_retry_records = sum(len(v) for v in retry_records.values())
    total_retry = {"pdf_ok": 0, "pdf_fail": 0}

    if retry_stocks and not dry_run:
        print(f"{'─' * 65}")
        print(f"  第 1 阶段: 重试下载失败的 PDF")
        print(f"  {len(retry_stocks)} 只股票, {total_retry_records} 条记录")
        print(f"  并发数:     {concurrency}")
        print(f"{'─' * 65}")
        print()

        sem = asyncio.Semaphore(concurrency)
        start_retry = time.time()

        async def retry_one(ts_code: str) -> dict[str, int]:
            async with sem:
                return await retry_failed_stock(ts_code, retry_records[ts_code], fetcher)

        retry_tasks = {asyncio.create_task(retry_one(ts_code)): ts_code for ts_code in retry_stocks}
        retry_pending = set(retry_tasks.keys())
        retry_done = 0

        while retry_pending:
            done_set, retry_pending = await asyncio.wait(
                retry_pending, return_when=asyncio.FIRST_COMPLETED
            )
            for task in done_set:
                try:
                    result = task.result()
                except Exception as e:
                    logger.error("重试任务异常: %s", e)
                    continue
                ts_code = retry_tasks[task]
                retry_done += 1
                for k in total_retry:
                    total_retry[k] += result.get(k, 0)
                if retry_done % 10 == 0:
                    logger.info(
                        f"[重试 {retry_done}/{len(retry_stocks)}] {ts_code}: "
                        f"PDF成功={result['pdf_ok']}, PDF失败={result['pdf_fail']}, "
                        f"跳过={result['skipped']}"
                    )

        retry_elapsed = int(time.time() - start_retry)
        print(f"  重试完成:  PDF成功={total_retry['pdf_ok']}, PDF失败={total_retry['pdf_fail']}, "
              f"耗时={format_duration(retry_elapsed)}")
        print()

    if retry_stocks and dry_run:
        print(f"  试运行: 共 {len(retry_stocks)} 只股票, {total_retry_records} 条记录等待重试下载")
        print()

    # ── 第 2 阶段：处理新股票 ──
    if retry_only:
        print("  --retry 模式: 仅重试下载失败的 PDF，跳过新股票处理")
        elapsed = int(time.time() - start_time)
        print()
        print(f"{'=' * 65}")
        print("  全部完成!")
        print(f"{'=' * 65}")
        if retry_stocks and not dry_run:
            print(f"  重试补下载: {len(retry_stocks)} 只股票, {total_retry_records} 条记录")
            print(f"  重试PDF成功: {total_retry['pdf_ok']:,} 条")
            print(f"  重试PDF失败: {total_retry['pdf_fail']:,} 条")
        print(f"  总耗时:     {format_duration(elapsed)}")
        print(f"  完成时间:   {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        return {}
    if not unprocessed:
        print("  所有股票已处理完毕，无需同步新股票")

        # 但仍有重试阶段的统计需要输出
        elapsed = int(time.time() - start_time)
        print()
        print(f"{'=' * 65}")
        print("  全部完成!")
        print(f"{'=' * 65}")
        if retry_stocks and not dry_run:
            print(f"  重试补下载: {len(retry_stocks)} 只股票, {total_retry_records} 条记录")
            print(f"  重试PDF成功: {total_retry['pdf_ok']:,} 条")
            print(f"  重试PDF失败: {total_retry['pdf_fail']:,} 条")
        print(f"  总耗时:     {format_duration(elapsed)}")
        print(f"  完成时间:   {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        return {}

    import minishare as ms
    minishare_pro = ms.pro_api(anns_token)

    total = {"fetched": 0, "filtered": 0, "saved": 0, "dup_skip": 0, "error": 0, "pdf_ok": 0, "pdf_fail": 0}
    rate_limiter = RateLimiter(API_RATE_PER_MINUTE)
    sem = asyncio.Semaphore(concurrency)

    async def sync_one(ts_code: str) -> dict[str, int]:
        async with sem:
            return await sync_stock(ts_code, minishare_pro, fetcher, start_date, end_date, dry_run, rate_limiter)

    tasks = {asyncio.create_task(sync_one(ts_code)): ts_code for ts_code in unprocessed}
    pending = set(tasks.keys())
    total_tasks = len(pending)
    done_count = 0

    # 进度追踪
    while pending:
        done_set, pending = await asyncio.wait(
            pending, return_when=asyncio.FIRST_COMPLETED
        )
        for task in done_set:
            try:
                result = task.result()
            except Exception as e:
                logger.error("任务异常: %s", e)
                continue
            ts_code = tasks[task]
            done_count += 1

            for k in total:
                total[k] += result.get(k, 0)

            # 每 10 只打印一次进度
            if done_count % 10 == 0:
                elapsed = int(time.time() - start_time)
                rate = done_count / (elapsed or 1) * 60
                est_rem = (len(unprocessed) - done_count) / (rate or 1)
                logger.info(
                    f"[{done_count}/{len(unprocessed)}] {ts_code}: "
                    f"获取={result['fetched']}, 保存={result['saved']}, 过滤={result['filtered']}, "
                    f"PDF成功={result['pdf_ok']}, PDF失败={result['pdf_fail']}, 错误={result['error']} | "
                    f"速率: {rate:.0f}只/分, 预计剩余: {est_rem:.0f}分"
                )

    # 完成
    elapsed = int(time.time() - start_time)
    print()
    print(f"{'=' * 65}")
    print("  回补完成!")
    print(f"{'=' * 65}")
    if retry_stocks and not dry_run:
        print(f"  重试补下载: {len(retry_stocks)} 只股票, {total_retry_records} 条记录")
        print(f"  重试PDF成功: {total_retry['pdf_ok']:,} 条")
        print(f"  重试PDF失败: {total_retry['pdf_fail']:,} 条")
        print(f"{'─' * 65}")
    print(f"  处理股票:   {len(unprocessed)}")
    print(f"  API获取:    {total['fetched']:,} 条")
    print(f"  关键词过滤: {total['filtered']:,} 条")
    print(f"  新增入库:   {total['saved']:,} 条")
    print(f"  重复跳过:   {total['dup_skip']:,} 条")
    print(f"  PDF下载成功: {total['pdf_ok']:,} 条")
    print(f"  PDF下载失败: {total['pdf_fail']:,} 条")
    print(f"  错误:       {total['error']} 只")
    print(f"  总耗时:     {format_duration(elapsed)}")
    print(f"  完成时间:   {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    return total


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Minishare 公告数据回补（改进并发版）")
    parser.add_argument("--start-date", help="起始日期 YYYYMMDD (默认: 20250101)")
    parser.add_argument("--end-date", help="结束日期 YYYYMMDD (默认: 今天)")
    parser.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY, help="并发数 (默认: 10)")
    parser.add_argument("--dry-run", action="store_true", help="试运行")
    parser.add_argument("--limit", type=int, default=0, help="限制处理的股票数量 (0=不限制)")
    parser.add_argument("--retry", action="store_true", help="仅重试下载失败的 PDF，不处理新股票")
    args = parser.parse_args()

    asyncio.run(
        main(
            start_date_str=args.start_date,
            end_date_str=args.end_date,
            concurrency=args.concurrency,
            dry_run=args.dry_run,
            limit=args.limit,
            retry_only=args.retry,
        )
    )
