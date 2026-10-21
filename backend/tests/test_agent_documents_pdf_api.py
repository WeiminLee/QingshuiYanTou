"""``GET /api/v1/knowledge/documents/{ann_id}/pdf`` — retained-PDF streaming.

The route implements byte ranges by hand (Starlette's ``FileResponse`` does not
guarantee range support across versions), so these tests pin the wire contract:
status codes, ``Content-Range``, chunked body length, and the absence of any
server path in body or headers.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pymongo.errors import ServerSelectionTimeoutError

from app.config import settings
from app.knowledge.api import agent_documents
from app.knowledge.document_service import load_pdf_path as real_load_pdf_path

HEADERS = {"X-API-Key": "test-key"}

PDF_BYTES = b"%PDF-1.4\n" + b"Q" * (2048 - len(b"%PDF-1.4\n"))
SHA256 = "a" * 64
ANN_ID = 1225468566


@pytest.fixture(autouse=True)
def _api_key(monkeypatch):
    monkeypatch.setattr(settings, "knowledge_api_key", "test-key", raising=False)
    monkeypatch.setattr(settings, "api_key", "", raising=False)


@pytest.fixture()
def root(tmp_path, monkeypatch) -> Path:
    """Point ``pdf_storage_root`` at a private directory so containment is real."""
    storage = tmp_path / "pdfroot"
    storage.mkdir()
    monkeypatch.setattr(settings, "pdf_storage_root", storage, raising=False)
    return storage


@pytest.fixture()
def pdf_file(root: Path) -> Path:
    path = root / "notices" / "300750.SZ" / "2024-04" / "1225468566.pdf"
    path.parent.mkdir(parents=True)
    path.write_bytes(PDF_BYTES)
    return path


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(agent_documents.router)
    return TestClient(app)


def _document(sha256: str | None = SHA256) -> dict:
    return {
        "ann_id": "1225468566",
        "ts_code": "300750.SZ",
        "source_name": "cninfo:300750.SZ",
        "publish_date": "2024-04-30",
        "title": "2023年年度报告",
        "title_is_filename": False,
        "chapters_parsed": 103,
        "chapters_kept": 98,
        "pdf": {"exists": sha256 is not None, "sha256": sha256, "size": len(PDF_BYTES)},
        "chapters": [],
    }


class _StubCursor:
    def __init__(self, rows):
        self._rows = rows

    async def to_list(self, length=None):
        return list(self._rows)


class _StubCollection:
    """Minimal ``kg_evidence`` stand-in: ``find`` ignores filter/projection."""

    def __init__(self, rows):
        self._rows = rows

    def find(self, *args, **kwargs):
        return _StubCursor(self._rows)


class _StubDB:
    def __init__(self, rows):
        self.kg_evidence = _StubCollection(rows)


@pytest.fixture()
def service(monkeypatch):
    """Stub both document-service loaders; no Mongo, no real storage lookup."""
    state = SimpleNamespace(
        calls=[],
        path=None,
        document=_document(),
        path_error=None,
        document_error=None,
    )

    async def fake_load_pdf_path(db, ann_id, *, root):
        state.calls.append(("pdf_path", ann_id, root))
        if state.path_error is not None:
            raise state.path_error
        return state.path, "ok" if state.path is not None else "missing"

    async def fake_load_document(db, ann_id, *, root):
        state.calls.append(("document", ann_id, root))
        if state.document_error is not None:
            raise state.document_error
        return state.document

    monkeypatch.setattr(agent_documents, "load_pdf_path", fake_load_pdf_path)
    monkeypatch.setattr(agent_documents, "load_document", fake_load_document)
    monkeypatch.setattr(agent_documents, "get_mongo_db", lambda: object())
    return state


def test_pdf_requires_api_key(client, service, pdf_file):
    r = client.get("/api/v1/knowledge/documents/1225468566/pdf")

    assert r.status_code == 401
    assert service.calls == []


def test_pdf_returns_whole_file_with_fixed_headers(client, service, pdf_file):
    service.path = pdf_file

    r = client.get("/api/v1/knowledge/documents/1225468566/pdf", headers=HEADERS)

    assert r.status_code == 200
    assert r.content == PDF_BYTES
    assert r.headers["content-type"] == "application/pdf"
    assert r.headers["content-disposition"] == "inline"
    assert r.headers["accept-ranges"] == "bytes"
    assert r.headers["cache-control"] == "private, max-age=86400"
    assert r.headers["content-length"] == str(len(PDF_BYTES))
    assert r.headers["etag"] == f'"{SHA256}"'
    assert "content-range" not in r.headers
    assert service.calls[0] == ("pdf_path", "1225468566", settings.pdf_storage_root)


def test_pdf_range_returns_206_with_content_range(client, service, pdf_file):
    service.path = pdf_file

    r = client.get(
        "/api/v1/knowledge/documents/1225468566/pdf",
        headers={**HEADERS, "Range": "bytes=0-1023"},
    )

    assert r.status_code == 206
    assert r.headers["content-range"] == f"bytes 0-1023/{len(PDF_BYTES)}"
    assert r.headers["content-length"] == "1024"
    assert r.headers["accept-ranges"] == "bytes"
    assert r.content == PDF_BYTES[:1024]


def test_pdf_open_ended_range_runs_to_eof(client, service, pdf_file):
    service.path = pdf_file

    r = client.get(
        "/api/v1/knowledge/documents/1225468566/pdf",
        headers={**HEADERS, "Range": "bytes=1024-"},
    )

    assert r.status_code == 206
    assert r.headers["content-range"] == f"bytes 1024-{len(PDF_BYTES) - 1}/{len(PDF_BYTES)}"
    assert r.content == PDF_BYTES[1024:]


def test_pdf_suffix_range_returns_tail(client, service, pdf_file):
    service.path = pdf_file

    r = client.get(
        "/api/v1/knowledge/documents/1225468566/pdf",
        headers={**HEADERS, "Range": "bytes=-16"},
    )

    assert r.status_code == 206
    assert r.headers["content-range"] == f"bytes {len(PDF_BYTES) - 16}-{len(PDF_BYTES) - 1}/{len(PDF_BYTES)}"
    assert r.content == PDF_BYTES[-16:]


@pytest.mark.parametrize(
    "range_header",
    ["bytes=999999-", "bytes=abc", "bytes=0-10, 20-30", "bytes=1024-0"],
    ids=["unsatisfiable", "malformed", "multi-range", "reversed"],
)
def test_pdf_invalid_range_returns_416(client, service, pdf_file, range_header):
    service.path = pdf_file

    r = client.get(
        "/api/v1/knowledge/documents/1225468566/pdf",
        headers={**HEADERS, "Range": range_header},
    )

    assert r.status_code == 416
    assert r.headers["content-range"] == f"bytes */{len(PDF_BYTES)}"
    assert r.json() == {"detail": {"code": "range_not_satisfiable"}}


def test_pdf_missing_file_returns_404_pdf_missing(client, service, root):
    service.path = None
    service.document = _document()

    r = client.get("/api/v1/knowledge/documents/1225468566/pdf", headers=HEADERS)

    assert r.status_code == 404
    assert r.json() == {"detail": {"code": "pdf_missing"}}
    # The document loader disambiguates "no document" from "document, no file".
    assert ("document", "1225468566", root) in service.calls


def test_pdf_without_document_returns_404_document_not_found(client, service, root):
    service.path = None
    service.document = None

    r = client.get("/api/v1/knowledge/documents/999/pdf", headers=HEADERS)

    assert r.status_code == 404
    assert r.json() == {"detail": {"code": "document_not_found"}}
    assert ("document", "999", root) in service.calls


def test_pdf_escaping_stored_path_returns_400_without_leaking_path(client, service, root, tmp_path, monkeypatch):
    """A real stored ``pdf_path`` escape must map to 400, not 404.

    The service loader runs for real against a stubbed ``kg_evidence``; only
    the document loader (sha256 / 404 disambiguation) is stubbed.
    """
    outside = tmp_path / "etc" / "passwd"
    outside.parent.mkdir()
    outside.write_bytes(PDF_BYTES)
    rows = [{"source_ref": {"ann_id": ANN_ID, "pdf_path": "/x/notices/../../etc/passwd"}}]
    monkeypatch.setattr(agent_documents, "load_pdf_path", real_load_pdf_path)
    monkeypatch.setattr(agent_documents, "get_mongo_db", lambda: _StubDB(rows))

    r = client.get("/api/v1/knowledge/documents/1225468566/pdf", headers=HEADERS)

    assert r.status_code == 400
    assert r.json() == {"detail": {"code": "pdf_path_invalid"}}
    assert str(tmp_path) not in r.text
    assert str(root) not in r.text
    assert all(str(tmp_path) not in value for value in r.headers.values())


def test_pdf_etag_omitted_when_sha256_absent(client, service, pdf_file):
    service.path = pdf_file
    service.document = _document(sha256=None)

    r = client.get("/api/v1/knowledge/documents/1225468566/pdf", headers=HEADERS)

    assert r.status_code == 200
    assert "etag" not in r.headers
    assert r.headers["content-type"] == "application/pdf"


def test_pdf_etag_not_emitted_when_file_missing(client, service, pdf_file):
    service.path = None
    service.document = _document()

    r = client.get("/api/v1/knowledge/documents/1225468566/pdf", headers=HEADERS)

    assert r.status_code == 404
    assert "etag" not in r.headers
    assert SHA256 not in r.text


def test_pdf_over_size_limit_returns_413(client, service, pdf_file, monkeypatch):
    monkeypatch.setattr(agent_documents, "MAX_PDF_BYTES", len(PDF_BYTES) - 1)
    service.path = pdf_file

    r = client.get("/api/v1/knowledge/documents/1225468566/pdf", headers=HEADERS)

    assert r.status_code == 413
    assert r.json() == {"detail": {"code": "pdf_too_large"}}


def test_pdf_streams_large_body_in_bounded_chunks(client, service, root):
    payload = b"%PDF-1.4\n" + b"x" * (200 * 1024)
    path = root / "notices" / "300750.SZ" / "2024-04" / "big.pdf"
    path.parent.mkdir(parents=True)
    path.write_bytes(payload)
    service.path = path

    r = client.get("/api/v1/knowledge/documents/1225468566/pdf", headers=HEADERS)

    assert r.status_code == 200
    assert r.content == payload
    assert r.headers["content-length"] == str(len(payload))


@pytest.mark.parametrize(
    "field",
    ["path_error", "document_error"],
    ids=["path-loader", "document-loader"],
)
def test_pdf_backend_failure_returns_503_without_details(client, service, pdf_file, field):
    setattr(
        service,
        field,
        ServerSelectionTimeoutError("connection refused mongodb://127.0.0.1:27017 from /Users/lwm/data/qingshui_pdfs"),
    )
    service.path = pdf_file

    r = client.get("/api/v1/knowledge/documents/1225468566/pdf", headers=HEADERS)

    assert r.status_code == 503
    assert r.json() == {"detail": {"code": "document_unavailable"}}
    assert "/Users" not in r.text
    assert "mongodb://" not in r.text
