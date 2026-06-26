#!/usr/bin/env python3
"""
概念板块数据入库脚本

将抓取好的 CSV 数据批量写入 PostgreSQL 表。
当前覆盖：
  - ths_tushare_members.csv  → ths_concept_members
  - ths_tushare_members.csv  → stock_concepts  (白名单股票子集)
  - sina_concept_members.csv → concept + stock_concepts
  - ths_concept_list.csv     → concepts

用法:
    python -m scripts.import_board_data
    python -m scripts.import_board_data --dry-run
    python -m scripts.import_board_data --scope ths_members
    python -m scripts.import_board_data --scope stock_concepts
    python -m scripts.import_board_data --scope sina
    python -m scripts.import_board_data --scope ths_list
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
from sqlalchemy import text

from app.core.database import engine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent / "data" / "board_concept"


# ── 辅助函数 ──────────────────────────────────────────────


def _clean(val) -> str:
    if val is None:
        return ""
    s = str(val).strip()
    return s if s else ""


async def _batch_insert(
    table_name: str,
    records: list[dict],
    index_elements: list[str],
    batch_size: int = 500,
) -> int:
    """批量 INSERT，支持 ON CONFLICT DO NOTHING。"""
    if not records:
        return 0

    fields = list(records[0].keys())
    field_list = ", ".join(fields)
    placeholders = ", ".join([f":{f}" for f in fields])
    conflict_cols = ", ".join(index_elements)
    stmt = text(f"""
        INSERT INTO {table_name} ({field_list})
        VALUES ({placeholders})
        ON CONFLICT ({conflict_cols}) DO NOTHING
    """)

    total_saved = 0
    for i in range(0, len(records), batch_size):
        batch = records[i : i + batch_size]
        try:
            async with engine.begin() as conn:
                result = await conn.execute(stmt, batch)
                total_saved += result.rowcount or 0
        except Exception as e:
            logger.warning(f"批量插入 {table_name}[{i}:{i + len(batch)}] 失败: {e}")
    return total_saved


# ── THS Tushare 成员 → ths_concept_members ───────────────


async def import_ths_members(dry_run: bool = False) -> dict:
    """导入 THS Tushare 成员数据到 ths_concept_members 表。"""
    csv_path = DATA_DIR / "ths_tushare_members.csv"
    if not csv_path.exists():
        logger.warning("文件不存在: %s，跳过", csv_path)
        return {"total": 0, "saved": 0}

    df = pd.read_csv(csv_path, dtype=str)
    df = df.fillna("")

    logger.info("THS Tushare 成员: %d 行", len(df))

    records = []
    for _, row in df.iterrows():
        code = _clean(row.get("concept_code"))
        cname = _clean(row.get("concept_name"))
        scode = _clean(row.get("stock_code"))

        if not code or not scode:
            continue

        # stock_code 可能是 "000021.SZ" 或纯数字
        ts_code = scode if "." in scode else None
        if not ts_code and len(scode) == 6 and scode.isdigit():
            if scode.startswith(("60", "68")):
                ts_code = f"{scode}.SH"
            elif scode.startswith(("00", "30", "20")):
                ts_code = f"{scode}.SZ"
            elif scode.startswith(("43", "83", "87", "88", "89", "92")):
                ts_code = f"{scode}.BJ"

        if ts_code:
            records.append(
                {
                    "ts_code": ts_code,
                    "con_code": code,
                    "con_name": cname,
                    "in_date": None,
                }
            )

    logger.info("转换后有效记录: %d", len(records))
    if dry_run:
        return {"total": len(records), "saved": 0}

    saved = await _batch_insert("ths_concept_members", records, ["ts_code", "con_code"])
    return {"total": len(records), "saved": saved}


# ── THS 成员 → stock_concepts (白名单子集) ───────────────


async def import_stock_concepts_ths(dry_run: bool = False) -> dict:
    """将 THS 成员中属于白名单的股票导入 stock_concepts。"""
    csv_path = DATA_DIR / "ths_tushare_members.csv"
    wl_path = DATA_DIR / "tech_ts_codes.txt"

    if not csv_path.exists():
        logger.warning("THS CSV 不存在，跳过")
        return {"total": 0, "saved": 0}

    with open(wl_path) as f:
        whitelist = set(line.strip() for line in f if line.strip())

    df = pd.read_csv(csv_path, dtype=str)
    df = df.fillna("")

    seen: set = set()
    records = []
    for _, row in df.iterrows():
        code = _clean(row.get("concept_code"))
        scode = _clean(row.get("stock_code"))

        if not code or not scode:
            continue

        ts_code = scode if "." in scode else None
        if not ts_code and len(scode) == 6 and scode.isdigit():
            if scode.startswith(("60", "68")):
                ts_code = f"{scode}.SH"
            elif scode.startswith(("00", "30", "20")):
                ts_code = f"{scode}.SZ"
            elif scode.startswith(("43", "83", "87", "88", "89", "92")):
                ts_code = f"{scode}.BJ"

        if ts_code and ts_code in whitelist:
            key = (ts_code, code)
            if key not in seen:
                seen.add(key)
                records.append({"ts_code": ts_code, "concept_code": code})

    logger.info("stock_concepts (THS 白名单): %d 条", len(records))
    if dry_run:
        return {"total": len(records), "saved": 0}

    saved = await _batch_insert("stock_concepts", records, ["ts_code", "concept_code"])
    return {"total": len(records), "saved": saved}


# ── Sina 成员 → concept + stock_concepts ─────────────────


async def import_sina_concepts(dry_run: bool = False) -> dict:
    """将 Sina 成员数据导入 concept 和 stock_concepts。"""
    csv_path = DATA_DIR / "sina_concept_members.csv"
    wl_path = DATA_DIR / "tech_ts_codes.txt"

    if not csv_path.exists():
        logger.warning("文件不存在: %s，跳过", csv_path)
        return {"total": 0, "saved": 0}

    if wl_path.exists():
        with open(wl_path) as f:
            whitelist = set(line.strip() for line in f if line.strip())
    else:
        whitelist = None

    df = pd.read_csv(csv_path, dtype=str)
    df = df.fillna("")

    logger.info("Sina 成员: %d 行", len(df))

    concept_records: list[dict] = []
    stock_records: list[dict] = []
    seen_concept: set = set()
    seen_stock: set = set()

    for _, row in df.iterrows():
        label = _clean(row.get("concept_label"))
        cname = _clean(row.get("concept_name"))
        ts_code = _clean(row.get("ts_code"))

        if not label:
            continue

        if label not in seen_concept:
            seen_concept.add(label)
            concept_records.append(
                {
                    "concept_code": label,
                    "concept_name": cname,
                    "created_at": datetime.now(),
                }
            )

        if ts_code and (whitelist is None or ts_code in whitelist):
            key = (ts_code, label)
            if key not in seen_stock:
                seen_stock.add(key)
                stock_records.append({"ts_code": ts_code, "concept_code": label})

    logger.info("concept: %d 条, stock_concepts: %d 条", len(concept_records), len(stock_records))

    if dry_run:
        return {
            "total_concepts": len(concept_records),
            "total_stocks": len(stock_records),
            "saved": 0,
        }

    c_saved = await _batch_insert("concept", concept_records, ["concept_code"])
    s_saved = await _batch_insert("stock_concepts", stock_records, ["ts_code", "concept_code"])
    return {
        "total_concepts": len(concept_records),
        "total_stocks": len(stock_records),
        "saved": c_saved + s_saved,
    }


# ── THS 概念列表 → concepts ───────────────────────────────


async def import_ths_concepts_list(dry_run: bool = False) -> dict:
    """将 THS 概念列表导入 concepts 表。"""
    csv_path = DATA_DIR / "ths_concept_list.csv"
    if not csv_path.exists():
        logger.warning("文件不存在: %s，跳过", csv_path)
        return {"total": 0, "saved": 0}

    df = pd.read_csv(csv_path, dtype=str)
    df = df.fillna("")

    records = []
    seen = set()
    for _, row in df.iterrows():
        code = _clean(row.get("code"))
        name = _clean(row.get("name"))
        if not code or code in seen:
            continue
        seen.add(code)
        records.append({"code": code, "name": name, "src": "ths"})

    logger.info("THS 概念列表: %d 条", len(records))
    if dry_run:
        return {"total": len(records), "saved": 0}

    saved = await _batch_insert("concepts", records, ["code"])
    return {"total": len(records), "saved": saved}


# ── 主入口 ───────────────────────────────────────────────


async def main(scope: str = "all", dry_run: bool = False) -> dict:
    logger.info("概念板块数据入库 | scope=%s | dry_run=%s", scope, dry_run)
    print(f"{'=' * 60}")
    print("  概念板块数据入库")
    print(f"{'=' * 60}")

    results = {}

    if scope in ("all", "ths_members"):
        r = await import_ths_members(dry_run)
        results["ths_members"] = r
        print(f"  ths_concept_members:  {r['total']:,} 条准备{r.get('saved', 0):,} 条写入")

    if scope in ("all", "stock_concepts"):
        r = await import_stock_concepts_ths(dry_run)
        results["stock_concepts"] = r
        print(f"  stock_concepts (THS): {r['total']:,} 条准备{r.get('saved', 0):,} 条写入")

    if scope in ("all", "sina"):
        r = await import_sina_concepts(dry_run)
        results["sina"] = r
        print(f"  concept:              {r.get('total_concepts', 0):,} 条")
        print(f"  stock_concepts (Sina): {r.get('total_stocks', 0):,} 条")

    if scope in ("all", "ths_list"):
        r = await import_ths_concepts_list(dry_run)
        results["ths_list"] = r
        print(f"  concepts (THS list):  {r['total']:,} 条准备{r.get('saved', 0):,} 条写入")

    if not dry_run:
        print()
        print("  验证入库结果:")
        async with engine.connect() as conn:
            for t in ["concept", "ths_concept_members", "stock_concepts", "concepts"]:
                try:
                    r = await conn.execute(text(f"SELECT COUNT(*) FROM {t}"))
                    cnt = r.scalar()
                    r2 = await conn.execute(text(f"SELECT COUNT(DISTINCT ts_code) FROM {t} WHERE ts_code IS NOT NULL"))
                    stocks = r2.scalar()
                    r3 = await conn.execute(
                        text(f"SELECT COUNT(DISTINCT concept_code) FROM {t} WHERE concept_code IS NOT NULL")
                    )
                    concepts = r3.scalar()
                    print(f"    {t:25s}: {cnt:>8,} 行, {stocks:>6,} 只股票, {concepts:>6,} 个概念")
                except Exception as e:
                    print(f"    {t}: 查询失败 {e}")

    print()
    print(f"  {'[dry-run] 试运行模式' if dry_run else '入库完成!'}")

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="概念板块数据入库")
    parser.add_argument(
        "--scope",
        default="all",
        choices=["all", "ths_members", "stock_concepts", "sina", "ths_list"],
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    asyncio.run(main(scope=args.scope, dry_run=args.dry_run))
