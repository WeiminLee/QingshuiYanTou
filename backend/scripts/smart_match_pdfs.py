#!/usr/bin/env python3
"""
智能匹配外部 PDF 到公告记录

策略：
1. 按 ts_code + 年月 + 公告类型分组
2. 每组只保留一个 PDF
3. 匹配数据库中同类型、同股票、同月份的记录

用法:
    python -m scripts.smart_match_pdfs --execute
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


# 公告类型关键词映射
DOC_TYPE_PATTERNS = [
    ("annual_report", ["年度报告", "年度业绩预告", "年度审计报告"]),
    ("half_report", ["半年度报告", "半年报告"]),
    ("quarter_report", ["一季度报告", "二季度报告", "三季度报告", "四季度报告", "季度报告"]),
    ("research_survey", ["投资者关系活动", "调研", "路演", "业绩说明会"]),
    ("investment", ["募集资金", "对外投资", "投资"]),
    ("ma_activity", ["并购", "资产重组", "股权激励"]),
]


def get_doc_type(title: str) -> str:
    """从标题推断公告类型"""
    if not title:
        return "other"
    for doc_type, keywords in DOC_TYPE_PATTERNS:
        for kw in keywords:
            if kw in title:
                return doc_type
    return "other"


async def main(dry_run: bool = True):
    print(f"{'=' * 65}")
    print("  智能匹配外部 PDF")
    print(f"{'=' * 65}")
    print(f"  模式: {'模拟运行' if dry_run else '实际执行'}")
    print()

    # ========== 1. 扫描外部 PDF ==========
    print("步骤 1: 扫描外部硬盘...")

    cfg = load_backfill_settings()
    whitelist = set(cfg.ts_codes) if cfg.scope == "tech_mvp" else None

    pdfs = []
    for pdf_path in EXTERNAL_DIR.rglob("*.pdf"):
        parts = pdf_path.parts
        if len(parts) < 3:
            continue
        ts_code = parts[-3]
        date_dir = parts[-2]
        if not re.match(r"\d{4}-\d{2}", date_dir):
            continue
        if whitelist and ts_code not in whitelist:
            continue

        filename = pdf_path.stem
        title = filename
        if filename.startswith("ann_"):
            parts_fn = filename.split("_", 2)
            if len(parts_fn) >= 3:
                title = parts_fn[2]

        doc_type = get_doc_type(title)

        pdfs.append(
            {
                "ts_code": ts_code,
                "date_dir": date_dir,
                "title": title,
                "doc_type": doc_type,
                "path": str(pdf_path),
            }
        )

    print(f"  扫描到 {len(pdfs):,} 个 PDF")

    # 按 (ts_code, year_month, doc_type) 去重，每组只保留一个
    pdf_index = {}
    for pdf in pdfs:
        key = (pdf["ts_code"], pdf["date_dir"], pdf["doc_type"])
        if key not in pdf_index:
            pdf_index[key] = pdf["path"]

    print(f"  去重后: {len(pdf_index):,} 个唯一记录")

    # ========== 2. 查询数据库记录 ==========
    print("\n步骤 2: 查询数据库...")

    async with engine.connect() as conn:
        # 查询 file_path 为 NULL 的公告记录（排除 IRM）
        r = await conn.execute(
            text("""
            SELECT cninfo_id, ts_code, TO_CHAR(ann_date, 'YYYY-MM') as ym, title, announcement_type
            FROM announcements
            WHERE file_path IS NULL
              AND title IS NOT NULL
              AND (announcement_type IS NULL OR announcement_type NOT LIKE 'irm:%')
        """)
        )
        records = []
        for row in r:
            records.append(
                {
                    "cninfo_id": row[0],
                    "ts_code": row[1],
                    "ym": row[2],
                    "title": row[3],
                    "ann_type": row[4],
                }
            )

    print(f"  待匹配记录: {len(records):,}")

    # ========== 3. 批量匹配 ==========
    print("\n步骤 3: 智能匹配...")

    # 按 (ts_code, year_month, ann_type) 分组
    db_index = defaultdict(list)
    for rec in records:
        ann_type = rec["ann_type"] or get_doc_type(rec["title"])
        key = (rec["ts_code"], rec["ym"], ann_type)
        db_index[key].append(rec["cninfo_id"])

    print(f"  数据库分组: {len(db_index):,}")

    # 执行匹配
    updates = []
    matched_keys = set()

    for key, pdf_path in pdf_index.items():
        ts_code, ym, doc_type = key

        # 精确匹配
        db_cids = db_index.get(key, [])

        if db_cids:
            updates.append((pdf_path, db_cids[0]))
            matched_keys.add(key)
        else:
            # 尝试用其他类型匹配（比如业绩预告 -> 年度报告）
            alt_types = {
                "annual_report": ["annual_report"],
                "half_report": ["half_report"],
                "quarter_report": ["quarter_report"],
            }
            if doc_type in alt_types:
                for alt in alt_types[doc_type]:
                    alt_key = (ts_code, ym, alt)
                    db_cids = db_index.get(alt_key, [])
                    if db_cids:
                        updates.append((pdf_path, db_cids[0]))
                        matched_keys.add(key)
                        break

    print(f"  匹配成功: {len(updates):,}")

    # ========== 4. 执行更新 ==========
    if updates and not dry_run:
        print(f"\n步骤 4: 更新 {len(updates):,} 条记录...")
        async with engine.begin() as conn:
            for path, cid in updates:
                await conn.execute(
                    text("UPDATE announcements SET file_path = :fp WHERE cninfo_id = :cid"),
                    {"fp": path, "cid": cid},
                )
        print("  更新完成!")

    print()
    print(f"{'=' * 65}")
    print("  完成!")
    print(f"{'=' * 65}")
    print(f"  匹配数量: {len(updates):,}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="智能匹配 PDF")
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    asyncio.run(main(dry_run=not args.execute))
