"""存量 value 真实性修正：metric_value 无数字（定性表述被 LLM 塞入）→ 摘 value。

例：'国内同行业首位' / '较高' / '良好'（无数字）→ 摘 value/unit。
与 normalize.clean_metric_value 同规则（提取数字部分；无数字 → None）。
幂等：第二遍无匹配即无操作。

用法：python -m scripts.sanitize_metric_values [--apply]
"""
from __future__ import annotations

import argparse
import asyncio
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_NUM_RE = re.compile(r"-?\d[\d,.]*")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    from sqlalchemy import text as sqltext

    from app.core.database import async_session

    async with async_session() as session:
        rows = (
            await session.execute(
                sqltext(
                    "SELECT keyword_id, evidence_id, span_start, metric_value "
                    "FROM link_links WHERE metric_value IS NOT NULL"
                )
            )
        ).all()
        print(f"带值行: {len(rows)}")
        pending = [(kw, ev, sp) for kw, ev, sp, val in rows if not _NUM_RE.search(str(val))]
        print(f"无数字（将摘 value）: {len(pending)}")
        # 样本
        for kw, ev, sp, val in rows[:200000]:
            if not _NUM_RE.search(str(val)):
                print("  样本:", repr(str(val))[:40])

        if not args.apply:
            print("（dry-run；加 --apply 执行）")
            return
        changed = 0
        for kw, ev, sp in pending:
            r = await session.execute(
                sqltext(
                    "UPDATE link_links SET metric_value=NULL, metric_unit=NULL "
                    "WHERE keyword_id=:kw AND evidence_id=:ev AND span_start=:sp"
                ),
                {"kw": kw, "ev": ev, "sp": sp},
            )
            changed += r.rowcount or 0
        await session.commit()
        print(f"=== 摘 {changed} 行 ===", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
