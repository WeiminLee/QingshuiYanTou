"""Gold set 候选生成器（半自动，供人工终审）。

三通道候选：
  timeline        —— 主体（ts_code）证据量足且日期跨度的演进链
  cross_section   —— dimension × scope 组合且 hint 主体数 ≥3 的跨公司对比
  theme           —— 高覆盖 scope 主题词（≥40 evidence），问题不含公司名

产出：
  backend/eval/gold_candidates_v2.json   机器可读候选（reviewed:false 待人工）
  backend/eval/gold_candidates_review.md 人审简报（复选框 + 证据摘录）

用法：
  python backend/scripts/build_gold_candidates.py --timeline 20 --cross 20 --theme 10
  python backend/scripts/build_gold_candidates.py --no-llm   # 模板问题，跳过 LLM
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from datetime import datetime, UTC
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

OUT_JSON = Path(__file__).resolve().parent.parent / "eval" / "gold_candidates_v2.json"
OUT_MD = Path(__file__).resolve().parent.parent / "eval" / "gold_candidates_review.md"

EXCERPT_CAP = 260


def _load_env() -> None:
    import os

    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_bytes().decode("utf-8", errors="replace").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())


_load_env()


def _existing_gold() -> list[dict]:
    p = Path(__file__).resolve().parent.parent / "eval" / "gold_set_v1.json"
    if p.is_file():
        return json.loads(p.read_text(encoding="utf-8"))
    return []


async def _stock_names(session) -> dict[str, str]:
    from sqlalchemy import text as _sql

    rows = (await session.execute(_sql("select ts_code, name from stocks"))).all()
    return {r[0]: r[1] for r in rows if r[0] and r[1]}


def _delist(x) -> str | None:
    return None if x is None else str(x)


async def _llm_question(kind: str, subject_name: str | None, dim: str | None,
                        scope: str | None, excerpts: list[str],
                        subject_code: str | None = None) -> str:
    """LLM 出题（thinking 已全局关闭）；失败/泄露 → 模板回退。"""
    if kind == "timeline":
        tpl = f"{subject_name} 在{dim or '相关业务'}上的进展如何演进？"
        code_note = f"（股票代码 {subject_code}）" if subject_code else ""
        rule = (f"问题必须包含公司「{subject_name}」{code_note}的名称本体，"
                "聚焦该公司的业务进展与时间演进；不要写成行业或概念泛问")
    elif kind == "cross_section":
        tpl = f"{scope or dim}相关业务，各公司的对比如何？" or "相关公司对比"
        rule = "问题中严禁出现任何公司名、简称或股票代码（公司名是答案）"
    else:
        tpl = f"{scope}赛道有哪些值得关注的进展？"
        rule = "问题中严禁出现任何公司名、简称或股票代码（公司名是答案）"
    try:
        from app.core.llm_client import chat_async

        sample = "\n".join(f"- {e[:180]}" for e in excerpts[:4])
        prompt = (
            "为投研检索系统写一条金标准查询问句（中文，≤50字）。\n"
            f"类型：{'公司时间线' if kind == 'timeline' else ('跨公司横截面' if kind == 'cross_section' else '主题')}\n"
            f"{rule}\n主数据标签：公司={subject_name or 'N/A'} 维度={dim or 'N/A'} scope={scope or 'N/A'}\n"
            f"证据摘录：\n{sample}\n"
            '只输出 JSON：{"question": "..."}'
        )
        text = await chat_async(prompt, model="Qwen3.6-35B-A3B-FP8", temperature=0.2, timeout=60)
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            q = json.loads(m.group(0)).get("question")
            if isinstance(q, str) and 6 <= len(q) <= 80:
                if kind != "timeline" and subject_name:
                    for token in re.split(r"[（(、,，\s]+", subject_name):
                        if len(token) >= 2 and token in q:
                            return tpl  # 泄露主体 → 模板
                return q
    except Exception:  # noqa: BLE001 — 出题尽力而为
        pass
    return tpl


async def timeline_candidates(session, names: dict[str, str], n: int) -> list[dict]:
    from sqlalchemy import text as _sql

    rows = (
        await session.execute(
            _sql(
                """
                SELECT k.norm_text AS subject_code, COUNT(DISTINCT l.evidence_id) AS n_ev,
                       COUNT(DISTINCT DATE(l.published_at)) AS n_days
                FROM link_keywords k JOIN link_links l ON l.keyword_id = k.keyword_id
                WHERE k.layer='subject' AND k.status='active' AND l.published_at IS NOT NULL
                GROUP BY k.norm_text
                HAVING COUNT(DISTINCT l.evidence_id) >= 6
                   AND COUNT(DISTINCT DATE(l.published_at)) >= 3
                ORDER BY n_ev DESC LIMIT :lim
                """
            ),
            {"lim": n * 2},
        )
    ).all()
    out: list[dict] = []
    for r in rows:
        if r.subject_code not in names:
            continue
        ev_rows = (
            await session.execute(
                _sql(
                    """
                    SELECT DISTINCT ON (l.evidence_id)
                        l.evidence_id, l.published_at,
                        (SELECT k2.norm_text FROM link_links l2 JOIN link_keywords k2
                          ON k2.keyword_id=l2.keyword_id AND k2.layer='dimension'
                          WHERE l2.evidence_id=l.evidence_id LIMIT 1) AS dim
                    FROM link_links l
                    JOIN link_keywords k ON k.keyword_id=l.keyword_id
                      AND k.layer='subject' AND k.norm_text=:s AND k.status='active'
                    WHERE l.published_at IS NOT NULL
                    ORDER BY l.evidence_id, l.published_at DESC
                    """
                ),
                {"s": r.subject_code},
            )
        ).all()
        if len(ev_rows) < 5:
            continue
        dates = sorted({e.published_at for e in ev_rows})
        ids: list[str] = []
        for day in (dates[0], dates[len(dates) // 2], dates[-1]):
            for e in ev_rows:
                if e.published_at == day and e.evidence_id not in ids:
                    ids.append(e.evidence_id)
        ids = ids[:5]
        if len(ids) < 4:
            continue
        dim = next((e.dim for e in ev_rows if e.dim), None)
        out.append({"subject_code": r.subject_code, "subject": names[r.subject_code],
                    "dim": dim, "evidence_ids": ids})
        if len(out) >= n:
            break
    return out


async def cross_candidates(session, names: dict[str, str], n: int) -> list[dict]:
    from sqlalchemy import text as _sql

    rows = (
        await session.execute(
            _sql(
                """
                SELECT d.norm_text AS dim, s.norm_text AS scope,
                       COUNT(DISTINCT l.evidence_id) AS n_ev,
                       COUNT(DISTINCT h.norm_text) AS n_subj
                FROM link_links l
                JOIN link_keywords d ON d.keyword_id=l.keyword_id
                  AND d.layer='dimension' AND d.status='active'
                JOIN link_links l2 ON l2.evidence_id=l.evidence_id
                JOIN link_keywords s ON s.keyword_id=l2.keyword_id
                  AND s.layer='scope' AND s.status='active' AND s.norm_text <> d.norm_text
                JOIN link_links lh ON lh.evidence_id=l.evidence_id AND lh.source='hint'
                JOIN link_keywords h ON h.keyword_id=lh.keyword_id AND h.layer='subject'
                GROUP BY d.norm_text, s.norm_text
                HAVING COUNT(DISTINCT l.evidence_id) >= 5
                   AND COUNT(DISTINCT h.norm_text) >= 3
                ORDER BY n_subj DESC, n_ev DESC LIMIT :lim
                """
            ),
            {"lim": n * 3},
        )
    ).all()
    seen = {(c.get("dimension"), c.get("scope")) for c in _existing_gold()}
    out: list[dict] = []
    for r in rows:
        if (r.dim, r.scope) in seen:
            continue
        ev_rows = (
            await session.execute(
                _sql(
                    """
                    SELECT DISTINCT ON (h.norm_text)
                        l.evidence_id, h.norm_text, l.published_at
                    FROM link_links l
                    JOIN link_keywords d ON d.keyword_id=l.keyword_id
                      AND d.layer='dimension' AND d.norm_text=:d
                    JOIN link_links l2 ON l2.evidence_id=l.evidence_id
                    JOIN link_keywords s ON s.keyword_id=l2.keyword_id
                      AND s.layer='scope' AND s.norm_text=:sc
                    JOIN link_links lh ON lh.evidence_id=l.evidence_id AND lh.source='hint'
                    JOIN link_keywords h ON h.keyword_id=lh.keyword_id AND h.layer='subject'
                    ORDER BY h.norm_text, l.published_at DESC NULLS LAST
                    """
                ),
                {"d": r.dim, "sc": r.scope},
            )
        ).all()
        picks = [e.evidence_id for e in ev_rows if e.published_at]
        if len(picks) < 3:
            continue
        out.append({"dim": r.dim, "scope": r.scope,
                    "subjects": [names.get(e.norm_text, e.norm_text) for e in ev_rows],
                    "evidence_ids": picks[:4]})
        if len(out) >= n:
            break
    return out


async def theme_candidates(session, names: dict[str, str], n: int) -> list[dict]:
    from sqlalchemy import text as _sql

    rows = (
        await session.execute(
            _sql(
                """
                SELECT s.norm_text AS scope, COUNT(DISTINCT l.evidence_id) AS n_ev,
                       COUNT(DISTINCT h.norm_text) AS n_subj
                FROM link_links l
                JOIN link_keywords s ON s.keyword_id=l.keyword_id
                  AND s.layer='scope' AND s.status='active'
                JOIN link_links lh ON lh.evidence_id=l.evidence_id AND lh.source='hint'
                JOIN link_keywords h ON h.keyword_id=lh.keyword_id AND h.layer='subject'
                GROUP BY s.norm_text
                HAVING COUNT(DISTINCT l.evidence_id) >= 20
                   AND COUNT(DISTINCT h.norm_text) >= 4
                ORDER BY n_ev DESC LIMIT :lim
                """
            ),
            {"lim": n * 3},
        )
    ).all()
    out: list[dict] = []
    for r in rows:
        ev_rows = (
            await session.execute(
                _sql(
                    """
                    SELECT DISTINCT ON (h.norm_text) l.evidence_id, h.norm_text
                    FROM link_links l
                    JOIN link_keywords s ON s.keyword_id=l.keyword_id
                      AND s.layer='scope' AND s.norm_text=:sc
                    JOIN link_links lh ON lh.evidence_id=l.evidence_id AND lh.source='hint'
                    JOIN link_keywords h ON h.keyword_id=lh.keyword_id AND h.layer='subject'
                    ORDER BY h.norm_text LIMIT 4
                    """
                ),
                {"sc": r.scope},
            )
        ).all()
        picks = [e.evidence_id for e in ev_rows if e.evidence_id][:3]
        if len(picks) < 3:
            continue
        out.append({"scope": r.scope, "evidence_ids": picks})
        if len(out) >= n:
            break
    return out


async def _verify_evidence_ids(ids: list[str], full: bool = False) -> dict[str, str]:
    from app.core.mongodb import get_mongo_db

    col = get_mongo_db().kg_evidence
    out: dict[str, str] = {}
    cur = col.find({"evidence_id": {"$in": ids}}, {"evidence_id": 1, "text_excerpt": 1})
    async for d in cur:
        text = (d.get("text_excerpt") or "")
        out[d["evidence_id"]] = text if full else text[:EXCERPT_CAP]
    return out


def _content_filter(texts: dict[str, str], tokens: list[str]) -> list[str]:
    """保留正文确含任一 token 的 evidence ids（共现噪声删除）。"""
    toks = [t for t in tokens if t and len(t) >= 2]
    if not toks:
        return list(texts)
    out = []
    for eid, text in texts.items():
        if any(tok in text for tok in toks):
            out.append(eid)
    return out


def _write_review_md(items: list[dict]) -> None:
    lines = [
        "# Gold set v2 候选终审单",
        "",
        f"生成时间：{datetime.now(UTC).isoformat(timespec='seconds')}　总数：{len(items)}",
        "",
        "审阅方法：淘汰项把 `reviewed` 从 `*` 改成 `false` 或整项删除；通过项把 `reviewed` 改成 `true`。改完 gold_candidates_v2.json 后让我汇总。",
        "",
        "---",
    ]
    for it in items:
        lines.append("")
        lines.append(f"## {it['query_id']}　[{it['type']}]")
        meta = {k: it.get(k) for k in ("subject", "dimension", "scope") if it.get(k)}
        lines.append(f"标签：{json.dumps(meta, ensure_ascii=False) if meta else '—'}")
        lines.append(f"**问题**：{it['question']}")
        for eid in it["expected_evidence_ids"]:
            ex = (it.get("excerpts") or {}).get(eid, "(摘录缺失)")
            lines.append(f"- `{eid[:24]}…`：{ex[:180]}")
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeline", type=int, default=20)
    ap.add_argument("--cross", type=int, default=20)
    ap.add_argument("--theme", type=int, default=10)
    ap.add_argument("--no-llm", action="store_true")
    args = ap.parse_args()

    from app.core.database import async_session

    v1_ids = {e for it in _existing_gold() for e in it.get("expected_evidence_ids", [])}

    async with async_session() as session:
        names = await _stock_names(session)
        tl = await timeline_candidates(session, names, args.timeline)
        cs = await cross_candidates(session, names, args.cross)
        th = await theme_candidates(session, names, args.theme)

    raws: list[tuple[str, dict]] = (
        [("timeline", c) for c in tl]
        + [("cross_section", c) for c in cs]
        + [("theme", c) for c in th]
    )

    sem = asyncio.Semaphore(8)
    items: list[dict] = []
    lock = asyncio.Lock()
    seq = 0

    async def build(kind: str, c: dict) -> None:
        nonlocal seq
        async with sem:
            needed = [e for e in c["evidence_ids"] if e not in v1_ids]
            if len(needed) < 3:
                return
            texts = await _verify_evidence_ids(needed, full=True)
            if kind == "timeline":
                tokens = [c.get("subject") or "", c.get("subject_code") or ""]
            elif kind == "cross_section":
                tokens = [c.get("scope") or "", c.get("dim") or ""]
            else:
                tokens = [c.get("scope") or ""]
            good = _content_filter(texts, tokens)
            good = [e for e in needed if e in good]
            if len(good) < 3:
                return
            display = {e: texts[e][:EXCERPT_CAP] for e in good}
            subject = c.get("subject")
            subject_code = c.get("subject_code")
            q = await _llm_question(kind, subject, c.get("dim"), c.get("scope"),
                                    [display[e] for e in good],
                                    subject_code=subject_code)
            async with lock:
                seq += 1
                items.append({
                    "query_id": f"{kind}-auto-{seq:03d}",
                    "type": kind,
                    "subject": subject or subject_code,
                    "subject_code": subject_code,
                    "dimension": c.get("dim"),
                    "scope": c.get("scope"),
                    "question": q,
                    "expected_evidence_ids": good,
                    "hard_negative_evidence_ids": [],
                    "excerpts": display,
                    "reviewed": None,
                    "note": "auto-generated; content-token filtered; pending human review",
                })

    await asyncio.gather(*[build(k, c) for k, c in raws])
    items.sort(key=lambda x: x["query_id"])

    OUT_JSON.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    _write_review_md(items)
    print(f"candidates={len(items)} -> {OUT_JSON.name} / {OUT_MD.name}")


if __name__ == "__main__":
    asyncio.run(main())
