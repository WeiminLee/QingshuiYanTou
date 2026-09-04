"""Async client implementing the ingestion queue interface over Knowledge API."""
from __future__ import annotations
import httpx
from datetime import date, datetime
from app.data_pipeline.job_queue import IngestionJobRecord

class KnowledgeApiClient:
    def __init__(self, base_url: str, api_key: str, timeout: float = 60.0):
        self.base_url = base_url.rstrip("/")
        self.headers = {"X-API-Key": api_key}
        self.timeout = timeout

    async def claim_jobs(self, worker_id, limit=20, job_types=None):
        payload = {"worker_id": worker_id, "limit": limit}
        if job_types: payload["job_types"] = list(job_types)
        async with httpx.AsyncClient(timeout=self.timeout) as c:
            r = await c.post(f"{self.base_url}/api/v1/knowledge/jobs/claim", json=payload, headers=self.headers)
            r.raise_for_status()
            data = r.json()
        return [IngestionJobRecord(**item) for item in data.get("jobs", [])]

    async def mark_success(self, job_id, worker_id, result_summary):
        return await self._finish(job_id, "success", {"worker_id": worker_id, "result_summary": result_summary})

    async def mark_failure(self, job_id, worker_id, error, attempt_count, max_attempts, error_category=None):
        return await self._finish(job_id, "failure", {"worker_id": worker_id, "error": error, "attempt_count": attempt_count, "max_attempts": max_attempts, "error_category": error_category})

    async def _finish(self, job_id, action, payload):
        async with httpx.AsyncClient(timeout=self.timeout) as c:
            r = await c.post(f"{self.base_url}/api/v1/knowledge/jobs/{job_id}/{action}", json=payload, headers=self.headers)
        return r.is_success

    async def upsert_evidence(self, input_obj, chunk_index=0):
        async with httpx.AsyncClient(timeout=self.timeout) as c:
            data = {k: (v.isoformat() if isinstance(v, (date, datetime)) else v) for k, v in input_obj.__dict__.items()}
            r = await c.post(f"{self.base_url}/api/v1/knowledge/evidence/upsert", json={"input": data, "chunk_index": chunk_index}, headers=self.headers)
            r.raise_for_status()
            return r.json().get("evidence")
