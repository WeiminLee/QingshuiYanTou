from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import settings
from app.knowledge.api.worker_writes import router as worker_writes_router

HEADERS = {"X-API-Key": "test-key"}


@pytest.fixture(autouse=True)
def _api_key(monkeypatch):
    monkeypatch.setattr(settings, "knowledge_api_key", "test-key", raising=False)
    monkeypatch.setattr(settings, "api_key", "", raising=False)


@pytest.fixture()
def client():
    test_app = FastAPI()
    test_app.include_router(worker_writes_router)
    return TestClient(test_app)


def test_vector_upsert_requires_api_key(client):
    r = client.post(
        "/api/v1/knowledge/vector/upsert",
        json={"evidence_id": "EV:1", "vector": [0.1], "payload": {}},
    )
    assert r.status_code == 401


def test_vector_upsert_writes_record(client):
    captured = {}

    def fake_write(record, collection):
        captured["record"] = record
        captured["collection"] = collection
        return True

    with patch("app.knowledge.api.worker_writes.write_chunk_vector", side_effect=fake_write):
        r = client.post(
            "/api/v1/knowledge/vector/upsert",
            headers=HEADERS,
            json={
                "evidence_id": "EV:1",
                "vector": [0.1, 0.2],
                "payload": {"content": "x", "source_type": "irm"},
            },
        )
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    assert captured["record"].vector == [0.1, 0.2]
    assert captured["record"].payload["evidence_id"] == "EV:1"


def test_vector_upsert_reports_write_failure(client):
    with patch("app.knowledge.api.worker_writes.write_chunk_vector", return_value=False):
        r = client.post(
            "/api/v1/knowledge/vector/upsert",
            headers=HEADERS,
            json={"evidence_id": "EV:1", "vector": [0.1], "payload": {}},
        )
    assert r.status_code == 502
