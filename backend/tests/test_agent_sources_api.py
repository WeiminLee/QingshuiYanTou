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
    body = r.json()
    assert body["items"][0]["answer"] == "客户认证中"
    assert "note" not in body


def test_irm_accepts_the_iso_dates_agents_send(client, monkeypatch):
    """本地 agent 会传 YYYY-MM-DD。这正是 get_irm 422 的那次调用。"""
    fake = _patch_report(monkeypatch, [])
    r = client.post(
        "/api/v1/knowledge/sources/irm",
        headers=HEADERS,
        json={"keyword": "博通", "end_date": "2026-10-20", "start_date": "2026-09-01", "page_size": 10},
    )
    assert r.status_code == 200
    assert fake.kwargs["keyword"] == "博通"
    assert fake.kwargs["start_date"] == "20260901"
    assert fake.kwargs["end_date"] == "20261020"
    assert fake.kwargs["limit"] == 10
    assert "note" not in r.json()


def test_irm_keeps_compact_dates(client, monkeypatch):
    fake = _patch_report(monkeypatch, [])
    r = client.post(
        "/api/v1/knowledge/sources/irm",
        headers=HEADERS,
        json={"keyword": "博通", "start_date": "20260901", "end_date": "20261020"},
    )
    assert r.status_code == 200
    assert fake.kwargs["start_date"] == "20260901"
    assert fake.kwargs["end_date"] == "20261020"


def test_irm_blank_date_stays_open(client, monkeypatch):
    fake = _patch_report(monkeypatch, [])
    r = client.post(
        "/api/v1/knowledge/sources/irm",
        headers=HEADERS,
        json={"keyword": "博通", "start_date": "", "end_date": None},
    )
    assert r.status_code == 200
    assert fake.kwargs["start_date"] is None
    assert fake.kwargs["end_date"] is None


def test_irm_bad_params_return_rows_with_a_note(client, monkeypatch):
    fake = _patch_report(monkeypatch, [])
    r = client.post(
        "/api/v1/knowledge/sources/irm",
        headers=HEADERS,
        json={
            "keyword": "博通",
            "start_date": "yesterday",
            "end_date": "2026-13-40",
            "page_size": 500,
            "ts_code": "不是代码",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 0
    assert "无法识别" in body["note"]
    assert "page_size 超过 200" in body["note"]
    assert "不是证券代码" in body["note"]
    assert fake.kwargs["keyword"] == "博通"
    assert fake.kwargs["ts_code"] is None
    assert fake.kwargs["start_date"] is None
    assert fake.kwargs["end_date"] is None
    assert fake.kwargs["limit"] == 200


def test_irm_company_name_in_ts_code_becomes_keyword(client, monkeypatch):
    fake = _patch_report(monkeypatch, [])
    r = client.post(
        "/api/v1/knowledge/sources/irm",
        headers=HEADERS,
        json={"ts_code": "博通", "page_size": "abc"},
    )
    assert r.status_code == 200
    body = r.json()
    assert "改按关键词查询" in body["note"]
    assert "page_size" in body["note"]
    assert fake.kwargs["keyword"] == "博通"
    assert fake.kwargs["ts_code"] is None
    assert fake.kwargs["limit"] == 20


def test_irm_body_that_is_not_an_object_still_returns(client, monkeypatch):
    fake = _patch_report(monkeypatch, [])
    r = client.post(
        "/api/v1/knowledge/sources/irm",
        headers=HEADERS,
        json=["博通"],
    )
    assert r.status_code == 200
    assert "请求体不是对象" in r.json()["note"]
    assert fake.kwargs["keyword"] is None
    assert fake.kwargs["limit"] == 20


def test_announcement_accepts_iso_dates(client, monkeypatch):
    fake = _patch_report(monkeypatch, [])
    r = client.post(
        "/api/v1/knowledge/sources/announcement",
        headers=HEADERS,
        json={"keyword": "合同", "start_date": "2026-09-01", "end_date": "2026/10/20", "page_size": 5},
    )
    assert r.status_code == 200
    assert fake.kwargs["start_date"] == "20260901"
    assert fake.kwargs["end_date"] == "20261020"


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


def test_recent_events_ok(client, monkeypatch):
    async def fake_recent(limit: int):
        return {"items": [{"event_id": "EV:abc", "title": "存储芯片"}], "count": 1, "limit": limit}

    monkeypatch.setattr(agent_sources, "list_recent_events", fake_recent)
    r = client.post(
        "/api/v1/knowledge/sources/events/recent",
        headers=HEADERS,
        json={"limit": 8},
    )
    assert r.status_code == 200
    assert r.json()["limit"] == 8
    assert r.json()["items"][0]["title"] == "存储芯片"


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
