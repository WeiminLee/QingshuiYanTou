#!/usr/bin/env python3
"""
补下载公告 PDF

用法:
    python -m scripts.backfill_missing_pdfs --execute
    python -m scripts.backfill_missing_pdfs --limit 1000  # 限制数量
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text

from app.core.database import engine
from app.data_pipeline.backfill_config import load_backfill_settings
from app.data_pipeline.file_storage import FileStorage

BATCH_SIZE = 50
CONCURRENCY = 3
TIMEOUT_SEC = 20


async def download_one(storage, rec, sem):
    """下载单个 PDF"""
    async with sem:
        try:
            path = await asyncio.wait_for(
                storage.download_notice_async(
                    url=rec["pdf_url"],
                    ts_code=rec["ts_code"],
                    filename=f"{rec['cninfo_id']}.pdf",
                    pub_date=rec["ann_date"].replace("-", "")[:8],
                ),
                timeout=TIMEOUT_SEC,
            )
            return (str(path) if path else None, rec["cninfo_id"])
        except Exception:
            return (None, rec["cninfo_id"])


async def main(dry_run: bool = True, limit: int = 10000):
    print(f"{'=' * 60}")
    print("  补下载公告 PDF")
    print(f"{'=' * 60}")
    print(f"  模式: {'模拟运行' if dry_run else '实际执行'}")
    print()

    cfg = load_backfill_settings()
    whitelist = set(cfg.ts_codes) if cfg.scope == "tech_mvp" else None

    # 查询
    print("步骤 1: 查询待补记录...")
    async with engine.connect() as conn:
        r = await conn.execute(
            text("""
            SELECT cninfo_id, ts_code, ann_date::text, title, pdf_url
            FROM announcements
            WHERE file_path IS NULL
              AND pdf_url IS NOT NULL
              AND (announcement_type IS NULL OR announcement_type NOT LIKE 'irm:%')
            ORDER BY ann_date DESC
            LIMIT :limit
        """),
            {"limit": limit},
        )
        records = [dict(row._mapping) for row in r]

    print(f"  待补记录: {len(records):,}")
    if whitelist:
        records = [r for r in records if r["ts_code"] in whitelist]
        print(f"  白名单过滤: {len(records):,}")

    if not records:
        return

    # 下载
    print("\n步骤 2: 下载 PDF...")
    storage = FileStorage()
    sem = asyncio.Semaphore(CONCURRENCY)

    success = 0
    updates = []

    for i in range(0, len(records), BATCH_SIZE):
        batch = records[i : i + BATCH_SIZE]
        tasks = [download_one(storage, rec, sem) for rec in batch]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for rec, result in zip(batch, results):
            if isinstance(result, Exception):
                continue
            path, cid = result
            if path:
                updates.append((path, cid))
                success += 1

        print(f"    {min(i + BATCH_SIZE, len(records))}/{len(records)} (成功: {success})")

    # 更新
    print(f"\n步骤 3: 更新 {len(updates):,} 条...")
    if updates and not dry_run:
        async with engine.begin() as conn:
            for path, cid in updates:
                await conn.execute(
                    text("UPDATE announcements SET file_path = :fp WHERE cninfo_id = :cid"),
                    {"fp": path, "cid": cid},
                )

    print(f"\n{'=' * 60}")
    print(f"  完成! 成功: {success:,} 更新: {len(updates):,}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--limit", type=int, default=10000)
    args = parser.parse_args()

    asyncio.run(main(dry_run=not args.execute, limit=args.limit))
