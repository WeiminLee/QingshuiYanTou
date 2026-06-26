#!/usr/bin/env python3
"""
修复 PDF 路径问题 - 优化版

直接 SQL 操作，高效处理

用法:
    python -m scripts.fix_pdf_paths --execute
"""

import argparse
import asyncio
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text

from app.core.database import engine
from app.data_pipeline.backfill_config import load_backfill_settings

EXTERNAL_DIR = Path("/run/media/lwm/0E27099B0E27099B/qingshui_data/notices")


def parse_pdf(pdf_path: Path) -> dict | None:
    """从 PDF 路径解析元信息。"""
    try:
        parts = pdf_path.parts
        if len(parts) < 3:
            return None

        ts_code = parts[-3]
        date_dir = parts[-2]

        if not re.match(r"\d{4}-\d{2}", date_dir):
            return None

        filename = pdf_path.stem
        title = filename

        if filename.startswith("ann_"):
            parts_fn = filename.split("_", 2)
            if len(parts_fn) >= 3:
                title = parts_fn[2]

        return (ts_code, date_dir, title[:40], str(pdf_path))
    except Exception:
        return None


async def main(dry_run: bool = True):
    print(f"{'=' * 65}")
    print("  修复 PDF 路径问题")
    print(f"{'=' * 65}")
    print(f"  模式: {'模拟运行' if dry_run else '实际执行'}")
    print()

    # ========== 步骤 1: 清空无效内网路径 ==========
    print("步骤 1: 清空无效内网路径...")

    async with engine.begin() as conn:
        # 快速验证几个路径
        r = await conn.execute(
            text("""
            SELECT file_path FROM announcements WHERE file_path LIKE '/home/lwm/%' LIMIT 3
        """)
        )
        samples = [row[0] for row in r]

    if samples:
        exists = sum(1 for p in samples if Path(p).exists())
        print(f"  验证: {exists}/3 个存在")

        if exists == 0:
            print("  所有内网路径无效，清空...")
            if not dry_run:
                async with engine.begin() as conn:
                    r = await conn.execute(
                        text("""
                        UPDATE announcements SET file_path = NULL WHERE file_path LIKE '/home/lwm/%'
                    """)
                    )
                    print(f"  已清空 {r.rowcount:,} 条")

    # ========== 步骤 2: 批量匹配外部 PDF ==========
    print("\n步骤 2: 扫描外部硬盘...")

    cfg = load_backfill_settings()
    whitelist = set(cfg.ts_codes) if cfg.scope == "tech_mvp" else None

    # 扫描
    pdfs = []
    for pdf_path in EXTERNAL_DIR.rglob("*.pdf"):
        info = parse_pdf(pdf_path)
        if info:
            if whitelist and info[0] not in whitelist:
                continue
            pdfs.append(info)

    print(f"  外部 PDF: {len(pdfs):,}")

    # 构建 hash 索引: (ts_code, year_month, title[:20]) -> path
    index = {}
    for ts_code, date_dir, title, path in pdfs:
        key = (ts_code, date_dir, title[:20])
        if key not in index:
            index[key] = path

    print(f"  索引大小: {len(index):,}")

    # ========== 步骤 3: 批量更新 ==========
    print("\n步骤 3: 匹配并更新...")

    # 一次查询所有需要更新的记录
    async with engine.connect() as conn:
        r = await conn.execute(
            text("""
            SELECT cninfo_id, ts_code, TO_CHAR(ann_date, 'YYYY-MM') as ym, LEFT(title, 40)
            FROM announcements
            WHERE file_path IS NULL AND title IS NOT NULL
        """)
        )
        records = [(row[0], row[1], row[2], row[3] or "") for row in r]

    print(f"  待匹配记录: {len(records):,}")

    # 批量匹配
    updates = []
    matched = 0

    for cninfo_id, ts_code, ym, title in records:
        key = (ts_code, ym, title[:20])
        if key in index:
            updates.append((index[key], cninfo_id))
            matched += 1

    print(f"  匹配成功: {matched:,}")

    # 批量更新
    if updates and not dry_run:
        print(f"\n  执行批量更新 {len(updates):,} 条...")
        async with engine.begin() as conn:
            for path, cid in updates:
                await conn.execute(
                    text("UPDATE announcements SET file_path = :fp WHERE cninfo_id = :cid"),
                    {"fp": path, "cid": cid},
                )
        print(f"  已更新 {len(updates):,} 条")

    print()
    print(f"{'=' * 65}")
    print("  完成!")
    print(f"{'=' * 65}")
    print(f"  匹配更新: {matched:,}")
    if not dry_run:
        print(f"  实际更新: {len(updates):,}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="修复 PDF 路径")
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    asyncio.run(main(dry_run=not args.execute))
