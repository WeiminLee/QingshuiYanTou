from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import settings
from app.knowledge.api.agent_metrics import router as agent_metrics_router

HEADERS = {"X-API-Key": "test-key"}


@pytest.fixture(autouse=True)
def _api_key(monkeypatch):
    monkeypatch.setattr(settings, "knowledge_api_key", "test-key", raising=False)
    monkeypatch.setattr(settings, "api_key", "", raising=False)


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(agent_metrics_router)
    return TestClient(app)


def _tool_mock(result):
    tool = MagicMock()
    tool.name = "mock"
    tool.ainvoke = AsyncMock(return_value=result)
    return tool


def test_compare_metric_requires_key(client):
    r = client.post("/api/v1/knowledge/agent/compare_metric", json={"dimension": "毛利率"})
    assert r.status_code == 401


def test_compare_metric_ok(client):
    tool = _tool_mock({"dimension": "毛利率", "scope": "硅片", "count": 1, "items": [{"subject": "300861.SZ", "value": "90%", "period": "FY 2025", "evidence_id": "EV:1"}]})
    with patch("app.reasoning.tools.knowledge.metric_ops.compare_metric", tool):
        # patch where used inside handler via late import — patch module attr before import path used
        with patch.dict("sys.modules", {}):
            pass
    with patch(
        "app.knowledge.api.agent_metrics._ainvoke",
        new=AsyncMock(return_value=tool.ainvoke.return_value),
    ):
        r = client.post(
            "/api/v1/knowledge/agent/compare_metric",
            headers=HEADERS,
            json={"dimension": "毛利率", "scope": "硅片", "top_k": 10},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    assert body["items"][0]["evidence_id"] == "EV:1"


def test_metric_trend_ok(client):
    with patch(
        "app.knowledge.api.agent_metrics._ainvoke",
        new=AsyncMock(return_value={"subject": "600962.SH", "count": 2, "timeline": []}),
    ):
        r = client.post(
            "/api/v1/knowledge/agent/metric_trend",
            headers=HEADERS,
            json={"subject": "600962.SH", "dimension": "营业收入"},
        )
    assert r.status_code == 200
    assert r.json()["subject"] == "600962.SH"


def test_rollup_metric_ok(client):
    with patch(
        "app.knowledge.api.agent_metrics._ainvoke",
        new=AsyncMock(return_value={"parent": "营收", "count": 1, "children": [{"child_metric": "营业收入", "evidence_count": 10}]}),
    ):
        r = client.post(
            "/api/v1/knowledge/agent/rollup_metric",
            headers=HEADERS,
            json={"parent": "营收"},
        )
    assert r.status_code == 200
    assert r.json()["parent"] == "营收"
