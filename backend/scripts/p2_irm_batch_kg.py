"""
P2: batched IRM ingestion + KG extraction.

Runs a small, auditable batch of stocks through:
  1. DataFetcher.fetch_irm(ts_codes=[...])
  2. process_irm_batch([...])

The script deliberately defaults to a small batch. Use repeated runs or a
scheduler instead of one uncontrolled all-market job.

Examples:
  python scripts/p2_irm_batch_kg.py --batch-size 20
  python scripts/p2_irm_batch_kg.py --ts-codes 300593.SZ,000858.SH --force
  python scripts/p2_irm_batch_kg.py --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
from sqlalchemy import text

load_dotenv()

from app.core.database import engine
from app.core.mongodb import get_mongo_db
from app.data_pipeline.fetcher import DataFetcher
from app.data_pipeline.irm_pipeline import process_irm_batch
from app.data_pipeline.progress import FAILED, PARTIAL, SUCCESS, IngestionProgressTracker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _a_share_filter(alias: str = "") -> str:
    prefix = f"{alias}." if alias else ""
    return f"""
({prefix}ts_code ~ '^(000|001|002|003|300|301)[0-9]{{3}}\\.SZ$'
 OR {prefix}ts_code ~ '^(600|601|603|605|688|689)[0-9]{{3}}\\.SH$'
 OR {prefix}ts_code ~ '^(83|87|92)[0-9]{{4}}\\.BJ$')
AND COALESCE({prefix}name, '') NOT LIKE '%指数%'
AND COALESCE({prefix}name, '') NOT LIKE '%基金%'
AND COALESCE({prefix}name, '') NOT LIKE '%国债%'
AND COALESCE({prefix}name, '') NOT LIKE '%债%'
"""


async def _candidate_ts_codes(batch_size: int, force: bool) -> list[str]:
    if force:
        async with engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        """
                        SELECT ts_code
                        FROM stocks
                        WHERE ts_code IS NOT NULL
                          AND """
                        + _a_share_filter()
                        + """
                        ORDER BY ts_code
                        LIMIT :limit
                        """
                    ),
                    {"limit": batch_size},
                )
            ).fetchall()
        return [r[0] for r in rows]

    try:
        db = get_mongo_db()
        docs = (
            await db["irm_checkpoint"]
            .find(
                {
                    "ts_code": {
                        "$regex": r"^(000|001|002|003|300|301|600|601|603|605|688|689|83|87|92)[0-9]{3}\.(SZ|SH|BJ)$"
                    },
                    "$or": [{"status": {"$ne": "done"}}, {"status": {"$exists": False}}],
                },
                {"ts_code": 1, "_id": 0},
            )
            .limit(batch_size)
            .to_list(length=batch_size)
        )
        codes = [d["ts_code"] for d in docs if d.get("ts_code")]
        if codes:
            return codes[:batch_size]
    except Exception as exc:  # noqa: BLE001
        logger.warning("读取 IRM checkpoint 候选失败，回退 stocks: %s", exc)

    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    """
                    SELECT s.ts_code
                    FROM stocks s
                    LEFT JOIN announcements a
                      ON a.ts_code = s.ts_code AND a.announcement_type LIKE 'irm:%'
                    WHERE s.ts_code IS NOT NULL
                      AND """
                    + _a_share_filter("s")
                    + """
                    GROUP BY s.ts_code
                    ORDER BY COUNT(a.cninfo_id) ASC, s.ts_code
                    LIMIT :limit
                    """
                ),
                {"limit": batch_size},
            )
        ).fetchall()
    return [r[0] for r in rows]


async def run_batch(
    ts_codes: list[str], batch_size: int, dry_run: bool, force: bool, kg_concurrency: int
) -> dict[str, Any]:
    if not ts_codes:
        ts_codes = await _candidate_ts_codes(batch_size, force=force)
    ts_codes = [c.strip() for c in ts_codes if c.strip()]
    scope = ",".join(ts_codes[:5]) if len(ts_codes) <= 5 else f"{len(ts_codes)}_companies"
    tracker = IngestionProgressTracker(source="irm", task_name="p2_irm_batch_kg", scope=scope)
    ctx = await tracker.start_run(metadata={"ts_codes": ts_codes, "dry_run": dry_run, "force": force})
    if dry_run:
        result = {"selected": ts_codes, "dry_run": True}
        await tracker.finish_run(
            ctx,
            status=SUCCESS,
            total_items=len(ts_codes),
            processed_items=0,
            success_count=0,
            skipped_count=0,
            downloaded_count=0,
            fail_count=0,
            metadata=result,
        )
        return result

    try:
        await tracker.event(ctx, stage="fetch_start", message="P2 互动易批次抓取开始", total_items=len(ts_codes))
        fetch_result = await DataFetcher().fetch_irm(ts_codes=ts_codes, extract_to_kg=False)
        await tracker.event(
            ctx,
            stage="fetch_done",
            message="P2 互动易批次抓取完成",
            total_items=len(ts_codes),
            processed_items=len(ts_codes),
            success_count=int(fetch_result.get("success", 0) or 0),
            skipped_count=int(fetch_result.get("skipped", 0) or 0) + int(fetch_result.get("duplicates", 0) or 0),
            fail_count=int(fetch_result.get("fail", 0) or 0),
            metadata=fetch_result,
        )
        await tracker.event(ctx, stage="kg_start", message="P2 互动易批次知识构建开始", total_items=len(ts_codes))
        kg_result = await process_irm_batch(ts_codes, max_concurrency=kg_concurrency)
        result = {"selected": ts_codes, "fetch": fetch_result, "kg": kg_result}
        fail_count = int(fetch_result.get("fail", 0) or 0) + int(kg_result.get("fail", 0) or 0)
        status = FAILED if fail_count and not kg_result.get("records") else (PARTIAL if fail_count else SUCCESS)
        await tracker.finish_run(
            ctx,
            status=status,
            total_items=len(ts_codes),
            processed_items=len(ts_codes),
            success_count=int(kg_result.get("records", 0) or 0),
            skipped_count=int(fetch_result.get("skipped", 0) or 0) + int(fetch_result.get("duplicates", 0) or 0),
            downloaded_count=0,
            fail_count=fail_count,
            metadata=result,
        )
        return result
    except Exception as exc:  # noqa: BLE001
        await tracker.finish_run(
            ctx,
            status=FAILED,
            total_items=len(ts_codes),
            processed_items=0,
            success_count=0,
            skipped_count=0,
            downloaded_count=0,
            fail_count=1,
            last_error=str(exc),
            metadata={"selected": ts_codes},
        )
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description="P2 batched IRM ingestion + KG")
    parser.add_argument("--batch-size", type=int, default=20)
    parser.add_argument("--ts-codes", default="", help="comma-separated ts_codes")
    parser.add_argument("--kg-concurrency", type=int, default=2)
    parser.add_argument("--force", action="store_true", help="ignore checkpoint candidate preference")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    codes = [c.strip() for c in args.ts_codes.split(",") if c.strip()]
    result = asyncio.run(run_batch(codes, args.batch_size, args.dry_run, args.force, args.kg_concurrency))
    logger.info("P2_RESULT %s", result)


if __name__ == "__main__":
    main()
