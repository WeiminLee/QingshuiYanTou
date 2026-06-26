#!/usr/bin/env python3
"""
同步外部硬盘 PDF 到数据库 - 完整版

策略：
1. 扫描外部硬盘所有 PDF，构建 ts_code + title 索引
2. 查询数据库中有旧路径（内网/不存在）的记录
3. 用 ts_code + ann_date + title 匹配，更新 file_path

用法:
    python -m scripts.sync_pdfs_to_external --execute
"""

import argparse
import asyncio
import re
import sys
from collections import defaultdict
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
        date_dir = parts[-2]  # YYYY-MM

        if not re.match(r"\d{4}-\d{2}", date_dir):
            return None

        filename = pdf_path.stem
        cninfo_id = None
        title = filename

        # 解析 ann_xxxx_xxx 格式
        if filename.startswith("ann_"):
            # ann_{hash16}_{title} 或 ann_{cninfo_id}_{title}
            parts_fn = filename.split("_", 2)
            if len(parts_fn) >= 3:
                cninfo_id = parts_fn[1]
                title = parts_fn[2]

        return {
            "ts_code": ts_code,
            "date_dir": date_dir,
            "cninfo_id": cninfo_id,
            "title": title,
            "external_path": str(pdf_path),
        }
    except Exception:
        return None


def build_title_key(title: str) -> str:
    """标准化标题用于匹配"""
    # 移除空白、常见分隔符，统一编码
    normalized = re.sub(r"[\s\-–—_,.，。]+", "", title)
    return normalized[:40]  # 取前40字符


async def scan_external_pdfs() -> dict:
    """扫描外部硬盘，构建索引

    Returns:
        {
            (ts_code, year_month, title_key): [pdf_info, ...],
            ts_code: [pdf_info, ...],  # 全量索引
        }
    """
    if not EXTERNAL_DIR.exists():
        print(f"错误: 外部目录不存在: {EXTERNAL_DIR}")
        return {}

    cfg = load_backfill_settings()
    whitelist = set(cfg.ts_codes) if cfg.scope == "tech_mvp" else None

    pdfs = []
    for pdf_path in EXTERNAL_DIR.rglob("*.pdf"):
        info = parse_pdf_path(pdf_path)
        if info:
            if whitelist and info["ts_code"] not in whitelist:
                continue
            pdfs.append(info)

    print(f"扫描到 {len(pdfs)} 个外部 PDF")

    # 构建索引: (ts_code, year_month, title_key) -> pdf_info
    by_key = defaultdict(list)
    for pdf in pdfs:
        key = (pdf["ts_code"], pdf["date_dir"], build_title_key(pdf["title"]))
        by_key[key].append(pdf)

    print(f"去重后唯一记录: {len(by_key)}")

    return by_key


async def find_and_update_records(external_index: dict, dry_run: bool = True) -> tuple[int, int, int]:
    """查找需要更新的记录并更新

    Returns:
        (total_need_update, found_count, updated_count)
    """
    # 1. 找出数据库中有旧路径的记录
    # 旧路径: /home/lwm/... 或 file_path IS NULL 但有 pdf_url
    async with engine.connect() as conn:
        result = await conn.execute(
            text("""
            SELECT cninfo_id, ts_code, ann_date, title, file_path, pdf_url
            FROM announcements
            WHERE
                (file_path LIKE '/home/lwm/%' AND file_path IS NOT NULL)
                OR (file_path IS NULL AND pdf_url IS NOT NULL)
            ORDER BY ts_code, ann_date
        """)
        )

        records = [dict(row._mapping) for row in result]

    print(f"数据库中需要更新的记录: {len(records)}")

    if not records:
        return 0, 0, 0

    # 2. 批量匹配
    found = 0
    updated = 0
    not_found = 0

    batch_size = 500
    for batch_start in range(0, len(records), batch_size):
        batch_end = min(batch_start + batch_size, len(records))
        batch = records[batch_start:batch_end]

        async with engine.begin() as conn:
            for rec in batch:
                ts_code = rec["ts_code"]
                ann_date = rec["ann_date"]
                title = rec["title"] or ""

                # 计算数据库记录的年-月
                if isinstance(ann_date, str):
                    year_month = ann_date[:7]  # YYYY-MM
                else:
                    year_month = ann_date.strftime("%Y-%m")

                title_key = build_title_key(title)

                # 查找外部索引
                key = (ts_code, year_month, title_key)
                matches = external_index.get(key, [])

                if not matches:
                    # 放宽匹配：只用 ts_code + year_month + title 前缀
                    for ext_key, ext_pdfs in external_index.items():
                        if ext_key[0] == ts_code and ext_key[1] == year_month:
                            ext_title = ext_pdfs[0]["title"]
                            if (
                                title_key[:20] in build_title_key(ext_title)
                                or build_title_key(ext_title)[:20] in title_key
                            ):
                                matches = ext_pdfs
                                break

                if matches:
                    found += 1
                    if not dry_run:
                        await conn.execute(
                            text("UPDATE announcements SET file_path = :fp WHERE cninfo_id = :cid"),
                            {"fp": matches[0]["external_path"], "cid": rec["cninfo_id"]},
                        )
                        updated += 1
                else:
                    not_found += 1

        if (batch_end) % 2000 == 0 or batch_end == len(records):
            print(f"  进度: {batch_end}/{len(records)} (找到: {found}, 更新: {updated}, 未找到: {not_found})")

    return len(records), found, updated


async def main(dry_run: bool = True):
    print(f"{'=' * 65}")
    print("  同步外部 PDF 到数据库")
    print(f"{'=' * 65}")
    print(f"  外部目录: {EXTERNAL_DIR}")
    print(f"  模式: {'模拟运行' if dry_run else '实际更新'}")
    print()

    # 1. 扫描外部 PDF
    external_index = await scan_external_pdfs()

    if not external_index:
        return

    # 2. 查找并更新
    print()
    total, found, updated = await find_and_update_records(external_index, dry_run)

    print()
    print(f"{'=' * 65}")
    print("  完成!")
    print(f"{'=' * 65}")
    print(f"  需要更新: {total}")
    print(f"  匹配成功: {found}")
    if dry_run:
        print(f"  预计更新: {updated}")
    else:
        print(f"  实际更新: {updated}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="同步外部 PDF 到数据库")
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    asyncio.run(main(dry_run=not args.execute))
