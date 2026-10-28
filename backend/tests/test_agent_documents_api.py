from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pymongo.errors import ServerSelectionTimeoutError

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
def service(monkeypatch):
    """Stub ``load_document``; ``service.doc`` is returned, ``service.error`` raised."""
    state = SimpleNamespace(calls=[], doc=_document(), error=None)

    async def fake_load_document(db, ann_id, *, root):
        state.calls.append({"db": db, "ann_id": ann_id, "root": root})
        if state.error is not None:
            raise state.error
        return state.doc

    monkeypatch.setattr(agent_documents, "load_document", fake_load_document)
    monkeypatch.setattr(agent_documents, "get_mongo_db", lambda: object())
    return state


def test_document_requires_api_key(client, service):
    r = client.get("/api/v1/knowledge/documents/1225468566")

    assert r.status_code == 401
    assert service.calls == []


def test_document_returns_view_shape(client, service):
    r = client.get("/api/v1/knowledge/documents/1225468566", headers=HEADERS)

    assert r.status_code == 200
    assert r.json() == _document()
    assert service.calls[0]["ann_id"] == "1225468566"
    assert service.calls[0]["root"] == settings.pdf_storage_root


def test_document_forwards_service_document_unchanged(client, service):
    """The handler is a pass-through: whatever the service builds is returned as-is.

    The guarantee that no server path can appear in that dict lives in
    ``tests/test_document_service.py::test_response_never_exposes_server_paths``;
    here we only pin that the handler neither reshapes nor filters it.
    """
    forwarded = _document()
    forwarded["title"] = "FORWARDED-UNCHANGED"
    forwarded["title_is_filename"] = True
    forwarded["chapters_parsed"] = 7
    forwarded["chapters_kept"] = 3
    forwarded["pdf"] = {"exists": False, "sha256": None, "size": None}
    service.doc = forwarded

    r = client.get("/api/v1/knowledge/documents/1225468566", headers=HEADERS)

    assert r.status_code == 200
    assert r.json() == forwarded


def test_document_missing_returns_coded_404(client, service):
    service.doc = None

    r = client.get("/api/v1/knowledge/documents/999", headers=HEADERS)

    assert r.status_code == 404
    assert r.json() == {"detail": {"code": "document_not_found"}}


@pytest.mark.parametrize(
    "error",
    [
        ServerSelectionTimeoutError(
            "connection refused mongodb://127.0.0.1:27017 from /Users/lwm/data/qingshui_pdfs"
        ),
        OSError(13, "Permission denied", "/Users/lwm/data/qingshui_pdfs/notices/300750.SZ"),
    ],
    ids=["mongo-unavailable", "storage-io-error"],
)
def test_document_backend_failure_returns_503_without_details(client, service, error):
    service.error = error

    r = client.get("/api/v1/knowledge/documents/1225468566", headers=HEADERS)

    assert r.status_code == 503
    assert r.json() == {"detail": {"code": "document_unavailable"}}
    # Neither the driver message nor any filesystem path may reach the client.
    assert "/Users" not in r.text
    assert "Permission denied" not in r.text
    assert "mongodb://" not in r.text


def test_document_code_bug_is_not_masked_as_unavailable(client, service):
    """Only backend failures map to 503; programming errors still surface."""
    service.error = RuntimeError("unexpected bug")

    with pytest.raises(RuntimeError, match="unexpected bug"):
        client.get("/api/v1/knowledge/documents/1225468566", headers=HEADERS)


def test_document_includes_ai_summary(client, service, monkeypatch):
    from datetime import UTC, datetime

    class _SummaryCollection:
        async def find_one(self, query):
            assert query["ann_id"]["$in"] == [1225468566, "1225468566"]
            return {
                "ann_id": 1225468566,
                "summary": "AI 摘要内容",
                "model": "qwen",
                "updated_at": datetime(2026, 10, 28, tzinfo=UTC),
            }

    class _DB(dict):
        pass

    db = _DB({"kg_document_summaries": _SummaryCollection()})
    monkeypatch.setattr(agent_documents, "get_mongo_db", lambda: db)

    r = client.get("/api/v1/knowledge/documents/1225468566", headers=HEADERS)

    assert r.status_code == 200
    payload = r.json()
    assert payload["summary"] == "AI 摘要内容"
    assert payload["summary_updated_at"].startswith("2026-10-28")


def test_document_includes_chapter_summary(client, service, monkeypatch):
    from datetime import UTC, datetime

    class _Cursor:
        def __init__(self, docs):
            self._it = iter(docs)

        def __aiter__(self):
            return self

        async def __anext__(self):
            try:
                return next(self._it)
            except StopIteration:
                raise StopAsyncIteration

    class _ChapterCollection:
        def find(self, query):
            assert query["evidence_id"]["$in"] == ["EV:abc123"]
            return _Cursor([
                {
                    "evidence_id": "EV:abc123",
                    "summary": "章节摘要内容",
                    "updated_at": datetime(2026, 10, 28, tzinfo=UTC),
                }
            ])

    class _SummaryCollection:
        async def find_one(self, query):
            return None

    class _DB(dict):
        pass

    db = _DB({
        "kg_document_summaries": _SummaryCollection(),
        "kg_chapter_summaries": _ChapterCollection(),
    })
    monkeypatch.setattr(agent_documents, "get_mongo_db", lambda: db)

    r = client.get("/api/v1/knowledge/documents/1225468566", headers=HEADERS)

    assert r.status_code == 200
    chapters = r.json()["chapters"]
    assert chapters[0]["summary"] == "章节摘要内容"
    assert chapters[0]["summary_updated_at"].startswith("2026-10-28")
