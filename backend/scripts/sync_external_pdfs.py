#!/usr/bin/env python3
"""
同步外部硬盘上的 PDF 文件到数据库 (高效版)

使用批量 SQL 匹配，不逐条查询数据库。

用法:
    python -m scripts.sync_external_pdfs --execute
"""

import argparse
import asyncio
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text

from app.core.database import engine
from app.data_pipeline.backfill_config import load_backfill_settings

EXTERNAL_DIR = Path("/run/media/lwm/0E27099B0E27099B/qingshui_data/notices")


def parse_pdf_path(pdf_path: Path) -> dict | None:
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
        cninfo_id = None
        title = filename

        if filename.startswith("ann_"):
            match = re.match(r"ann_([a-f0-9]{16})_(.*)", filename, re.IGNORECASE)
            if match:
                cninfo_id = match.group(1)
                title = match.group(2)
            else:
                parts_fname = filename.split("_", 2)
                if len(parts_fname) >= 3:
                    cninfo_id = parts_fname[1]
                    title = parts_fname[2]

        return {
            "ts_code": ts_code,
            "date_dir": date_dir,
            "cninfo_id": cninfo_id,
            "title": title,
            "full_path": str(pdf_path),
        }
    except Exception:
        return None


async def scan_external_pdfs() -> list[dict]:
    """扫描外部硬盘上的所有 PDF"""
    pdfs = []

    if not EXTERNAL_DIR.exists():
        print(f"警告: 外部目录不存在: {EXTERNAL_DIR}")
        return pdfs

    for pdf_path in EXTERNAL_DIR.rglob("*.pdf"):
        info = parse_pdf_path(pdf_path)
        if info:
            pdfs.append(info)

    return pdfs


async def batch_update(pdfs: list[dict], dry_run: bool = True) -> tuple[int, int]:
    """批量更新数据库

    Returns:
        (found_count, updated_count)
    """
    cfg = load_backfill_settings()
    whitelist = set(cfg.ts_codes) if cfg.scope == "tech_mvp" else None

    # 过滤白名单
    if whitelist:
        pdfs = [p for p in pdfs if p["ts_code"] in whitelist]

    # 构建 ts_code + date_dir + title 前缀 作为匹配键
    # 使用 ts_code + date_dir + title 的 hash 作为唯一标识
    import hashlib

    keys = {}
    for pdf in pdfs:
        # 标准化标题用于匹配
        title_normalized = re.sub(r"[\s\-_]+", "", pdf["title"])[:30]
        key = f"{pdf['ts_code']}|{pdf['date_dir']}|{title_normalized}"
        key_hash = hashlib.md5(key.encode()).hexdigest()[:16]

        # 存储原始数据
        if key_hash not in keys:
            keys[key_hash] = {
                "key": key,
                "ts_code": pdf["ts_code"],
                "date_dir": pdf["date_dir"],
                "title_normalized": title_normalized,
                "paths": [],
            }
        keys[key_hash]["paths"].append(pdf["full_path"])

    print(f"  去重后唯一键: {len(keys)}")

    # 批量查询匹配的公告
    found = 0
    updated = 0

    # 分批处理
    batch_size = 1000
    key_list = list(keys.items())

    for batch_start in range(0, len(key_list), batch_size):
        batch_end = min(batch_start + batch_size, len(key_list))
        batch = key_list[batch_start:batch_end]

        # 构建查询: 用 ts_code IN (...) AND date >= ... AND date <= ...
        ts_codes = list(set(k[1]["ts_code"] for k in batch))
        date_ranges = [(k[1]["ts_code"], k[1]["date_dir"]) for k in batch]

        # 用 ts_code + title 模糊匹配
        async with engine.begin() as conn:
            for key_hash, info in batch:
                ts_code = info["ts_code"]
                date_dir = info["date_dir"]
                title_pattern = f"%{info['title_normalized'][:20]}%"

                # 日期范围
                year, month = map(int, date_dir.split("-"))
                from calendar import monthrange

                last_day = monthrange(year, month)[1]
                date_start = datetime(year, month, 1).date()
                date_end = datetime(year, month, last_day).date()

                result = await conn.execute(
                    text("""
                        SELECT cninfo_id, title
                        FROM announcements
                        WHERE ts_code = :ts_code
                          AND ann_date >= :date_start
                          AND ann_date <= :date_end
                          AND title LIKE :title_pattern
                          AND file_path IS NULL
                        LIMIT 1
                    """),
                    {
                        "ts_code": ts_code,
                        "date_start": date_start,
                        "date_end": date_end,
                        "title_pattern": title_pattern,
                    },
                )
                row = result.fetchone()

                if row:
                    found += 1
                    if not dry_run:
                        # 更新为第一个路径
                        await conn.execute(
                            text("UPDATE announcements SET file_path = :fp WHERE cninfo_id = :cid"),
                            {"fp": info["paths"][0], "cid": row[0]},
                        )
                        updated += 1

        if (batch_end) % 5000 == 0 or batch_end == len(key_list):
            print(f"  处理进度: {batch_end}/{len(key_list)} (找到: {found}, 更新: {updated})")

    return found, updated


async def main(dry_run: bool = True):
    print(f"{'=' * 60}")
    print("  同步外部硬盘 PDF 到数据库 (高效版)")
    print(f"{'=' * 60}")
    print(f"  外部目录: {EXTERNAL_DIR}")
    print(f"  模式: {'模拟运行' if dry_run else '实际更新'}")
    print()

    # 1. 扫描
    print("扫描外部硬盘 PDF...")
    pdfs = await scan_external_pdfs()
    print(f"  找到 {len(pdfs)} 个 PDF 文件")

    if not pdfs:
        return

    ts_codes = set(p["ts_code"] for p in pdfs)
    print(f"  涉及股票: {len(ts_codes)} 只")

    # 2. 批量更新
    print()
    print("匹配数据库记录...")
    found, updated = await batch_update(pdfs, dry_run=dry_run)

    print()
    print(f"{'=' * 60}")
    print("  完成!")
    print(f"{'=' * 60}")
    print(f"  扫描 PDF: {len(pdfs)}")
    print(f"  匹配记录: {found}")
    if dry_run:
        print(f"  预计更新: {updated}")
    else:
        print(f"  实际更新: {updated}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="同步外部硬盘 PDF 到数据库")
    parser.add_argument("--dry-run", action="store_true", default=True, help="模拟运行，不实际更新数据库")
    parser.add_argument("--execute", action="store_true", help="实际执行更新")
    args = parser.parse_args()

    asyncio.run(main(dry_run=not args.execute))
