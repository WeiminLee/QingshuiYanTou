from __future__ import annotations

import pytest
from starlette.testclient import TestClient


@pytest.fixture()
def health_app(monkeypatch):
    monkeypatch.setenv("KNOWLEDGE_API_KEY", "test-key")
    from app.mcp_data.server import build_http_app, build_mcp

    mcp = build_mcp()
    return build_http_app(mcp)


def test_health_open_without_api_key(health_app):
    client = TestClient(health_app)
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "fetch_evidence" in body["tools"]
    assert "compare_metric" in body["tools"]


def test_mcp_path_requires_api_key(health_app):
    client = TestClient(health_app)
    r = client.post("/mcp", json={})
    assert r.status_code == 401
