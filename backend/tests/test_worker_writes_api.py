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


def test_link_upsert_requires_api_key(client):
    r = client.post("/api/v1/knowledge/link/upsert", json={"evidence_id": "EV:1", "actions": []})
    assert r.status_code == 401


def test_link_upsert_persists_and_runs_ledger(client):
    calls = {}

    async def fake_persist(session, evidence_id, actions):
        calls["persisted_evidence"] = evidence_id
        calls["actions"] = len(actions)
        return len(actions)

    async def fake_pipeline(session, evidence_id):
        calls["pipeline_evidence"] = evidence_id
        return {"candidates": 2, "radar_signals": 1}

    with patch("app.knowledge.api.worker_writes.persist_link_actions", side_effect=fake_persist), \
         patch("app.knowledge.api.worker_writes.run_link_ledger_pipeline", side_effect=fake_pipeline), \
         patch("app.knowledge.api.worker_writes.async_session") as fake_session_ctx:
        class _Ctx:
            async def __aenter__(self):
                return object()

            async def __aexit__(self, *a):
                return False

        fake_session_ctx.return_value = _Ctx()
        r = client.post(
            "/api/v1/knowledge/link/upsert",
            headers=HEADERS,
            json={
                "evidence_id": "EV:1",
                "actions": [
                    {"layer": "subject", "norm_text": "300001.SZ", "source": "hint",
                     "span_start": 0, "span_end": 0}
                ],
            },
        )
    assert r.status_code == 200
    assert r.json() == {"ok": True, "links": 1, "candidates": 2, "radar_signals": 1}
    assert calls["persisted_evidence"] == "EV:1"
    assert calls["pipeline_evidence"] == "EV:1"
