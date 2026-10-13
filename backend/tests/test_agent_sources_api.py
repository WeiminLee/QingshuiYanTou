from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import settings
from app.data_pipeline.services import news_service
from app.knowledge.api import agent_sources

HEADERS = {"X-API-Key": "test-key"}


@pytest.fixture(autouse=True)
def _api_key(monkeypatch):
    monkeypatch.setattr(settings, "knowledge_api_key", "test-key", raising=False)
    monkeypatch.setattr(settings, "api_key", "", raising=False)


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(agent_sources.router)
    return TestClient(app)


def _patch_report(monkeypatch, payload):
    import app.knowledge.api.agent_sources as mod

    class FakeService:
        async def search_announcements(self, **kwargs):
            self.kwargs = kwargs
            return payload

        async def search_irm(self, **kwargs):
            self.kwargs = kwargs
            return payload

    fake = FakeService()
    monkeypatch.setattr(mod, "get_report_service", lambda: fake)
    return fake


def test_announcement_requires_api_key(client):
    r = client.post("/api/v1/knowledge/sources/announcement", json={"keyword": "年报"})
    assert r.status_code == 401


def test_announcement_ok(client, monkeypatch):
    rows = [{"ann_date": "20260901", "ts_code": "003026.SZ", "title": "半年度报告", "type": "定增", "summary": ""}]
    fake = _patch_report(monkeypatch, rows)
    r = client.post(
        "/api/v1/knowledge/sources/announcement",
        headers=HEADERS,
        json={"ts_code": "003026.SZ", "page_size": 5},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    assert body["items"][0]["title"] == "半年度报告"
    assert fake.kwargs["limit"] == 5


def test_irm_ok(client, monkeypatch):
    rows = [
        {"ann_date": "20260901", "ts_code": "003026.SZ", "question": "抛光硅片进展？", "answer": "客户认证中", "exchange": "sz"}
    ]
    _patch_report(monkeypatch, rows)
    r = client.post(
        "/api/v1/knowledge/sources/irm",
        headers=HEADERS,
        json={"keyword": "认证", "page_size": 20},
    )
    assert r.status_code == 200
    assert r.json()["items"][0]["answer"] == "客户认证中"


def test_events_requires_query_or_tags(client, monkeypatch):
    async def fake_search(**kwargs):
        return {"items": [], "count": 0, "note": "请至少提供搜索关键词(query)或板块标签(tags)"}

    monkeypatch.setattr(agent_sources, "search_events", fake_search)
    r = client.post(
        "/api/v1/knowledge/sources/events",
        headers=HEADERS,
        json={"top_n": 5},
    )
    assert r.status_code == 200
    assert "至少提供" in r.json()["note"]


def test_events_ok(client, monkeypatch):
    async def fake_search(**kwargs):
        return {
            "items": [{"event_id": "EV:...", "title": "光模块涨价", "summary": "", "source": "cls", "publish_at": "2026-10-01"}],
            "count": 1,
            "query": kwargs.get("query"),
            "tags": kwargs.get("tags"),
        }

    monkeypatch.setattr(agent_sources, "search_events", fake_search)
    r = client.post(
        "/api/v1/knowledge/sources/events",
        headers=HEADERS,
        json={"query": "光模块 涨价", "tags": ["CPO"]},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    assert body["tags"] == ["CPO"]
    assert body["items"][0]["title"] == "光模块涨价"


def test_event_detail_ok(client, monkeypatch):
    async def fake_detail(event_id: str):
        return {"found": True, "event_id": event_id, "title": "光模块涨价", "content": "全文……", "tags": ["CPO"]}

    monkeypatch.setattr(agent_sources, "get_event_detail", fake_detail)
    r = client.post(
        "/api/v1/knowledge/sources/event_detail",
        headers=HEADERS,
        json={"event_id": "EV:abc123"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["found"] is True
    assert body["tags"] == ["CPO"]


@pytest.mark.asyncio
async def test_news_service_search_events_requires_query_or_tags():
    out = await news_service.search_events(query=None, tags=None)
    assert out["count"] == 0
    assert "至少提供" in out["note"]
