import os
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("MONGODB_URL", "mongodb://localhost:27017/test")
os.environ.setdefault("LLM_API_KEY", "test-key")
os.environ.setdefault("NEO4J_PASSWORD", "test-password")
os.environ.setdefault("MASTER_PASSWORD", "test-master-pass-1234")
os.environ.setdefault("API_KEY", "test-api-key")

from app.signals.api import router
from app.signals.evidence_ingestion import evidence_to_source_payload, extract_evidence_signal_records
from app.utils.auth import verify_api_key


def test_evidence_to_source_payload_preserves_announcement_fields():
    evidence = {
        "evidence_id": "EV:evidence-1",
        "source_type": "announcement",
        "source_name": "重大合同公告",
        "source_id": "ann-1",
        "subject_hint": {"ts_code": "300001.SZ", "company_name": "测试公司", "title": "重大合同公告"},
        "publish_date": datetime(2026, 7, 14, tzinfo=UTC),
        "text_excerpt": "公司签订重大合同，相关产品进入规模化交付阶段。",
        "source_ref": {"pdf_url": "https://example.test/a.pdf"},
        "metadata": {"chapter": "合同"},
    }

    payload = evidence_to_source_payload(evidence)

    assert payload.source_type == "announcement"
    assert payload.source_id == "EV:evidence-1"
    assert payload.title == "重大合同公告"
    assert payload.content == "公司签订重大合同，相关产品进入规模化交付阶段。"
    assert payload.url == "https://example.test/a.pdf"
    assert payload.metadata["evidence_id"] == "EV:evidence-1"
    assert payload.metadata["subject_hint"]["ts_code"] == "300001.SZ"


def test_extract_evidence_signal_records_detects_announcement_order_and_mass_production():
    evidence = {
        "evidence_id": "EV:evidence-1",
        "source_type": "announcement",
        "source_name": "重大合同公告",
        "source_id": "ann-1",
        "subject_hint": {"title": "重大合同公告"},
        "publish_date": datetime(2026, 7, 14, tzinfo=UTC),
        "text_excerpt": "公司签订重大合同，相关产品进入规模化交付阶段。",
        "source_ref": {},
        "metadata": {},
    }

    signals, propagations = extract_evidence_signal_records(evidence)

    assert {s["signal_type"] for s in signals} >= {"order", "mass_production"}
    assert all(s["source_id"] == "EV:evidence-1" for s in signals)
    assert propagations
    assert {p["signal_id"] for p in propagations}.issubset({s["signal_id"] for s in signals})


@pytest.mark.asyncio
async def test_backfill_evidence_endpoint_returns_stats(monkeypatch):
    async def fake_backfill_evidence_signals(*args, **kwargs):
        return {"evidence_scanned": 4, "signals_upserted": 3, "propagations_upserted": 3}

    monkeypatch.setattr("app.signals.api.backfill_evidence_signals", fake_backfill_evidence_signals)
    app = FastAPI()
    app.dependency_overrides[verify_api_key] = lambda: "test-api-key"
    app.include_router(router, prefix="/api/v1/signals")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post(
            "/api/v1/signals/backfill/evidence",
            params={"source_type": "announcement"},
            headers={"x-api-key": "test-api-key"},
        )

    assert res.status_code == 200
    assert res.json() == {"evidence_scanned": 4, "signals_upserted": 3, "propagations_upserted": 3}
