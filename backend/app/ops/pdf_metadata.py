"""Portable PDF storage metadata helpers used by remote workers."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any


def sha256_file(path: str | Path, chunk_size: int = 1024 * 1024) -> str:
    file_path = Path(path)
    digest = hashlib.sha256()
    with file_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_pdf_metadata(path: str | Path, *, pdf_url: str | None = None) -> dict[str, Any]:
    file_path = Path(path)
    available = file_path.is_file()
    return {
        "pdf_storage": "desktop",
        "pdf_path": str(file_path),
        "pdf_sha256": sha256_file(file_path) if available else None,
        "pdf_url": pdf_url,
        "available": available,
    }
