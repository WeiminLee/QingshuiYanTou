"""存量单位一致性修正：值行 unit 与标准维度 parent 不同型 → 摘 value/unit。

与 normalize.enforce_unit 同规则（毛利率=ratio/营收=money/净利润=money）。
幂等：第二遍无匹配即无操作。

用法（云端）：python -m scripts.detach_unit_violations / --apply
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    from sqlalchemy import text as sqltext

    from app.core.database import async_session

    async with async_session() as session:
        # parent 标准维度 → 型
        rows = (
            await session.execute(
                sqltext(
                    "SELECT l.keyword_id, k2.norm_text AS parent, l.metric_value, l.metric_unit"
                    " FROM link_links l"
                    " JOIN link_keywords k ON k.keyword_id = l.keyword_id"
                    " LEFT JOIN link_keywords k2 ON k2.keyword_id = k.parent_keyword_id"
                    " WHERE l.metric_value IS NOT NULL AND k.layer='dimension'"
                    "   AND k2.norm_text IN ('毛利率','营收','净利润')"
                )
            )
        ).all()
        print(f"带值行（三大维度）: {len(rows)}")

        violation = []
        for kw_id, parent, val, unit in rows:
            u = (unit or "").strip()
            if parent == "毛利率" and u and not any(x in u for x in ("%", "个点", "pct", "百分点")):
                violation.append((kw_id, parent, val, u, "ratio组混入"))
            elif parent in ("营收", "净利润") and u and any(x in u for x in ("%", "pct")):
                violation.append((kw_id, parent, val, u, "money组混%"))
        print(f"违规行: {len(violation)}")
        for v in violation[:8]:
            print("  ", v)

        if not args.apply:
            print("（dry-run；加 --apply 执行）")
            return

        changed = 0
        for kw_id, _p, _v, _u, _why in violation:
            r = await session.execute(
                sqltext(
                    "UPDATE link_links SET metric_value=NULL, metric_unit=NULL, metric_period=NULL"
                    " WHERE keyword_id=:kw AND metric_value IS NOT NULL"
                ),
                {"kw": kw_id},
            )
            changed += r.rowcount or 0
        await session.commit()
        print(f"=== 摘 value {changed} 行 ===", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
