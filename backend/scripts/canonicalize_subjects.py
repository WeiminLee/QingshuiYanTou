"""存量 subject 规范化回填：把可映射到上市主体的 subject 关键词 link 迁移。

规则（机械，非 LLM）：
  · 精确：alias 表（ts_code/简称/规范全称）
  · 前缀：surface 以 alias(len>=4) 开头（"隆基绿能科技股份有限公司"→601012.SH）
  · 恒等：ts_code 自身
迁移方式：INSERT-SELECT...ON CONFLICT DO NOTHING → DELETE 原行（单事务，幂等）。
跑两遍安全（第二遍无匹配即无操作）。

用法（云端）：
  python -m scripts.canonicalize_subjects --dry-run     # 只统计映射与可迁移行数
  python -m scripts.canonicalize_subjects --apply
"""
from __future__ import annotations

import argparse
import asyncio
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

TS_RE = re.compile(r"^\d{6}\.(SH|SZ|BJ|SI)$")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit-kw", type=int, default=0, help="limit subject keyword count (0=all)")
    args = ap.parse_args()

    from sqlalchemy import text as sqltext

    from app.core.database import async_session
    from app.knowledge.linklayer.dict_match import SubjectIndex, load_alias_table
    from app.knowledge.linklayer.normalize import ensure_keyword

    idx = SubjectIndex(alias_to_norm=load_alias_table())

    async with async_session() as session:
        # 1) 拉 subject 层关键词
        q = "SELECT keyword_id, norm_text FROM link_keywords WHERE layer='subject'"
        if args.limit_kw:
            q += f" LIMIT {args.limit_kw}"
        kws = (await session.execute(sqltext(q))).all()
        print(f"subject keywords: {len(kws)}", flush=True)

        # 2) 计算映射：norm_text 可规范化（目标为 ts_code 且 != 自身）
        mapping: dict[str, str] = {}  # old keyword_id -> canonical ts_code
        no_hit = 0
        for kw_id, norm in kws:
            if TS_RE.match(norm or ""):
                continue  # 已是规范形态
            target = idx.canonicalize(norm)
            if target and TS_RE.match(target) and target != norm:
                mapping[kw_id] = target
            else:
                no_hit += 1
        print(f"可规范化映射: {len(mapping)}（不可映射保留 {no_hit}）", flush=True)

        # 可迁移行数预估
        if mapping:
            old_ids = list(mapping.keys())
            param_batch = 20000
            total_links = 0
            for i in range(0, len(old_ids), param_batch):
                chunk = old_ids[i : i + param_batch]
                n = (
                    await session.execute(
                        sqltext(
                            "SELECT count(*) FROM link_links WHERE keyword_id = ANY(:ids)"
                        ),
                        {"ids": chunk},
                    )
                ).scalar()
                total_links += n or 0
            print(f"需迁移 link 行数: {total_links}", flush=True)

        if not args.apply:
            print("（dry-run 结束；加 --apply 执行）")
            return

        # 3) 执行迁移（ensure_keyword 返回真实 keyword_id KW:xxx，不能直接用 ts_code 字符串）
        canon_id_by_code: dict[str, str] = {}
        for ts in sorted({v for v in mapping.values()}):
            canon_id_by_code[ts] = await ensure_keyword(
                session, "subject", ts, source="dictionary"
            )
        await session.commit()

        moved = deleted = 0
        for i, (old_id, target) in enumerate(mapping.items(), 1):
            r = await session.execute(
                sqltext(
                    "insert into link_links (keyword_id, evidence_id, span_start, span_end,"
                    " published_at, source, metric_value, metric_unit, metric_period) "
                    "select :t, evidence_id, span_start, span_end, published_at, source,"
                    " metric_value, metric_unit, metric_period"
                    " from link_links where keyword_id = :o"
                    " on conflict (keyword_id, evidence_id, span_start) do nothing"
                    " returning keyword_id"
                ),
                {"t": canon_id_by_code[target], "o": old_id},
            )
            inserted = len(r.all() or [])
            moved += inserted
            d = await session.execute(
                sqltext("delete from link_links where keyword_id = :o"), {"o": old_id}
            )
            deleted += d.rowcount or 0
            if i % 500 == 0:
                await session.commit()
                print(f"  进度 {i}/{len(mapping)} moved={moved} deleted={deleted}", flush=True)
        await session.commit()
        print(f"=== 完成：canonical 行新增 {moved}，原行删除 {deleted} ===", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
