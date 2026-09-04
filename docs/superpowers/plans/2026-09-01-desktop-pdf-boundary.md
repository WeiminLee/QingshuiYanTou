# Desktop PDF Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move PDF download, storage, parsing, and Evidence construction to the desktop while retaining direct WireGuard access to cloud databases and Qdrant.

**Architecture:** Cloud ingestion records source metadata and durable download jobs without downloading PDFs. A desktop PDF worker claims those jobs, downloads directly from upstream sources into `PDF_STORAGE_ROOT`, builds Evidence, and writes MongoDB/PostgreSQL/Qdrant state over WireGuard. Existing cloud API, scheduler, and database services remain unchanged.

**Tech Stack:** Python 3.11+, asyncio, PostgreSQL/asyncpg, MongoDB/Motor, Qdrant, Docker Compose, pytest.

**Spec:** `docs/superpowers/specs/2026-09-01-cloud-knowledge-boundaries-design.md`

## Global Constraints

- Worker-to-database communication uses WireGuard direct connectivity.
- Cloud services do not download new PDFs.
- Desktop is the authoritative owner of new PDF bytes and local parsing.
- Existing Evidence is never deleted or rebuilt as part of this migration.
- Secrets remain environment-injected and are not committed.
- Current acceptance is single-task/small-batch functional success; large batch throughput is deferred.

### Task 1: Download job contract

**Files:**
- Modify: `backend/app/models/models.py`
- Modify: `backend/app/data_pipeline/job_handlers.py`
- Create: `backend/tests/data_pipeline/test_pdf_download_job.py`

**Interfaces:** Add a durable `pdf_download` job payload containing source URL, source type/id, stock code, publish date, and filename; handler must be claimable by the desktop worker and idempotent by source id.

- [ ] Add failing tests for payload serialization, duplicate enqueue, and status transitions.
- [ ] Implement the contract using existing ingestion job tables and handlers.
- [ ] Run focused tests.

### Task 2: Cloud ingestion stops downloading

**Files:**
- Modify: `backend/app/data_pipeline/fetcher.py`
- Modify: `backend/app/data_pipeline/scheduler.py`
- Create: `backend/tests/data_pipeline/test_cloud_ingestion_no_download.py`

**Interfaces:** Cloud ingestion persists metadata and enqueues `pdf_download`; it must not call `FileStorage.download_*`.

- [ ] Add a failing test that patches FileStorage and asserts no download call.
- [ ] Implement metadata-only behavior with retryable job enqueue.
- [ ] Preserve existing behavior for records already having a local `file_path`.
- [ ] Run focused ingestion tests.

### Task 3: Desktop PDF worker

**Files:**
- Create: `backend/scripts/pdf_download_worker.py`
- Create: `backend/app/knowledge/pdf_download_service.py`
- Create: `backend/tests/knowledge/test_pdf_download_worker.py`

**Interfaces:** `PdfDownloadWorker.run_once(limit: int | None = None) -> dict[str, int]` claims jobs, downloads directly, saves via `FileStorage`, parses/builds Evidence, and marks job done/failed with bounded retries.

- [ ] Add tests for successful download, existing-file idempotency, invalid PDF, and retryable failure.
- [ ] Implement the worker with concurrency default 1 and signal-safe daemon mode.
- [ ] Run focused worker tests.

### Task 4: Local storage and Compose boundary

**Files:**
- Modify: `backend/app/config.py`
- Modify: `docker-compose.yml`
- Modify: `docker-compose.cloud.yml`
- Modify: `backend/.env.local-agent.example`
- Create: `docker-compose.local-agent.yml`
- Create: `backend/tests/ops/test_local_agent_compose.py`

**Interfaces:** Local-agent compose owns `pdf-download-worker`, `evidence-worker`, and Agent; `PDF_STORAGE_ROOT` is a desktop path mounted read-write only by the downloader/parser and read-only by extraction.

- [ ] Add failing compose contract tests.
- [ ] Implement service split and environment validation.
- [ ] Validate both compose configurations.

### Task 5: Documentation and functional verification

**Files:**
- Modify: `docs/运维/云端知识底座Phase1.md`
- Modify: `README.md`
- Create: `docs/运维/台式机PDFWorker迁移.md`

- [ ] Document startup order, queue ownership, local storage backup, and rollback.
- [ ] Run single-task end-to-end smoke test and focused/full tests in the standard Python 3.11 environment.
- [ ] Record remaining throughput work as deferred, not blocking.
