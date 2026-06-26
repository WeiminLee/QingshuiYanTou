#!/usr/bin/env python3
"""
将 board_concept 目录下的 CSV 数据加载到数据库表。

数据来源:
  - ths_tushare_members.csv  → ths_concept_members  (69,253 行，成分股映射)
  - ths_tushare_index.csv   → ths_concepts          (概念列表，403 个)
  - sina_concept_members.csv → stock_concepts        (新浪概念，10,532 行)

用法:
    python -m scripts.load_concepts_to_db
    python -m scripts.load_concepts_to_db --dry-run
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import sys
from datetime import date as date_type
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
from sqlalchemy import text

from app.core.database import engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent / "data" / "board_concept"


def _md5(prefix: str, *parts: str) -> str:
    raw = "_".join(str(p) for p in parts)
    return hashlib.md5(raw.encode("utf-8", errors="replace")).hexdigest()[:8]


# ── 通用 upsert（纯 SQL，无 ORM 依赖） ──────────────────


async def _upsert_sql(
    table: str,
    records: list[dict[str, Any]],
    index_cols: list[str],
    batch_size: int = 2000,
) -> int:
    """批量 upsert，返回实际写入行数。"""
    if not records:
        return 0

    # 统一所有记录的 key 集合，避免参数绑定错位
    all_keys: set[str] = set()
    for r in records:
        all_keys.update(r.keys())
    cols = sorted(all_keys)
    names = ", ".join(cols)
    placeholders = ", ".join([f":{c}" for c in cols])

    # 规范化每条记录：缺失字段填 None
    for r in records:
        for k in cols:
            r.setdefault(k, None)

    # ON CONFLICT DO UPDATE SET ... (排除主键、index_cols)
    skip_cols = {"id", "created_at"} | set(index_cols)
    set_parts = [f"{k}=EXCLUDED.{k}" for k in cols if k not in skip_cols]
    if set_parts:
        on_conflict = f"ON CONFLICT ({', '.join(index_cols)}) DO UPDATE SET {', '.join(set_parts)}"
    else:
        on_conflict = f"ON CONFLICT ({', '.join(index_cols)}) DO NOTHING"

    sql = text(f"INSERT INTO {table} ({names}) VALUES ({placeholders}) {on_conflict}")

    total = 0
    for i in range(0, len(records), batch_size):
        batch = records[i : i + batch_size]
        try:
            async with engine.begin() as conn:
                result = await conn.execute(sql, batch)
                total += result.rowcount or 0
        except Exception as e:
            logger.warning("  批量失败(%s)，降级逐条: %s", table, e)
            ok = 0
            for rec in batch:
                try:
                    async with engine.begin() as conn:
                        r = await conn.execute(sql, rec)
                        ok += r.rowcount or 0
                except Exception:
                    pass
            total += ok

        done = min(i + batch_size, len(records))
        if (i + batch_size) % 10000 == 0 or done == len(records):
            logger.info("  已写入 %d / %d", done, len(records))

    return total


# ── 1. ths_concept_members ─────────────────────────────


async def load_ths_members(dry_run: bool) -> int:
    """ths_tushare_members.csv → ths_concept_members"""
    path = DATA_DIR / "ths_tushare_members.csv"
    if not path.exists():
        logger.warning("跳过: %s 不存在", path)
        return 0

    df = pd.read_csv(path)
    logger.info("源文件: %s (%d 行)", path.name, len(df))

    # 列: concept_code, concept_name, stock_code, stock_name
    records = []
    for _, row in df.iterrows():
        ts_code = str(row.get("stock_code", "")).strip()
        con_code = str(row.get("concept_code", "")).strip()
        con_name = str(row.get("concept_name", "")).strip()

        if not ts_code or not con_code:
            continue
        if "." not in ts_code:  # 跳过无后缀的代码
            continue

        records.append(
            {
                "ts_code": ts_code,
                "con_code": con_code,
                "con_name": con_name,
            }
        )

    logger.info("有效记录: %d", len(records))
    if dry_run:
        return len(records)

    total = await _upsert_sql(
        "ths_concept_members",
        records,
        index_cols=["ts_code", "con_code"],
    )
    logger.info("ths_concept_members: 写入 %d 行", total)
    return total


# ── 2. ths_concepts ────────────────────────────────────


async def load_ths_concepts(dry_run: bool) -> int:
    """ths_tushare_index.csv → ths_concepts（概念列表）"""
    path = DATA_DIR / "ths_tushare_index.csv"
    if not path.exists():
        logger.warning("跳过: %s 不存在", path)
        return 0

    df = pd.read_csv(path)
    logger.info("源文件: %s (%d 行)", path.name, len(df))

    # 列: ts_code(=concept_code), name, count, exchange, list_date, type
    records = []
    for _, row in df.iterrows():
        ts_code = str(row.get("ts_code", "")).strip()
        name = str(row.get("name", "")).strip()
        count = row.get("count")
        exchange = str(row.get("exchange", "")).strip()
        list_date_val = row.get("list_date")
        ctype = str(row.get("type", "")).strip()

        if not ts_code or not name:
            continue

        rec: dict[str, Any] = {
            "ts_code": ts_code,  # 概念代码，如 885311.TI
            "name": name,
            "type": ctype,
        }
        if pd.notna(count):
            rec["count"] = int(float(count))
        if exchange:
            rec["exchange"] = exchange
        if pd.notna(list_date_val):
            list_str = str(int(float(list_date_val)))[:8]
            if list_str.isdigit():
                rec["list_date"] = date_type(int(list_str[:4]), int(list_str[4:6]), int(list_str[6:8]))

        records.append(rec)

    logger.info("有效记录: %d", len(records))
    if dry_run:
        return len(records)

    total = await _upsert_sql(
        "ths_concepts",
        records,
        index_cols=["ts_code"],
    )
    logger.info("ths_concepts: 写入 %d 行", total)
    return total


# ── 3. stock_concepts ──────────────────────────────────


async def load_stock_concepts(dry_run: bool) -> int:
    """sina_concept_members.csv → stock_concepts"""
    path = DATA_DIR / "sina_concept_members.csv"
    if not path.exists():
        logger.warning("跳过: %s 不存在", path)
        return 0

    df = pd.read_csv(path)
    logger.info("源文件: %s (%d 行)", path.name, len(df))

    # 列: concept_label, concept_name, ts_code, stock_code, stock_name, fetched_at
    records = []
    for _, row in df.iterrows():
        ts_code = str(row.get("ts_code", "")).strip()
        concept_name = str(row.get("concept_name", "")).strip()
        if not ts_code or not concept_name:
            continue
        con_code = _md5("sina", concept_name)
        records.append({"ts_code": ts_code, "concept_code": con_code})

    logger.info("有效记录: %d", len(records))
    if dry_run:
        return len(records)

    total = await _upsert_sql(
        "stock_concepts",
        records,
        index_cols=["ts_code", "concept_code"],
    )
    logger.info("stock_concepts: 写入 %d 行", total)
    return total


# ── main ────────────────────────────────────────────────


async def main(dry_run: bool = False) -> dict[str, int]:
    logger.info("=" * 60)
    logger.info("  概念数据加载: CSV → DB")
    logger.info("=" * 60)
    logger.info("  数据目录: %s", DATA_DIR)
    logger.info("  模式:    %s", "试运行 (dry-run)" if dry_run else "正式写入")
    logger.info("")

    r1 = await load_ths_members(dry_run)
    r2 = await load_ths_concepts(dry_run)
    r3 = await load_stock_concepts(dry_run)

    logger.info("")
    logger.info("=" * 60)
    logger.info("  完成！")
    logger.info("  ths_concept_members: +%d", r1)
    logger.info("  ths_concepts:        +%d", r2)
    logger.info("  stock_concepts:      +%d", r3)
    logger.info("=" * 60)

    return {"ths_members": r1, "ths_concepts": r2, "stock_concepts": r3}


if __name__ == "__main__":
    import asyncio

    parser = argparse.ArgumentParser(description="概念数据 CSV → DB 加载器")
    parser.add_argument("--dry-run", action="store_true")
    asyncio.run(main(dry_run=parser.parse_args().dry_run))
