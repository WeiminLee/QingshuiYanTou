"""清洗存量污染：删除「词不在原文里」的 LLM 类 scope/dimension link。

历史原因：LLM 类 link 的 span 恒为 0，无法用 span 校验，导致跨文档串台与
幻觉（约 1.6% 真污染）长期留存。本脚本用 evidence 原文做包含性校验（带格式
归一化兜底，避免误杀全角/空白变体）。

性能设计（v2，全量可用）：
  1. keyset 分页（游标 keyword_id, evidence_id），避免 OFFSET 越翻越慢；
  2. 每批「扫完即删即提交」，进程中断不丢已删进度，可断点续跑；
  3. 每批 evidence 原文用一次 Mongo $in 批量取，省掉逐条往返。

断点续跑：删除会改变分页集合，故用「已处理游标」持久化到文件，
  重启时从游标继续（LEAST 语义：只前进，不回头）。

用法（云端）：
  python -m scripts.clean_link_pollution --dry-run          # 只统计
  python -m scripts.clean_link_pollution --apply            # 实际删除
  python -m scripts.clean_link_pollution --apply --limit 50000
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

CHECKPOINT = Path("/tmp/clean_link_pollution.checkpoint.json")


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


def _load_cursor() -> tuple[str, str] | None:
    try:
        d = json.loads(CHECKPOINT.read_text())
        return (d["kw"], d["ev"])
    except Exception:  # noqa: BLE001
        return None


def _save_cursor(kw: str, ev: str) -> None:
    CHECKPOINT.write_text(json.dumps({"kw": kw, "ev": ev}))


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="最多检查条数（0=全部）")
    ap.add_argument("--apply", action="store_true", help="实际删除（默认 dry-run）")
    ap.add_argument("--batch", type=int, default=5000)
    ap.add_argument("--reset", action="store_true", help="忽略断点，从头开始")
    args = ap.parse_args()

    from sqlalchemy import text as sqltext

    from app.core.database import async_session
    from app.knowledge.evidence_service import EvidenceService

    svc = EvidenceService()
    total_checked = total_bad = total_deleted = 0

    cursor = None if args.reset else _load_cursor()
    if cursor:
        print(f"从断点续跑：kw={cursor[0]} ev={cursor[1]}", flush=True)

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

        # keyset 分页：游标 (keyword_id, evidence_id)，只前进
        while True:
            if cursor:
                q = sqltext(
                    "SELECT l.keyword_id, k.norm_text, l.evidence_id "
                    "FROM link_links l JOIN link_keywords k USING (keyword_id) "
                    "WHERE k.layer IN ('scope','dimension') AND l.source='llm' "
                    "AND (l.keyword_id, l.evidence_id) > (:kw, :ev) "
                    "ORDER BY l.keyword_id, l.evidence_id LIMIT :lim"
                )
                params = {"kw": cursor[0], "ev": cursor[1], "lim": args.batch}
            else:
                q = sqltext(
                    "SELECT l.keyword_id, k.norm_text, l.evidence_id "
                    "FROM link_links l JOIN link_keywords k USING (keyword_id) "
                    "WHERE k.layer IN ('scope','dimension') AND l.source='llm' "
                    "ORDER BY l.keyword_id, l.evidence_id LIMIT :lim"
                )
                params = {"lim": args.batch}

            rows = (await session.execute(q, params)).all()
            if not rows:
                break

            # 批量取原文（一次 Mongo $in）
            ev_ids = list({r[2] for r in rows})
            raw = await svc._evidence.find(
                {"evidence_id": {"$in": ev_ids}}, {"_id": 0, "evidence_id": 1, "text_excerpt": 1}
            ).to_list(length=len(ev_ids))
            texts = {d["evidence_id"]: (d.get("text_excerpt") or "") for d in raw}
            norm_cache = {eid: _normalize(t) for eid, t in texts.items()}

            batch_bad: list[tuple[str, str]] = []
            for kw_id, norm, evid in rows:
                total_checked += 1
                text = texts.get(evid, "")
                if not text:
                    continue  # 无原文不判定（保守）
                if norm in text or _normalize(norm) in norm_cache.get(evid, ""):
                    continue
                total_bad += 1
                batch_bad.append((kw_id, evid))

            # 本批「扫完即删即提交」（应用模式）
            if args.apply and batch_bad:
                for kw_id, evid in batch_bad:
                    await session.execute(
                        sqltext("DELETE FROM link_links WHERE keyword_id=:k AND evidence_id=:e"),
                        {"k": kw_id, "e": evid},
                    )
                await session.commit()
                total_deleted += len(batch_bad)

            last = rows[-1]
            _save_cursor(last[0], last[2])

            print(
                f"已检查 {total_checked}，污染 {total_bad}"
                f"（{100*total_bad/max(total_checked,1):.1f}%），已删 {total_deleted}，"
                f"游标 kw={last[0][:8]}.. ev={last[2][:10]}..",
                flush=True,
            )
            if args.limit and total_checked >= args.limit:
                break

        print(
            f"\n=== 结果：检查 {total_checked}，污染 {total_bad}，删除 {total_deleted} ==="
        )
        if not args.apply:
            print("（dry-run，未删除；加 --apply 执行）")
        else:
            CHECKPOINT.unlink(missing_ok=True)
            print("（已删除，断点文件已清理）")


if __name__ == "__main__":
    asyncio.run(main())
