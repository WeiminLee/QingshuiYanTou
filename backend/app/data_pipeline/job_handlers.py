"""Execution handlers for durable ingestion jobs."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.data_pipeline.fetcher import DataFetcher
from app.data_pipeline.job_queue import (
    JOB_CNINFO_ANNOUNCEMENT_DATE,
    JOB_FAILED,
    JOB_IRM_COMPANY,
    JOB_SUCCESS,
    IngestionJobRecord,
)


@dataclass(frozen=True)
class JobExecutionResult:
    status: str
    summary: dict[str, Any]
    error: str | None = None


async def execute_ingestion_job(
    job: IngestionJobRecord,
    fetcher: DataFetcher | None = None,
) -> JobExecutionResult:
    if job.job_type == JOB_CNINFO_ANNOUNCEMENT_DATE:
        date_key = str(job.payload["date"])
        active_fetcher = fetcher or DataFetcher()
        result = await active_fetcher.fetch_announcements(ann_date=date_key)
        return _result_from_fetcher_result(result)
    if job.job_type == JOB_IRM_COMPANY:
        ts_code = str(job.payload["ts_code"])
        active_fetcher = fetcher or DataFetcher()
        result = await active_fetcher.fetch_irm(ts_codes=[ts_code], extract_to_kg=False)
        return _result_from_fetcher_result(result)
    raise ValueError(f"unsupported ingestion job_type: {job.job_type}")


def _result_from_fetcher_result(result: dict[str, Any]) -> JobExecutionResult:
    fail = int(result.get("fail", 0) or 0)
    status = JOB_SUCCESS if fail == 0 else JOB_FAILED
    error = None if fail == 0 else f"fetcher returned fail={fail}"
    return JobExecutionResult(status=status, summary=result, error=error)
