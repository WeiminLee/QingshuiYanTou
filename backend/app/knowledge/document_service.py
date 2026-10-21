"""Aggregate per-chapter evidence rows into one announcement document view.

The artifact reader lists a document's chapters without their text (a 103-chapter
announcement is ~1MB); chapter bodies stay behind the existing evidence endpoint.
Everything here is derived from plain evidence dicts — no Motor/DB access in
:func:`build_document_response`, so it stays unit-testable and path-free.

Response shape (design §5.1)::

    {ann_id, ts_code, source_name, publish_date, title, title_is_filename,
     chapters_parsed, chapters_kept, pdf{exists, sha256, size},
     chapters[{evidence_id, chapter_index, heading, chars}]}

No server path is ever returned: ``pdf`` only reports ``exists``/``sha256``/``size``.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.knowledge.pdf_store import resolve_pdf_path

logger = logging.getLogger(__name__)

# Titles that are really the download filename (cninfo ids like ``1225468566.PDF``)
# carry no information for the reader, so they are suppressed.
FILENAME_TITLE_RE = re.compile(r"^[\w.-]+\.(?:pdf|PDF)$")

_ANN_ID_DIGITS_RE = re.compile(r"[0-9]+")


def classify_title(title: str | None) -> tuple[str | None, bool]:
    """Return ``(display_title, title_is_filename)``.

    A title that is only a filename is not a title: the reader shows a
    "公告（标题缺失）" placeholder instead.
    """
    if not isinstance(title, str):
        return None, False
    candidate = title.strip()
    if not candidate:
        return None, False
    if FILENAME_TITLE_RE.fullmatch(candidate):
        return None, True
    return candidate, False


def ann_id_variants(ann_id: str) -> list[object]:
    """Return the ``ann_id`` shapes to query.

    Mongo stores ``source_ref.ann_id`` as the PG int, while the HTTP path
    parameter is a string and historical documents may hold strings too.
    """
    if isinstance(ann_id, str) and _ANN_ID_DIGITS_RE.fullmatch(ann_id):
        return [int(ann_id), ann_id]
    return [ann_id]


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and _ANN_ID_DIGITS_RE.fullmatch(value.strip()):
        return int(value.strip())
    return None


def _source_ref(row: dict[str, Any]) -> dict[str, Any]:
    ref = row.get("source_ref")
    return ref if isinstance(ref, dict) else {}


def _metadata(row: dict[str, Any]) -> dict[str, Any]:
    metadata = row.get("metadata")
    return metadata if isinstance(metadata, dict) else {}


def _row_ts_code(row: dict[str, Any]) -> str | None:
    subject_hint = row.get("subject_hint")
    if isinstance(subject_hint, dict) and isinstance(subject_hint.get("ts_code"), str):
        ts_code = subject_hint["ts_code"].strip()
        if ts_code:
            return ts_code
    ref_ts_code = _source_ref(row).get("ts_code")
    if isinstance(ref_ts_code, str) and ref_ts_code.strip():
        return ref_ts_code.strip()
    source_name = row.get("source_name")
    if isinstance(source_name, str):
        for separator in (":", "："):
            if separator in source_name:
                tail = source_name.rsplit(separator, 1)[1].strip()
                if tail:
                    return tail
    return None


def _first_str(rows: list[dict[str, Any]], getter: Callable[[dict[str, Any]], Any]) -> str | None:
    for row in rows:
        value = getter(row)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _chapter(row: dict[str, Any]) -> dict[str, Any]:
    ref = _source_ref(row)
    heading = ref.get("chapter_heading")
    heading_text = heading.strip() if isinstance(heading, str) else ""
    text = row.get("text_excerpt")
    return {
        "evidence_id": row.get("evidence_id"),
        "chapter_index": _as_int(ref.get("chapter_index")),
        "heading": heading_text or None,
        "chars": len(text) if isinstance(text, str) else 0,
    }


def _chapter_sort_key(chapter: dict[str, Any]) -> tuple[bool, int, str]:
    index = chapter["chapter_index"]
    # Rows without a chapter index sort last; evidence_id breaks ties so the
    # response is stable across identical re-runs.
    return (index is None, index if index is not None else 0, chapter.get("evidence_id") or "")


def _chapters_parsed(rows: list[dict[str, Any]]) -> int:
    totals: list[int] = []
    for row in rows:
        for candidate in (
            _source_ref(row).get("total_chapters"),
            _metadata(row).get("total_chapters"),
        ):
            total = _as_int(candidate)
            if total is not None:
                totals.append(total)
    return max(totals) if totals else 0


def _pdf_summary(rows: list[dict[str, Any]], *, root: Path | str) -> dict[str, Any]:
    ref = _source_ref(rows[0])
    stored_path = _first_str(rows, lambda row: _source_ref(row).get("pdf_path"))
    sha256 = _first_str(rows, lambda row: _source_ref(row).get("pdf_sha256"))
    raw_ann_id = ref.get("ann_id")
    resolved = resolve_pdf_path(
        stored_path,
        ts_code=_row_ts_code(rows[0]) or "",
        ann_date=ref.get("ann_date"),
        ann_id=raw_ann_id if raw_ann_id is not None else "",
        root=Path(root),
    )
    size: int | None = None
    if resolved is not None:
        try:
            size = resolved.stat().st_size
        except OSError:
            logger.warning("pdf stat failed for ann_id=%r", raw_ann_id)
            resolved = None
    return {"exists": resolved is not None, "sha256": sha256, "size": size}


def build_document_response(rows: list[dict[str, Any]], *, root: Path | str) -> dict[str, Any] | None:
    """Build the document view from evidence rows, or ``None`` when empty.

    ``chapters_parsed`` is the maximum ``total_chapters`` (how many chapters the
    source PDF was parsed into) and ``chapters_kept`` is how many rows survived
    extraction.  They are never combined into a "N of M" ratio.
    """
    if not rows:
        return None

    primary = rows[0]
    ref = _source_ref(primary)
    subject_hint = primary.get("subject_hint")
    hint_title = subject_hint.get("title") if isinstance(subject_hint, dict) else None
    title, title_is_filename = classify_title(hint_title)
    if title is None and not title_is_filename:
        title, title_is_filename = classify_title(_metadata(primary).get("title"))

    raw_ann_id = ref.get("ann_id")
    chapters = sorted((_chapter(row) for row in rows), key=_chapter_sort_key)

    return {
        "ann_id": str(raw_ann_id) if raw_ann_id is not None else None,
        "ts_code": _row_ts_code(primary),
        "source_name": primary.get("source_name"),
        "publish_date": primary.get("publish_date") or ref.get("ann_date"),
        "title": title,
        "title_is_filename": title_is_filename,
        "chapters_parsed": _chapters_parsed(rows),
        "chapters_kept": len(rows),
        "pdf": _pdf_summary(rows, root=root),
        "chapters": chapters,
    }


async def load_document(db: Any, ann_id: str, *, root: Path | str) -> dict[str, Any] | None:
    """Load one announcement's evidence rows and aggregate them."""
    cursor = db.kg_evidence.find({"source_ref.ann_id": {"$in": ann_id_variants(ann_id)}})
    rows = await cursor.to_list(length=None)
    return build_document_response(rows, root=root)


async def load_pdf_path(db: Any, ann_id: str, *, root: Path | str) -> Path | None:
    """Resolve the retained PDF for ``ann_id``, or ``None`` when absent."""
    document = await db.kg_evidence.find_one(
        {"source_ref.ann_id": {"$in": ann_id_variants(ann_id)}},
        {"source_ref": 1, "subject_hint": 1, "source_name": 1},
    )
    if not document:
        return None
    ref = _source_ref(document)
    raw_ann_id = ref.get("ann_id")
    return resolve_pdf_path(
        ref.get("pdf_path"),
        ts_code=_row_ts_code(document) or "",
        ann_date=ref.get("ann_date"),
        ann_id=raw_ann_id if raw_ann_id is not None else ann_id,
        root=Path(root),
    )


async def ensure_document_indexes(db: Any) -> None:
    """Create the lookup index used by both document endpoints."""
    await db.kg_evidence.create_index("source_ref.ann_id")


def parse_range(header: str | None, size: int) -> tuple[int, int] | None:
    """Parse a single ``Range: bytes=...`` header into inclusive offsets.

    ``None`` means "serve the whole file".  Malformed, multi-range, and
    unsatisfiable headers raise :class:`ValueError` (the route maps that to 416).
    """
    if header is None:
        return None
    if size < 0:
        raise ValueError(f"invalid size: {size}")

    match = re.fullmatch(r"bytes=([0-9]*)-([0-9]*)", header.strip())
    if match is None:
        raise ValueError(f"malformed range header: {header!r}")
    start_raw, end_raw = match.group(1), match.group(2)
    if not start_raw and not end_raw:
        raise ValueError(f"malformed range header: {header!r}")

    if not start_raw:
        suffix_length = int(end_raw)
        if suffix_length <= 0 or size == 0:
            raise ValueError(f"unsatisfiable range header: {header!r}")
        return max(size - suffix_length, 0), size - 1

    start = int(start_raw)
    if start >= size:
        raise ValueError(f"unsatisfiable range header: {header!r}")
    if not end_raw:
        return start, size - 1
    end = int(end_raw)
    if end < start:
        raise ValueError(f"invalid range header: {header!r}")
    return start, min(end, size - 1)
