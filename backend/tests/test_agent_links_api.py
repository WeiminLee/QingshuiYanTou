from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import settings
from app.knowledge.api.agent_links import router as agent_links_router

HEADERS = {"X-API-Key": "test-key"}


@pytest.fixture(autouse=True)
def _api_key(monkeypatch):
    monkeypatch.setattr(settings, "knowledge_api_key", "test-key", raising=False)
    monkeypatch.setattr(settings, "api_key", "", raising=False)


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(agent_links_router)
    return TestClient(app)


def test_pull_history_requires_api_key(client):
    r = client.post("/api/v1/knowledge/links/history", json={"subject": "300861.SZ"})
    assert r.status_code == 401


def test_pull_history_ok(client):
    result = {
        "items": [
            {
                "evidence_id": "EV:1",
                "published_at": "2026-01-01",
                "source_type": "announcement",
                "source_name": "年报",
                "text_excerpt": "毛利率提升",
                "matched_keywords": ["毛利率"],
            }
        ],
        "count": 1,
    }
    with patch(
        "app.knowledge.linklayer.queries.pull_history",
        new=AsyncMock(return_value=result),
    ):
        r = client.post(
            "/api/v1/knowledge/links/history",
            headers=HEADERS,
            json={"subject": "300861.SZ", "dimension": "毛利率", "limit": 10},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    assert body["items"][0]["evidence_id"] == "EV:1"


def test_lookup_players_ok(client):
    rows = [{"norm_text": "300861.SZ", "mention_count": 12, "last_seen": "2026-01-01"}]
    with patch(
        "app.knowledge.linklayer.queries.lookup_players",
        new=AsyncMock(return_value=rows),
    ):
        r = client.post(
            "/api/v1/knowledge/links/lookup_players",
            headers=HEADERS,
            json={"keyword_norm_text": "硅片", "top_k": 5},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    assert body["items"][0]["norm_text"] == "300861.SZ"


def test_lookup_products_ok(client):
    rows = [{"norm_text": "硅片", "mention_count": 8, "last_seen": None}]
    with patch(
        "app.knowledge.linklayer.queries.lookup_products",
        new=AsyncMock(return_value=rows),
    ):
        r = client.post(
            "/api/v1/knowledge/links/lookup_products",
            headers=HEADERS,
            json={"company": "300861.SZ", "top_k": 5},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    assert body["items"][0]["norm_text"] == "硅片"


def test_links_http_has_no_langchain():
    import ast
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "app/knowledge/api/agent_links.py"
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
