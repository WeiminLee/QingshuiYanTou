from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import settings
from app.knowledge.api import agent_documents

HEADERS = {"X-API-Key": "test-key"}


@pytest.fixture(autouse=True)
def _api_key(monkeypatch):
    monkeypatch.setattr(settings, "knowledge_api_key", "test-key", raising=False)
    monkeypatch.setattr(settings, "api_key", "", raising=False)


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(agent_documents.router)
    return TestClient(app)


def _document():
    return {
        "ann_id": "1225468566",
        "ts_code": "300750.SZ",
        "source_name": "cninfo:300750.SZ",
        "publish_date": "2024-04-30",
        "title": "2023年年度报告",
        "title_is_filename": False,
        "chapters_parsed": 103,
        "chapters_kept": 98,
        "pdf": {"exists": True, "sha256": "a" * 64, "size": 1234567},
        "chapters": [
            {
                "evidence_id": "EV:abc123",
                "chapter_index": 1,
                "heading": "第一节 重要提示",
                "chars": 512,
            }
        ],
    }


@pytest.fixture()
def calls(monkeypatch):
    """Record ``load_document`` calls and stub the DB handle."""
    recorded: list[dict] = []

    async def fake_load_document(db, ann_id, *, root):
        recorded.append({"db": db, "ann_id": ann_id, "root": root})
        return _document() if ann_id == "1225468566" else None

    monkeypatch.setattr(agent_documents, "load_document", fake_load_document)
    monkeypatch.setattr(agent_documents, "get_mongo_db", lambda: object())
    return recorded


def test_document_requires_api_key(client, calls):
    r = client.get("/api/v1/knowledge/documents/1225468566")

    assert r.status_code == 401
    assert calls == []


def test_document_returns_view_shape(client, calls):
    r = client.get("/api/v1/knowledge/documents/1225468566", headers=HEADERS)

    assert r.status_code == 200
    assert r.json() == _document()
    assert calls[0]["ann_id"] == "1225468566"
    assert calls[0]["root"] == settings.pdf_storage_root


def test_document_never_exposes_server_path(client, calls):
    r = client.get("/api/v1/knowledge/documents/1225468566", headers=HEADERS)

    assert r.status_code == 200
    assert set(r.json()) == {
        "ann_id",
        "ts_code",
        "source_name",
        "publish_date",
        "title",
        "title_is_filename",
        "chapters_parsed",
        "chapters_kept",
        "pdf",
        "chapters",
    }
    assert set(r.json()["pdf"]) == {"exists", "sha256", "size"}


def test_document_missing_returns_coded_404(client, calls):
    r = client.get("/api/v1/knowledge/documents/999", headers=HEADERS)

    assert r.status_code == 404
    assert r.json() == {"detail": {"code": "document_not_found"}}
