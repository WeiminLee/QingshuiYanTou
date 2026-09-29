from __future__ import annotations

from unittest.mock import AsyncMock, patch

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


def test_compare_metric_requires_key(client):
    r = client.post("/api/v1/knowledge/agent/compare_metric", json={"dimension": "毛利率"})
    assert r.status_code == 401


def test_compare_metric_ok(client):
    result = {
        "dimension": "毛利率",
        "scope": "硅片",
        "count": 1,
        "items": [{"subject": "300861.SZ", "value": "90%", "period": "FY 2025", "evidence_id": "EV:1"}],
    }
    with patch(
        "app.knowledge.agent_metric_ops.compare_metric",
        new=AsyncMock(return_value=result),
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
        "app.knowledge.agent_metric_ops.metric_trend",
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
        "app.knowledge.agent_metric_ops.rollup_metric",
        new=AsyncMock(
            return_value={
                "parent": "营收",
                "count": 1,
                "children": [{"child_metric": "营业收入", "evidence_count": 10}],
            }
        ),
    ):
        r = client.post(
            "/api/v1/knowledge/agent/rollup_metric",
            headers=HEADERS,
            json={"parent": "营收"},
        )
    assert r.status_code == 200
    assert r.json()["parent"] == "营收"


def test_related_nodes_ok(client):
    with patch(
        "app.knowledge.agent_graph_ops.related_nodes",
        new=AsyncMock(return_value={"keyword": "硅片", "found": True, "neighbors": []}),
    ):
        r = client.post(
            "/api/v1/knowledge/agent/related_nodes",
            headers=HEADERS,
            json={"keyword": "硅片"},
        )
    assert r.status_code == 200
    assert r.json()["found"] is True


def test_http_path_has_no_langchain_ainvoke():
    """Guard: Knowledge HTTP must not route through LangChain tool.ainvoke."""
    import ast
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "app/knowledge/api/agent_metrics.py"
    tree = ast.parse(src.read_text())
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    joined = " ".join(imports)
    assert "langchain" not in joined
    assert "reasoning.tools" not in joined
    assert "app.knowledge" in joined
    body = src.read_text()
    assert "agent_metric_ops" in body
    assert "agent_graph_ops" in body
    assert ".ainvoke" not in body
