"""清洗存量污染：删除「词不在原文里」的 LLM 类 scope/dimension link。

历史原因：LLM 类 link 的 span 恒为 0，无法用 span 校验，导致跨文档串台与
幻觉（约 4% 真污染）长期留存。本脚本用 evidence 原文做包含性校验（带格式
归一化兜底，避免误杀全角/空白变体）。

用法（在云端跑，需同时连 PG + Mongo）：
  cd backend && python -m scripts.clean_link_pollution --dry-run --limit 20000
  cd backend && python -m scripts.clean_link_pollution --apply
"""
from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_NUM = re.compile(r"\s+")


def _normalize(text: str) -> str:
    out = []
    for ch in text or "":
        code = ord(ch)
        if 0xFF01 <= code <= 0xFF5E:
            ch = chr(code - 0xFEE0)
        elif code == 0x3000:
            ch = " "
        out.append(ch)
    s = "".join(out).lower()
    return "".join(c for c in s if not c.isspace() and c not in "-_—–")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="最多检查条数（0=全部）")
    ap.add_argument("--apply", action="store_true", help="实际删除（默认 dry-run）")
    ap.add_argument("--batch", type=int, default=2000)
    args = ap.parse_args()

    from sqlalchemy import text as sqltext

    from app.core.database import async_session
    from app.knowledge.evidence_service import EvidenceService

    svc = EvidenceService()
    total_checked = total_bad = 0
    bad_pairs: list[tuple[str, str]] = []  # (keyword_id, evidence_id)

    async with async_session() as session:
        row = (
            await session.execute(
                sqltext(
                    "SELECT count(*) FROM link_links l JOIN link_keywords k USING (keyword_id) "
                    "WHERE k.layer IN ('scope','dimension') AND l.source='llm'"
                )
            )
        ).first()
        print(f"候选总数: {row[0]}", flush=True)

        offset = 0
        while True:
            q = sqltext(
                "SELECT l.keyword_id, k.norm_text, l.evidence_id "
                "FROM link_links l JOIN link_keywords k USING (keyword_id) "
                "WHERE k.layer IN ('scope','dimension') AND l.source='llm' "
                "ORDER BY l.keyword_id, l.evidence_id LIMIT :lim OFFSET :off"
            )
            rows = (await session.execute(q, {"lim": args.batch, "off": offset})).all()
            if not rows:
                break
            offset += len(rows)

            # 按 evidence 分组取原文（减少查询）
            by_ev: dict[str, list[tuple[str, str]]] = {}
            for kw_id, norm, evid in rows:
                by_ev.setdefault(evid, []).append((kw_id, norm))

            for evid, pairs in by_ev.items():
                ev = await svc.get_evidence(evid)
                text = (ev or {}).get("text_excerpt") or ""
                norm_text = _normalize(text)
                for kw_id, norm in pairs:
                    total_checked += 1
                    if not text:
                        continue  # 无原文不判定（保守）
                    if norm in text or _normalize(norm) in norm_text:
                        continue
                    total_bad += 1
                    bad_pairs.append((kw_id, evid))

            print(
                f"已检查 {total_checked} 条，污染 {total_bad} 条"
                f"（{100*total_bad/max(total_checked,1):.1f}%）",
                flush=True,
            )
            if args.limit and total_checked >= args.limit:
                break

        print(f"\n=== 结果：检查 {total_checked}，污染 {total_bad} ===")

        if args.apply and bad_pairs:
            deleted = 0
            for i in range(0, len(bad_pairs), args.batch):
                chunk = bad_pairs[i : i + args.batch]
                for kw_id, evid in chunk:
                    await session.execute(
                        sqltext(
                            "DELETE FROM link_links WHERE keyword_id=:k AND evidence_id=:e"
                        ),
                        {"k": kw_id, "e": evid},
                    )
                deleted += len(chunk)
                await session.commit()
                print(f"已删除 {deleted}/{len(bad_pairs)}", flush=True)
            print(f"=== 清洗完成，删除 {deleted} 行 ===")
        elif bad_pairs:
            print("（dry-run，未删除；加 --apply 执行）")


if __name__ == "__main__":
    asyncio.run(main())
