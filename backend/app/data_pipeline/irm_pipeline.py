"""IRM Q&A to KG orchestration."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from sqlalchemy import text

from app.core.database import engine
from app.data_pipeline.progress import (
    FAILED,
    PARTIAL,
    SUCCESS,
    IngestionProgressTracker,
)
from app.knowledge.irm_extractor import create_irm_evidence_jobs, extract_irm_batch

logger = logging.getLogger(__name__)
IRM_KG_PROGRESS_EVERY = 5


async def get_irm_records_from_db(ts_code: str) -> list[dict[str, Any]]:
    sql = """
    SELECT ts_code, name, title, type, cninfo_id, ann_date
    FROM announcements
    WHERE ts_code = :ts_code
      AND announcement_type LIKE 'irm:%'
    ORDER BY ann_date DESC
    """
    async with engine.connect() as conn:
        rows = (await conn.execute(text(sql), {"ts_code": ts_code})).mappings().all()
    return [
        {
            "ts_code": row["ts_code"],
            "company_name": row["name"] or row["ts_code"],
            "question": row["title"],
            "answer": row["type"],
            "cninfo_id": row["cninfo_id"],
            "ann_date": row["ann_date"],
        }
        for row in rows
    ]


async def process_irm_for_company(
    ts_code: str,
    progress_callback: Any | None = None,
    evidence_first: bool = True,
) -> dict[str, int]:
    records = await get_irm_records_from_db(ts_code)
    if not records:
        if progress_callback:
            await progress_callback(
                stage="company_skipped",
                message="互动易公司无可抽取问答",
                item_id=ts_code,
                metadata={"records": 0},
            )
        return {
            "companies": 1,
            "records": 0,
            "entities": 0,
            "relations": 0,
            "fail": 0,
            "skipped": 0,
        }
    if progress_callback:
        await progress_callback(
            stage="company_start",
            message="互动易公司知识构建开始",
            item_id=ts_code,
            total_items=len(records),
            metadata={"records": len(records)},
        )
    if evidence_first:
        result = await create_irm_evidence_jobs(records, progress_callback=progress_callback)
    else:
        result = await extract_irm_batch(records, progress_callback=progress_callback)
    if progress_callback:
        await progress_callback(
            stage="company_done",
            message="互动易公司知识构建完成",
            item_id=ts_code,
            total_items=len(records),
            processed_items=len(records),
            success_count=result.get("records", 0),
            skipped_count=result.get("skipped", 0),
            fail_count=result.get("fail", 0),
            metadata=result,
        )
    return {"companies": 1, **result}


async def process_irm_batch(
    ts_codes: list[str], max_concurrency: int = 4, evidence_first: bool = True
) -> dict[str, int]:
    semaphore = asyncio.Semaphore(max_concurrency)
    scope = ",".join(ts_codes[:5]) if len(ts_codes) <= 5 else f"{len(ts_codes)}_companies"
    tracker = IngestionProgressTracker(
        source="irm",
        task_name="kg_extract",
        scope=scope,
    )
    run_ctx = await tracker.start_run(
        metadata={
            "companies": ts_codes,
            "max_concurrency": max_concurrency,
            "evidence_first": evidence_first,
        },
    )
    total_companies = len(ts_codes)
    totals = {
        "companies": 0,
        "records": 0,
        "entities": 0,
        "relations": 0,
        "fail": 0,
        "skipped": 0,
        "qa_vectors": 0,
        "entity_vectors": 0,
        "relation_vectors": 0,
    }
    totals_lock = asyncio.Lock()

    async def emit_event(**kwargs: Any) -> None:
        await tracker.event(run_ctx, **kwargs)

    async def worker(code: str) -> dict[str, int]:
        async with semaphore:
            try:
                return await process_irm_for_company(code, progress_callback=emit_event, evidence_first=evidence_first)
            except Exception as exc:  # noqa: BLE001
                logger.warning("IRM company processing failed [%s]: %s", code, exc)
                await tracker.event(
                    run_ctx,
                    stage="company_error",
                    message="互动易公司知识构建失败",
                    item_id=code,
                    error=str(exc),
                )
                return {
                    "companies": 1,
                    "records": 0,
                    "entities": 0,
                    "relations": 0,
                    "fail": 1,
                    "skipped": 0,
                }

    async def tracked_worker(code: str) -> dict[str, int]:
        result = await worker(code)
        async with totals_lock:
            for key in totals:
                totals[key] += int(result.get(key, 0) or 0)
            snapshot = dict(totals)
        await tracker.update_run(
            run_ctx,
            total_items=total_companies,
            processed_items=snapshot["companies"],
            success_count=snapshot["records"],
            skipped_count=snapshot["skipped"],
            fail_count=snapshot["fail"],
            last_item_id=code,
        )
        if (
            snapshot["companies"] % IRM_KG_PROGRESS_EVERY == 0
            or snapshot["companies"] == total_companies
            or total_companies <= IRM_KG_PROGRESS_EVERY
        ):
            await tracker.event(
                run_ctx,
                stage="batch_progress",
                message="互动易知识构建批次进展",
                total_items=total_companies,
                processed_items=snapshot["companies"],
                success_count=snapshot["records"],
                skipped_count=snapshot["skipped"],
                fail_count=snapshot["fail"],
                item_id=code,
                metadata={
                    "entities": snapshot["entities"],
                    "relations": snapshot["relations"],
                    "qa_vectors": snapshot["qa_vectors"],
                    "entity_vectors": snapshot["entity_vectors"],
                    "relation_vectors": snapshot["relation_vectors"],
                    "skipped": snapshot["skipped"],
                },
            )
        return result

    try:
        await asyncio.gather(*(tracked_worker(code) for code in ts_codes))
        status = FAILED if totals["fail"] and not totals["records"] else (PARTIAL if totals["fail"] else SUCCESS)
        await tracker.finish_run(
            run_ctx,
            status=status,
            total_items=total_companies,
            processed_items=totals["companies"],
            success_count=totals["records"],
            skipped_count=totals["skipped"],
            downloaded_count=0,
            fail_count=totals["fail"],
            last_item_id=ts_codes[-1] if ts_codes else None,
            metadata=totals,
        )
    except Exception as exc:  # noqa: BLE001
        await tracker.finish_run(
            run_ctx,
            status=FAILED,
            total_items=total_companies,
            processed_items=totals["companies"],
            success_count=totals["records"],
            skipped_count=totals["skipped"],
            downloaded_count=0,
            fail_count=max(1, totals["fail"]),
            last_error=str(exc),
            metadata=totals,
        )
        raise
    return totals
