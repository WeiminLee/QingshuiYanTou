"""Resolve retained PDF files across legacy storage layouts.

Historical ``source_ref.pdf_path`` values point at several roots
(``/data/qingshui-pdfs/...``, the shared-storage copy, ...), while the
canonical store is ``/data/qingshui/pdf``.  Resolution is pure: it only ever
touches the explicit candidate paths below, never scans a directory, and it
never returns a path outside the given root.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path, PurePosixPath

logger = logging.getLogger(__name__)

STORAGE_SEGMENTS: tuple[str, ...] = ("notices", "reports", "irm")

_UNSAFE_TS_CODE_CHARS = re.compile(r"[^A-Za-z0-9._-]")
# ``strptime`` alone is lenient (``2026081`` parses as 2026-08-01), so the two
# accepted shapes are pinned before parsing.
_ANN_DATE_SHAPES = (
    (re.compile(r"\d{8}"), "%Y%m%d"),
    (re.compile(r"\d{4}-\d{2}-\d{2}"), "%Y-%m-%d"),
)
_UNKNOWN_MONTH = "unknown"
_UNKNOWN_TS_CODE = "unknown"


def strip_to_storage_tail(stored_path: str | None) -> str | None:
    """Return the POSIX path starting at the first ``notices``/``reports``/``irm`` segment.

    Returns ``None`` when the path is empty or has no such segment.  The tail is
    returned verbatim (no ``..`` normalization); containment is enforced by
    :func:`resolve_pdf_path`.
    """
    if not stored_path or not stored_path.strip():
        return None
    parts = PurePosixPath(stored_path.strip()).parts
    for index, part in enumerate(parts):
        if part in STORAGE_SEGMENTS:
            return "/".join(parts[index:])
    return None


def _month_segment(ann_date: str | None) -> str:
    if isinstance(ann_date, str):
        candidate = ann_date.strip()
        for shape, fmt in _ANN_DATE_SHAPES:
            if not shape.fullmatch(candidate):
                continue
            try:
                return datetime.strptime(candidate, fmt).strftime("%Y-%m")
            except ValueError:
                return _UNKNOWN_MONTH
    return _UNKNOWN_MONTH


def canonical_pdf_relpath(ts_code: str, ann_date: str | None, ann_id: str | int) -> str:
    """Build the canonical store-relative path ``notices/{ts}/{YYYY-MM}/{ann_id}.pdf``."""
    safe_ts_code = _UNSAFE_TS_CODE_CHARS.sub("", ts_code or "") or _UNKNOWN_TS_CODE
    return f"notices/{safe_ts_code}/{_month_segment(ann_date)}/{ann_id}.pdf"


def resolve_pdf_path(
    stored_path: str | None,
    *,
    ts_code: str,
    ann_date: str | None,
    ann_id: str | int,
    root: Path,
) -> Path | None:
    """Return the first existing PDF under ``root``, or ``None``.

    Candidates are the storage tail of ``stored_path`` (legacy layouts) and the
    canonical ``{ann_id}.pdf`` path.  Each candidate must resolve to a regular
    file inside ``root`` — traversal and symlink escapes are rejected.
    """
    root_path = Path(root).resolve()

    candidates: list[str] = []
    tail = strip_to_storage_tail(stored_path)
    if tail is not None:
        candidates.append(tail)
    canonical = canonical_pdf_relpath(ts_code, ann_date, ann_id)
    if canonical not in candidates:
        candidates.append(canonical)

    for relpath in candidates:
        try:
            candidate = (root_path / relpath).resolve()
        except (OSError, RuntimeError):
            logger.warning("pdf path resolution failed for candidate %r", relpath)
            continue
        if not candidate.is_relative_to(root_path):
            continue
        if candidate.is_file():
            return candidate
    return None
