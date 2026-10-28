#!/usr/bin/env python3
"""Generate document-level AI summaries with the self-hosted GPU.

Run on chemagent (host worker venv) with MONGODB_URL pointed at 127.0.0.1:27018
and LLM_BASE_URL pointed at the GPU :23457 endpoint:

  python -m scripts.summarize_documents --limit 20 --dry-run
  python -m scripts.summarize_documents --limit 20 --concurrency 4
  python -m scripts.summarize_documents --since 2026-01-01 --concurrency 12

Idempotent: a summary whose ``text_sha`` matches the current evidence digest is
skipped unless ``--force`` is passed.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import re
from typing import Any

from app.config import settings
from app.core.llm_client import chat_async
from app.core.mongodb import get_mongo_db
from app.knowledge.document_service import ann_id_variants
from app.knowledge.document_summary import ensure_summary_indexes, save_document_summary

logger = logging.getLogger("summarize_documents")

PROMPT = """你是投研文档摘要器。只总结材料中的事实，不写买入、卖出、估值或推荐结论。
用 150-250 个中文字符输出一段摘要，覆盖：文档类型与主体、关键数字、重大事项、风险提示。
不要编造材料没有的内容；不要用「本文」「该报告」开头。

标题：{title}
正文：
{text}
"""

_PREFIX_RE = re.compile(r"^(摘要|总结)[：:]\s*")


def _maybe_int(value: str) -> Any:
    return int(value) if value.isdigit() else value


def _meta(rows: list[dict[str, Any]]) -> tuple[str | None, str | None, str | None]:
    first = rows[0]
    ref = first.get("source_ref") if isinstance(first.get("source_ref"), dict) else {}
    subject = first.get("subject_hint") if isinstance(first.get("subject_hint"), dict) else {}
    title = subject.get("title") or ref.get("title") or first.get("source_name")
    ts_code = subject.get("ts_code") or ref.get("ts_code")
    publish_date = first.get("publish_date") or ref.get("ann_date")
    return (
        str(title).strip() if title else None,
        str(ts_code).strip() if ts_code else None,
        str(publish_date).strip() if publish_date else None,
    )


def _text(rows: list[dict[str, Any]], limit: int = 12000) -> str:
    rows = sorted(
        rows,
        key=lambda row: (
            (row.get("source_ref") or {}).get("chapter_index") is None,
            (row.get("source_ref") or {}).get("chapter_index") or 0,
            str(row.get("evidence_id") or ""),
        ),
    )
    parts: list[str] = []
    for row in rows:
        ref = row.get("source_ref") if isinstance(row.get("source_ref"), dict) else {}
        heading = str(ref.get("chapter_heading") or "").strip()
        body = str(row.get("text_excerpt") or "").strip()
        if not body:
            continue
        body = body[:1500]
        parts.append(f"## {heading}\n{body}" if heading else body)
    text = "\n\n".join(parts)
    return text[:limit] + "\n…" if len(text) > limit else text


async def _candidates(db: Any, args: argparse.Namespace) -> list[Any]:
    if args.ann_id:
        return [_maybe_int(value) for value in args.ann_id]
    match: dict[str, Any] = {
        "source_type": "announcement",
        "source_ref.ann_id": {"$exists": True},
    }
    if args.since:
        match["publish_date"] = {"$gte": args.since}
    pipeline: list[dict[str, Any]] = [
        {"$match": match},
        {"$group": {"_id": "$source_ref.ann_id"}},
        {"$sort": {"_id": 1}},
    ]
    if args.limit:
        pipeline.append({"$limit": args.limit})
    return [doc["_id"] async for doc in db.kg_evidence.aggregate(pipeline)]


async def _summarize_one(db: Any, ann_id: Any, args: argparse.Namespace) -> dict[str, Any] | None:
    rows = await db.kg_evidence.find(
        {"source_ref.ann_id": {"$in": ann_id_variants(str(ann_id))}}
    ).to_list(length=None)
    if not rows:
        return None

    actual_ann_id = (rows[0].get("source_ref") or {}).get("ann_id", ann_id)
    title, ts_code, publish_date = _meta(rows)
    text = _text(rows)
    if not text.strip():
        return None
    text_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]

    existing = await db.kg_document_summaries.find_one({"ann_id": actual_ann_id})
    if existing and existing.get("text_sha") == text_sha and not args.force:
        return {"ann_id": actual_ann_id, "skipped": True}

    model = args.model or os.environ.get("LLM_EXTRACTION_MODEL") or settings.llm_model
    raw = await chat_async(
        PROMPT.format(title=title or "", text=text),
        model=model,
        temperature=0.0,
        timeout=120,
        max_tokens=400,
        force_disable_thinking=True,
    )
    summary = _PREFIX_RE.sub("", raw.strip()).strip().strip('"“”').strip()
    if not summary:
        raise ValueError("empty summary")

    await save_document_summary(
        db,
        ann_id=actual_ann_id,
        title=title,
        ts_code=ts_code,
        publish_date=publish_date,
        summary=summary,
        model=model,
        text_sha=text_sha,
    )
    return {
        "ann_id": actual_ann_id,
        "title": title,
        "chars": len(text),
        "summary": summary,
        "skipped": False,
    }


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=0, help="max documents (0=all)")
    parser.add_argument("--since", default=None, help="publish_date >= YYYY-MM-DD")
    parser.add_argument("--ann-id", action="append", default=None, help="specific ann_id(s)")
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--model", default=None)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    db = get_mongo_db()
    await ensure_summary_indexes(db)
    candidates = await _candidates(db, args)
    logger.info("candidates=%d concurrency=%d", len(candidates), args.concurrency)
    if args.dry_run:
        for ann_id in candidates:
            print(ann_id)
        return

    sem = asyncio.Semaphore(max(1, args.concurrency))
    done = skipped = failed = 0
    lock = asyncio.Lock()

    async def run(ann_id: Any) -> None:
        nonlocal done, skipped, failed
        async with sem:
            try:
                result = await _summarize_one(db, ann_id, args)
                async with lock:
                    if result is None:
                        skipped += 1
                    elif result.get("skipped"):
                        skipped += 1
                    else:
                        done += 1
                        logger.info(
                            "summary ann_id=%s chars=%s title=%s",
                            result["ann_id"],
                            result["chars"],
                            (result.get("title") or "")[:40],
                        )
                        print(
                            json.dumps(
                                {
                                    "ann_id": result["ann_id"],
                                    "title": result.get("title"),
                                    "chars": result["chars"],
                                    "summary": result["summary"][:120],
                                },
                                ensure_ascii=False,
                            ),
                            flush=True,
                        )
            except Exception as exc:  # noqa: BLE001 — one bad doc must not stop the batch
                async with lock:
                    failed += 1
                logger.warning("summary failed ann_id=%r: %s", ann_id, exc)

    await asyncio.gather(*(run(ann_id) for ann_id in candidates))
    logger.info("finished done=%d skipped=%d failed=%d", done, skipped, failed)


if __name__ == "__main__":
    asyncio.run(main())
