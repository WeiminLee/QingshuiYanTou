"""Read-only 文档聚合视图 HTTP（artifact reader）。

按 ``ann_id`` 聚合 ``kg_evidence`` 章节行，返回文档元信息与章节清单（不含正文）。
只读：不写库；响应永不含服务器路径（``pdf`` 只报 ``exists``/``sha256``/``size``）。

``/{ann_id}/pdf`` 按手动 Range 流式回放留存 PDF：Starlette 版本间 ``FileResponse``
的 Range 支持并不稳定，这里自己切块，保证任意版本行为一致；文件按 64 KiB 分块读取，
永不整文件读入内存。
"""
from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from pymongo.errors import PyMongoError

from app.config import settings
from app.core.mongodb import get_mongo_db
from app.knowledge.api._auth import require_api_key
from app.knowledge.document_service import load_document, load_pdf_path, parse_range
from app.knowledge.document_summary import get_chapter_summaries, get_document_summary

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/knowledge/documents", tags=["知识 文档"])

# Defensive ceiling: retained PDFs are ~0.6 MB today, but a corrupt or hostile
# row must not turn one request into a multi-gigabyte stream.
MAX_PDF_BYTES = 200 * 1024 * 1024
PDF_CHUNK_SIZE = 64 * 1024

# Only a real sha256 may reach the ETag header: legacy rows hold no
# ``pdf_sha256`` at all, and a stray value must never reach header encoding.
_SHA256_RE = re.compile(r"[0-9a-fA-F]{64}")


@router.get("/{ann_id}")
async def get_document(
    ann_id: str,
    x_api_key: str | None = Header(default=None),
) -> dict[str, Any]:
    require_api_key(x_api_key)
    db = get_mongo_db()
    try:
        document = await load_document(
            db,
            ann_id,
            root=settings.pdf_storage_root,
        )
    except (PyMongoError, OSError) as exc:
        # Backend unavailability must be distinguishable from a code bug.  The
        # driver message and any filesystem path stay in the server log; the
        # client gets a fixed code only.
        logger.exception("document load failed for ann_id=%r", ann_id)
        raise HTTPException(503, detail={"code": "document_unavailable"}) from exc
    if document is None:
        raise HTTPException(404, detail={"code": "document_not_found"})
    # Summary is additive: a missing row or a summary-store error must never
    # turn a readable document into an error response.
    try:
        summary = await get_document_summary(db, ann_id)
    except Exception as exc:  # noqa: BLE001 — optional summary
        logger.warning("document summary lookup failed for ann_id=%r: %s", ann_id, exc)
        summary = None
    if summary is not None:
        document = {**document, "summary": summary["summary"]}
        if summary.get("updated_at") is not None:
            document["summary_updated_at"] = summary["updated_at"]

    chapter_ids = [
        str(chapter.get("evidence_id"))
        for chapter in (document.get("chapters") or [])
        if isinstance(chapter, dict) and chapter.get("evidence_id")
    ]
    try:
        chapter_summaries = await get_chapter_summaries(db, chapter_ids)
    except Exception as exc:  # noqa: BLE001 — optional chapter summaries
        logger.warning("chapter summary lookup failed for ann_id=%r: %s", ann_id, exc)
        chapter_summaries = {}
    if chapter_summaries:
        chapters: list[Any] = []
        for chapter in document.get("chapters") or []:
            if not isinstance(chapter, dict):
                chapters.append(chapter)
                continue
            item = dict(chapter)
            chapter_summary = chapter_summaries.get(str(item.get("evidence_id")))
            if chapter_summary is not None:
                item["summary"] = chapter_summary["summary"]
                if chapter_summary.get("updated_at") is not None:
                    item["summary_updated_at"] = chapter_summary["updated_at"]
            chapters.append(item)
        document = {**document, "chapters": chapters}
    return document


def _document_sha256(document: dict[str, Any] | None) -> str | None:
    """Return the document's PDF sha256 when it is one we can put in an ETag."""
    if not document:
        return None
    pdf = document.get("pdf")
    value = pdf.get("sha256") if isinstance(pdf, dict) else None
    if isinstance(value, str) and _SHA256_RE.fullmatch(value.strip()):
        return value.strip()
    return None


def _iter_file(path: Path, start: int, length: int) -> Iterator[bytes]:
    """Yield exactly ``length`` bytes from ``start``, ``PDF_CHUNK_SIZE`` at a time.

    Sync generator: Starlette drives it through a thread pool, so the event loop
    never blocks on disk I/O and no chunk larger than 64 KiB is held in memory.
    """
    with path.open("rb") as handle:
        handle.seek(start)
        remaining = length
        while remaining > 0:
            chunk = handle.read(min(PDF_CHUNK_SIZE, remaining))
            if not chunk:
                # The file shrank after it was stat'ed.  Stop at the real EOF
                # instead of padding the body to the promised Content-Length.
                logger.warning("pdf truncated while streaming (path=%s)", path)
                return
            remaining -= len(chunk)
            yield chunk


@router.get("/{ann_id}/pdf")
async def get_document_pdf(
    ann_id: str,
    request: Request,
    x_api_key: str | None = Header(default=None),
) -> StreamingResponse:
    """Stream the retained PDF for ``ann_id`` with manual byte-range support."""
    require_api_key(x_api_key)
    db = get_mongo_db()
    try:
        # The path and its status decide *what* to stream and why it is absent;
        # the document view contributes the sha256 (the ETag) and separates
        # "no document" from "document with no retained file".
        path, path_status = await load_pdf_path(db, ann_id, root=settings.pdf_storage_root)
        document = await load_document(db, ann_id, root=settings.pdf_storage_root)
    except (PyMongoError, OSError) as exc:
        logger.exception("pdf load failed for ann_id=%r", ann_id)
        raise HTTPException(503, detail={"code": "document_unavailable"}) from exc

    if path_status == "invalid":
        raise HTTPException(400, detail={"code": "pdf_path_invalid"})
    if path is None:
        if document is None:
            raise HTTPException(404, detail={"code": "document_not_found"})
        raise HTTPException(404, detail={"code": "pdf_missing"})

    root = Path(settings.pdf_storage_root).resolve()
    try:
        resolved = path.resolve()
    except (OSError, RuntimeError) as exc:
        logger.warning("pdf path resolution failed for ann_id=%r", ann_id)
        raise HTTPException(400, detail={"code": "pdf_path_invalid"}) from exc
    # Defence in depth: ``load_pdf_path`` already resolves inside the root, but
    # a symlink swapped in afterwards must not escape it.
    if not resolved.is_relative_to(root):
        raise HTTPException(400, detail={"code": "pdf_path_invalid"})
    if not resolved.is_file():
        raise HTTPException(404, detail={"code": "pdf_missing"})
    try:
        size = resolved.stat().st_size
    except OSError as exc:
        raise HTTPException(404, detail={"code": "pdf_missing"}) from exc
    if size > MAX_PDF_BYTES:
        raise HTTPException(413, detail={"code": "pdf_too_large"})

    try:
        span = parse_range(request.headers.get("range"), size)
    except ValueError:
        raise HTTPException(
            416,
            detail={"code": "range_not_satisfiable"},
            headers={
                "Content-Range": f"bytes */{size}",
                "Accept-Ranges": "bytes",
            },
        ) from None

    if span is None:
        start, length, status_code = 0, size, 200
    else:
        start, end = span
        length, status_code = end - start + 1, 206

    headers = {
        "Content-Type": "application/pdf",
        "Content-Disposition": "inline",
        "Accept-Ranges": "bytes",
        "Cache-Control": "private, max-age=86400",
        # StreamingResponse cannot infer it, and pdf.js relies on it.
        "Content-Length": str(length),
    }
    if status_code == 206:
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    sha256 = _document_sha256(document)
    if sha256 is not None:
        headers["ETag"] = f'"{sha256}"'

    return StreamingResponse(
        _iter_file(resolved, start, length),
        status_code=status_code,
        headers=headers,
    )
