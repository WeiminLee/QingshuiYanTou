"""存量维度 parent 修正：占比类 metric 词的 parent_keyword_id 摘除。

背景：canonicalize_dimension 的子串命中把「占营业收入比例」等占比碎片挂到
「营收」parent 下，rollup_metric 的 children 被稀释（实战 [3] top30 半数占比）。
改 normalize 加占比黑名单后，增量不再挂错；本脚本修存量。

幂等：第二遍无匹配即无操作。规则机械（无 LLM）。

用法（云端）：
  python -m scripts.detach_derived_parents --dry-run
  python -m scripts.detach_derived_parents --apply
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 与 normalize._DERIVED_MARKERS 保持一致（占比类）
DERIVED_MARKERS = ("占营业收入", "营业收入占比", "营收占比", "占比", "比重", "比例")


def is_derived(norm: str) -> bool:
    return any(m in (norm or "") for m in DERIVED_MARKERS)


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    from sqlalchemy import text as sqltext

    from app.core.database import async_session

    async with async_session() as session:
        # parent 不为 NULL 的 dimension 关键词，norm 含占比类判定词
        rows = (
            await session.execute(
                sqltext(
                    "SELECT keyword_id, norm_text, parent_keyword_id FROM link_keywords "
                    "WHERE layer='dimension' AND parent_keyword_id IS NOT NULL"
                )
            )
        ).all()
        targets = [
            (kw_id, norm, pid) for kw_id, norm, pid in rows if is_derived(norm)
        ]
        # parent 链上「营收」子树下最多（rollup 的污染面），全部摘 parent（占比与
        # 任何 parent 语义都不匹配）。打印分布便于确认。
        print(f"dimension keywords with parent: {len(rows)}")
        print(f"占比类（将摘除 parent）: {len(targets)}")
        for _kw, norm, pid in targets[:8]:
            print("  ", norm, "→", pid[:16])

        if not args.apply:
            print("（dry-run；加 --apply 执行）")
            return
        changed = 0
        for kw_id, _norm, _pid in targets:
            r = await session.execute(
                sqltext(
                    "UPDATE link_keywords SET parent_keyword_id = NULL "
                    "WHERE keyword_id = :kw"
                ),
                {"kw": kw_id},
            )
            changed += r.rowcount or 0
        await session.commit()
        print(f"=== 摘除 parent {changed} 条 ===", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
