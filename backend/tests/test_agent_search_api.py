from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import settings
from app.knowledge.api.agent_search import router as agent_search_router
from app.knowledge.vector_client import SearchResult

HEADERS = {"X-API-Key": "test-key"}


@pytest.fixture(autouse=True)
def _api_key(monkeypatch):
    monkeypatch.setattr(settings, "knowledge_api_key", "test-key", raising=False)
    monkeypatch.setattr(settings, "api_key", "", raising=False)


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(agent_search_router)
    return TestClient(app)


def _entity_hit():
    return SearchResult(
        id="uuid-point-1",
        score=0.91,
        payload={
            "entity_id": "C_宁德时代",
            "entity_name": "宁德时代",
            "entity_type": "Company",
            "ts_code": "300750.SZ",
        },
    )


def _chunk_hit():
    return SearchResult(
        id="uuid-point-2",
        score=0.83,
        payload={
            "evidence_id": "EV:abc123",
            "content": "公司预计2024年产能翻倍。",
            "source_type": "announcement",
            "source_name": "2024年度报告",
        },
    )


def test_semantic_requires_api_key(client):
    r = client.post("/api/v1/knowledge/search/semantic", json={"query": "宁德"})
    assert r.status_code == 401


def test_semantic_entities_shapes_graph_id(client):
    with patch(
        "app.knowledge.api.agent_search.semantic_search_entities",
        return_value=[_entity_hit()],
    ):
        r = client.post(
            "/api/v1/knowledge/search/semantic",
            headers=HEADERS,
            json={"query": "宁德 电池龙头", "scope": "entities"},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["entities"][0]["entity_id"] == "C_宁德时代"
    assert "chunks" not in body


def test_semantic_chunks_and_both(client):
    with (
        patch(
            "app.knowledge.api.agent_search.semantic_search_entities",
            return_value=[_entity_hit()],
        ),
        patch(
            "app.knowledge.api.agent_search.semantic_search_chunks",
            return_value=[_chunk_hit()],
        ),
    ):
        r = client.post(
            "/api/v1/knowledge/search/semantic",
            headers=HEADERS,
            json={"query": "产能", "scope": "both", "top_k": 3},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["chunks"][0]["evidence_id"] == "EV:abc123"
    assert body["chunks"][0]["snippet"].startswith("公司预计")


def test_semantic_invalid_scope(client):
    r = client.post(
        "/api/v1/knowledge/search/semantic",
        headers=HEADERS,
        json={"query": "x", "scope": "nope"},
    )
    assert r.status_code == 422 or r.status_code == 400
