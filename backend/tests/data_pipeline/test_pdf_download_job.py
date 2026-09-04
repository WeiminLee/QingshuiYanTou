"""Tests for the durable PDF download job contract."""

from __future__ import annotations

import asyncio
import importlib.util
import json
from datetime import date
from pathlib import Path
from types import ModuleType
import sys

from sqlalchemy.orm import declarative_base


BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _load_module(module_name: str, relative_path: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(module_name, BACKEND_ROOT / relative_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _load_data_pipeline_modules() -> tuple[ModuleType, ModuleType]:
    if "app.core.database" not in sys.modules:
        core_database = ModuleType("app.core.database")
        core_database.Base = declarative_base()
        core_database.engine = object()
        sys.modules["app.core.database"] = core_database
    if "app.data_pipeline" not in sys.modules:
        package = ModuleType("app.data_pipeline")
        package.__path__ = [str(BACKEND_ROOT / "app" / "data_pipeline")]
        sys.modules["app.data_pipeline"] = package
    if "app.data_pipeline.fetcher" not in sys.modules:
        fetcher = ModuleType("app.data_pipeline.fetcher")

        class DummyDataFetcher:
            pass

        fetcher.DataFetcher = DummyDataFetcher
        sys.modules["app.data_pipeline.fetcher"] = fetcher
    if "app.data_pipeline.pdf_download_contract" not in sys.modules:
        _load_module(
            "app.data_pipeline.pdf_download_contract",
            "app/data_pipeline/pdf_download_contract.py",
        )
    job_queue = _load_module("app.data_pipeline.job_queue", "app/data_pipeline/job_queue.py")
    job_handlers = _load_module("app.data_pipeline.job_handlers", "app/data_pipeline/job_handlers.py")
    return job_queue, job_handlers


class FakeAsyncResult:
    def __init__(self, rows: list[dict] | None = None, rowcount: int = 0) -> None:
        self._rows = rows or []
        self.rowcount = rowcount

    def mappings(self) -> "FakeAsyncResult":
        return self

    def all(self) -> list[dict]:
        return self._rows


class FakeAsyncConnection:
    def __init__(self, result: FakeAsyncResult | None = None) -> None:
        self.result = result or FakeAsyncResult()
        self.calls: list[tuple[object, dict]] = []

    async def execute(self, sql: object, params: dict) -> FakeAsyncResult:
        self.calls.append((sql, params))
        return self.result


class FakeAsyncBegin:
    def __init__(self, connection: FakeAsyncConnection) -> None:
        self.connection = connection

    async def __aenter__(self) -> FakeAsyncConnection:
        return self.connection

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None


class FakeAsyncEngine:
    def __init__(self, connection: FakeAsyncConnection) -> None:
        self.connection = connection

    def begin(self) -> FakeAsyncBegin:
        return FakeAsyncBegin(self.connection)


def test_pdf_download_job_payload_serializes_and_parses_stably() -> None:
    _, job_handlers = _load_data_pipeline_modules()
    contract = sys.modules["app.data_pipeline.pdf_download_contract"]

    job = contract.PdfDownloadJobPayload(
        source_url="https://example.invalid/files/report.pdf",
        source_type="cninfo",
        source_id="cninfo-20260901-0001",
        stock_code="600000.SH",
        publish_date=date(2026, 9, 1),
        filename="600000.SH-20260901.pdf",
    )

    payload = job.to_payload()

    assert job.job_key == "cninfo-20260901-0001"
    assert payload == {
        "source_url": "https://example.invalid/files/report.pdf",
        "source_type": "cninfo",
        "source_id": "cninfo-20260901-0001",
        "stock_code": "600000.SH",
        "publish_date": "2026-09-01",
        "filename": "600000.SH-20260901.pdf",
    }
    assert job_handlers.parse_pdf_download_job_payload(payload) == job


def test_pdf_download_job_enqueue_uses_source_id_as_dedup_key(monkeypatch) -> None:
    job_queue, _ = _load_data_pipeline_modules()
    contract = sys.modules["app.data_pipeline.pdf_download_contract"]
    JOB_PDF_DOWNLOAD = job_queue.JOB_PDF_DOWNLOAD

    connection = FakeAsyncConnection()
    monkeypatch.setattr(job_queue, "engine", FakeAsyncEngine(connection))

    queue = job_queue.IngestionJobQueue()
    job = contract.PdfDownloadJobPayload(
        source_url="https://example.invalid/files/report.pdf",
        source_type="cninfo",
        source_id="cninfo-20260901-0001",
        stock_code="600000.SH",
        publish_date=date(2026, 9, 1),
        filename="600000.SH-20260901.pdf",
    )
    updated_payload = {
        **job.to_payload(),
        "filename": "600000.SH-20260901-v2.pdf",
    }

    asyncio.run(queue.enqueue_job(JOB_PDF_DOWNLOAD, job.job_key, job.to_payload(), priority=25, max_attempts=8))
    asyncio.run(queue.enqueue_job(JOB_PDF_DOWNLOAD, job.job_key, updated_payload, priority=10, max_attempts=9))

    assert len(connection.calls) == 2
    sql = str(connection.calls[1][0])
    params = connection.calls[1][1]
    assert "ON CONFLICT (job_type, job_key) DO UPDATE" in sql
    assert params["job_type"] == JOB_PDF_DOWNLOAD
    assert params["job_key"] == job.job_key
    assert params["payload"] == json.dumps(updated_payload, ensure_ascii=False)
    assert params["priority"] == 10
    assert params["max_attempts"] == 9


def test_pdf_download_job_can_be_claimed_and_marked_success(monkeypatch) -> None:
    job_queue, _ = _load_data_pipeline_modules()
    contract = sys.modules["app.data_pipeline.pdf_download_contract"]
    JOB_PDF_DOWNLOAD = job_queue.JOB_PDF_DOWNLOAD

    job = contract.PdfDownloadJobPayload(
        source_url="https://example.invalid/files/report.pdf",
        source_type="cninfo",
        source_id="cninfo-20260901-0001",
        stock_code="600000.SH",
        publish_date=date(2026, 9, 1),
        filename="600000.SH-20260901.pdf",
    )
    connection = FakeAsyncConnection(
        FakeAsyncResult(
            [
                {
                    "id": 42,
                    "job_type": JOB_PDF_DOWNLOAD,
                    "job_key": job.job_key,
                    "status": "running",
                    "payload": job.to_payload(),
                    "priority": 25,
                    "attempt_count": 0,
                    "max_attempts": 8,
                    "locked_by": "desktop-worker",
                }
            ],
            rowcount=1,
        )
    )
    monkeypatch.setattr(job_queue, "engine", FakeAsyncEngine(connection))

    queue = job_queue.IngestionJobQueue()
    claimed = asyncio.run(queue.claim_jobs("desktop-worker", limit=1, job_types=[JOB_PDF_DOWNLOAD]))

    assert claimed[0].job_type == JOB_PDF_DOWNLOAD
    assert claimed[0].payload == job.to_payload()
    assert claimed[0].status == "running"

    claim_sql = str(connection.calls[0][0])
    claim_params = connection.calls[0][1]
    assert "job_type = ANY(CAST(:job_types AS text[]))" in claim_sql
    assert claim_params["job_types"] == [JOB_PDF_DOWNLOAD]

    connection.result = FakeAsyncResult(rowcount=1)
    finished = asyncio.run(queue.mark_success(42, "desktop-worker", {"saved": 1}))

    finish_sql = str(connection.calls[1][0])
    finish_params = connection.calls[1][1]
    assert finished is True
    assert "status = 'running'" in finish_sql
    assert finish_params["worker_id"] == "desktop-worker"
    assert finish_params["result_summary"] == json.dumps({"saved": 1}, ensure_ascii=False)
