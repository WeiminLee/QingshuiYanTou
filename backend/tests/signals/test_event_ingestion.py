import os
from datetime import UTC, datetime
from types import SimpleNamespace

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
from app.signals.event_ingestion import event_to_source_payload, extract_event_signal_records
from app.utils.auth import verify_api_key


def test_event_to_source_payload_preserves_news_fields():
    event = SimpleNamespace(
        event_id="EV:policy",
        title="十五五规划强调算力基础设施",
        summary="政策加码",
        content="十五五规划强调算力基础设施建设。",
        publish_at=datetime(2026, 7, 14, tzinfo=UTC),
        url="https://example.test/news",
        metadata_={"tags": ["算力概念"]},
    )

    payload = event_to_source_payload(event)

    assert payload.source_type == "news"
    assert payload.source_id == "EV:policy"
    assert payload.title == "十五五规划强调算力基础设施"
    assert payload.metadata["tags"] == ["算力概念"]


def test_extract_event_signal_records_links_propagations_to_signal_ids():
    event = SimpleNamespace(
        event_id="EV:policy",
        title="十五五规划强调算力基础设施，大厂资本开支显著增加",
        summary="",
        content="十五五规划强调算力基础设施建设，多家大公司资本开支显著增加。",
        publish_at=datetime(2026, 7, 14, tzinfo=UTC),
        url=None,
        metadata_={"tags": ["算力概念"]},
    )

    signals, propagations = extract_event_signal_records(event)

    assert {s["signal_type"] for s in signals} >= {"policy", "capex"}
    assert all(s["signal_id"].startswith("SIG:") for s in signals)
    assert propagations
    assert {p["signal_id"] for p in propagations}.issubset({s["signal_id"] for s in signals})


@pytest.mark.asyncio
async def test_backfill_events_endpoint_returns_stats(monkeypatch):
    async def fake_backfill_event_signals(*args, **kwargs):
        return {"events_scanned": 3, "signals_upserted": 2, "propagations_upserted": 2}

    monkeypatch.setattr("app.signals.api.backfill_event_signals", fake_backfill_event_signals)
    app = FastAPI()
    app.dependency_overrides[verify_api_key] = lambda: "test-api-key"
    app.include_router(router, prefix="/api/v1/signals")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post("/api/v1/signals/backfill/events", headers={"x-api-key": "test-api-key"})

    assert res.status_code == 200
    assert res.json() == {"events_scanned": 3, "signals_upserted": 2, "propagations_upserted": 2}
