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
from app.data_pipeline.pdf_download_contract import PdfDownloadJobPayload

# 通用 ingestion worker 只处理这些 job_type。pdf_download 由专用
# PdfDownloadWorker 处理（它有自己的 job 契约与落盘逻辑）；若通用 worker 也领，
# execute_ingestion_job 会抛 "unsupported ingestion job_type"，把下载任务判死
# （实战：203 个 pdf_download 被误判 dead，公告 evidence 断流 27 天）。
SUPPORTED_INGESTION_JOB_TYPES = (JOB_CNINFO_ANNOUNCEMENT_DATE, JOB_IRM_COMPANY)


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
        result = await active_fetcher.fetch_minishare_announcements(ann_date=date_key)
        return _result_from_fetcher_result(result)
    if job.job_type == JOB_IRM_COMPANY:
        ts_code = str(job.payload["ts_code"])
        active_fetcher = fetcher or DataFetcher()
        result = await active_fetcher.fetch_irm(ts_codes=[ts_code], extract_to_kg=True)
        return _result_from_fetcher_result(result)
    raise ValueError(f"unsupported ingestion job_type: {job.job_type}")


def parse_pdf_download_job_payload(payload: dict[str, Any]) -> PdfDownloadJobPayload:
    """Validate the durable PDF download job contract."""

    return PdfDownloadJobPayload.from_payload(payload)


def _result_from_fetcher_result(result: dict[str, Any]) -> JobExecutionResult:
    fail = int(result.get("fail", 0) or 0)
    status = JOB_SUCCESS if fail == 0 else JOB_FAILED
    error = None if fail == 0 else str(result.get("last_error") or f"fetcher returned fail={fail}")
    return JobExecutionResult(status=status, summary=result, error=error)
