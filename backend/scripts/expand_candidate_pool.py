#!/usr/bin/env python3
"""扩充 candidate_pool 到核心科技主题池（~3000 家）。

口径（2026-10-30）：
- 现有 ths_concept_members 的全部概念（芯片/半导体/AIDC/算力/CPO/存储/先进封装/液冷等）
- 科技及其产业链行业：半导体、元器件、软件服务、通信设备、IT设备、互联网、电器仪表、
  电气设备、专用机械、汽车配件、机械基件、机床制造、化工原料、家用电器
- 剔除 ST / 退市
- 只增不减：现有 active 一律保留；新命中标的 upsert 为 active

用法：
    python -m scripts.expand_candidate_pool --dry-run
    python -m scripts.expand_candidate_pool
"""

from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import text

from app.core.database import engine

TECH_INDUSTRIES = (
    "半导体",
    "元器件",
    "软件服务",
    "通信设备",
    "IT设备",
    "互联网",
    "电器仪表",
    "电气设备",
    "专用机械",
    "汽车配件",
    "机械基件",
    "机床制造",
    "化工原料",
)

TARGET_SQL = """
WITH target AS (
    SELECT con_code AS ts_code FROM ths_concept_members
    UNION
    SELECT ts_code FROM stocks WHERE industry = ANY(:industries)
)
SELECT t.ts_code, s.name
FROM target t
JOIN stocks s ON s.ts_code = t.ts_code
WHERE s.name NOT LIKE '%ST%'
  AND s.name NOT LIKE '%退%'
""".strip()


async def main(dry_run: bool) -> None:
    async with engine.connect() as conn:
        before = (await conn.execute(text("SELECT count(*) FROM candidate_pool WHERE is_active"))).scalar()
        rows = (await conn.execute(text(TARGET_SQL), {"industries": list(TECH_INDUSTRIES)})).fetchall()
        active_set = {
            r[0]
            for r in (
                await conn.execute(text("SELECT ts_code FROM candidate_pool WHERE is_active"))
            ).fetchall()
        }

    target = {r[0]: r[1] for r in rows}
    new_codes = sorted(set(target) - active_set)
    print(f"active_before={before} target={len(target)} new_to_add={len(new_codes)}")
    print(f"active_after≈{before + len(new_codes)}")

    if dry_run:
        for code in new_codes[:10]:
            print("  +", code, target[code])
        return

    if not new_codes:
        print("nothing to do")
        return

    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO candidate_pool (ts_code, name, source, reason, is_active)
                VALUES (:ts_code, :name, 'theme', :reason, true)
                ON CONFLICT (ts_code) DO UPDATE SET
                    name = EXCLUDED.name,
                    source = 'theme',
                    reason = EXCLUDED.reason,
                    is_active = true,
                    updated_at = now()
                """
            ),
            [
                {
                    "ts_code": code,
                    "name": target[code],
                    "reason": "core-tech-expand-2026-10-30",
                }
                for code in new_codes
            ],
        )
        after = (await conn.execute(text("SELECT count(*) FROM candidate_pool WHERE is_active"))).scalar()

    print(f"active_after={after}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    asyncio.run(main(ap.parse_args().dry_run))
