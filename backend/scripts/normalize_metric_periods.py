"""存量 metric period 归一化：原文字面串 → canonicalize_period 规范标签。

增量已在 ingest 走 canonicalize_period；本脚本把存量的
「2025年1-6月」→ H1 2025 / 「2024年度」→ FY 2024 等写回 link_links.metric_period。
可逆性：原串已在 evidence 文本里（fetch_evidence 可回查），改写无信息损失。
幂等：canonicalize_period(规范标签) == 规范标签 → 第二遍 no-op。

用法：python -m scripts.normalize_metric_periods [--apply]
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
    from app.knowledge.linklayer.normalize import canonicalize_period

    async with async_session() as session:
        rows = (
            await session.execute(
                sqltext(
                    "SELECT keyword_id, evidence_id, span_start, metric_period "
                    "FROM link_links WHERE metric_period IS NOT NULL"
                )
            )
        ).all()
        print(f"period 非空行: {len(rows)}")
        pending: list[tuple[str, str, str]] = []
        unchanged = 0
        for kw_id, evid, span, period in rows:
            norm = canonicalize_period(period)
            if norm and norm != period:
                pending.append((norm, kw_id, evid, span))
            else:
                unchanged += 1
        print(f"待归一: {len(pending)}（已规范 {unchanged}）")
        for row in pending[:6]:
            print("  ", row[1][:14], repr(row[3]), "→", row[0])

        if not args.apply:
            print("（dry-run；加 --apply 执行）")
            return
        changed = 0
        for norm, kw_id, evid, span in pending:
            r = await session.execute(
                sqltext(
                    "UPDATE link_links SET metric_period = :p "
                    "WHERE keyword_id = :kw AND evidence_id = :ev AND span_start = :sp"
                ),
                {"p": norm, "kw": kw_id, "ev": evid, "sp": span},
            )
            changed += r.rowcount or 0
        await session.commit()
        print(f"=== 归一 {changed} 行 ===", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
