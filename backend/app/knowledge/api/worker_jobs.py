"""HTTPS boundary for remote PDF/Evidence workers."""
from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from app.config import settings
from app.data_pipeline.job_queue import IngestionJobQueue
from app.knowledge.evidence import EvidenceInput
from app.knowledge.evidence_service import EvidenceService

router = APIRouter(prefix="/api/v1/knowledge/jobs", tags=["知识 Worker"])

def _auth(key: str | None) -> None:
    expected = settings.knowledge_api_key or settings.api_key
    if not expected or key != expected:
        raise HTTPException(401, "无效 API 密钥")

class ClaimRequest(BaseModel):
    worker_id: str = Field(min_length=1, max_length=200)
    limit: int = Field(default=1, ge=1, le=100)
    job_types: list[str] | None = None

class FinishRequest(BaseModel):
    worker_id: str = Field(min_length=1, max_length=200)
    result_summary: dict[str, Any] = Field(default_factory=dict)

class FailureRequest(BaseModel):
    worker_id: str = Field(min_length=1, max_length=200)
    error: str = Field(min_length=1, max_length=4000)
    attempt_count: int = Field(default=0, ge=0)
    max_attempts: int = Field(default=5, ge=1)
    error_category: str | None = None

@router.post("/claim")
async def claim(req: ClaimRequest, x_api_key: str | None = Header(default=None)):
    _auth(x_api_key)
    jobs = await IngestionJobQueue().claim_jobs(req.worker_id, limit=req.limit, job_types=req.job_types)
    return {"jobs": [j.__dict__ for j in jobs]}

@router.post("/{job_id}/success")
async def success(job_id: int, req: FinishRequest, x_api_key: str | None = Header(default=None)):
    _auth(x_api_key)
    ok = await IngestionJobQueue().mark_success(job_id, req.worker_id, req.result_summary)
    if not ok: raise HTTPException(409, "任务不存在或租约已失效")
    return {"ok": True}

@router.post("/{job_id}/failure")
async def failure(job_id: int, req: FailureRequest, x_api_key: str | None = Header(default=None)):
    _auth(x_api_key)
    ok = await IngestionJobQueue().mark_failure(job_id, req.worker_id, req.error, req.attempt_count, req.max_attempts, req.error_category)
    if not ok: raise HTTPException(409, "任务不存在或租约已失效")
    return {"ok": True}

class EvidenceRequest(BaseModel):
    input: dict[str, Any]
    chunk_index: int = Field(default=0, ge=0)

evidence_router = APIRouter(prefix="/api/v1/knowledge/evidence", tags=["知识 Worker"])
@evidence_router.get("/{evidence_id}")
async def evidence_get(evidence_id: str, x_api_key: str | None = Header(default=None)):
    _auth(x_api_key); item = await EvidenceService().get_evidence(evidence_id)
    if not item: raise HTTPException(404, "Evidence not found")
    return item

@evidence_router.post("/jobs/claim")
async def extraction_claim(req: ClaimRequest, x_api_key: str | None = Header(default=None)):
    _auth(x_api_key)
    svc = EvidenceService(); jobs=[]
    for _ in range(req.limit):
        job = await svc.claim_next_job(job_type=(req.job_types[0] if req.job_types else "combined"), worker_id=req.worker_id)
        if not job: break
        jobs.append(job)
    return {"jobs": jobs}

@evidence_router.post("/jobs/{job_id}/success")
async def extraction_success(job_id: str, req: FinishRequest, x_api_key: str | None = Header(default=None)):
    _auth(x_api_key); await EvidenceService().mark_job_done(job_id, req.result_summary); return {"ok": True}

@evidence_router.post("/jobs/{job_id}/failure")
async def extraction_failure(job_id: str, req: FailureRequest, x_api_key: str | None = Header(default=None)):
    _auth(x_api_key); await EvidenceService().mark_job_failed(job_id, req.error); return {"ok": True}
@evidence_router.post("/upsert")
async def evidence_upsert(req: EvidenceRequest, x_api_key: str | None = Header(default=None)):
    _auth(x_api_key)
    try:
        item = EvidenceInput(**req.input)
        result = await EvidenceService().upsert_evidence(item, chunk_index=req.chunk_index)
    except Exception as exc:
        raise HTTPException(400, f"invalid evidence: {exc}") from exc
    return {"evidence": result}
