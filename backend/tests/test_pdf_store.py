"""Retained-PDF path resolution across legacy storage roots."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.knowledge.pdf_store import (
    STORAGE_SEGMENTS,
    canonical_pdf_relpath,
    resolve_pdf_path,
    strip_to_storage_tail,
)

LEGACY_PREFIXES = (
    "/data/qingshui-pdfs",
    "/mnt/shared-storage-user/liweimin/qingshui/qingshui-pdfs",
)


def _touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF-1.4 test")
    return path


def test_storage_segments() -> None:
    assert STORAGE_SEGMENTS == ("notices", "reports", "irm")


@pytest.mark.parametrize(
    ("stored_path", "expected"),
    [
        (
            "/data/qingshui-pdfs/notices/600962.SH/2026-08/1225468566.PDF",
            "notices/600962.SH/2026-08/1225468566.PDF",
        ),
        (
            "/mnt/shared-storage-user/liweimin/qingshui/qingshui-pdfs/notices/600962.SH/2026-08/1225468566.PDF",
            "notices/600962.SH/2026-08/1225468566.PDF",
        ),
        ("/srv/pdfstore/reports/600962.SH/r1.pdf", "reports/600962.SH/r1.pdf"),
        ("/srv/pdfstore/irm/deep/nested/x.pdf", "irm/deep/nested/x.pdf"),
        ("notices/a.pdf", "notices/a.pdf"),
        (None, None),
        ("", None),
        ("/data/qingshui-pdfs/other/a.pdf", None),
        ("/data/qingshui-pdfs/notices", "notices"),
    ],
)
def test_strip_to_storage_tail(stored_path: str | None, expected: str | None) -> None:
    assert strip_to_storage_tail(stored_path) == expected


@pytest.mark.parametrize(
    ("ts_code", "ann_date", "ann_id", "expected"),
    [
        ("600962.SH", "20260812", "2200763", "notices/600962.SH/2026-08/2200763.pdf"),
        ("600962.SH", "2026-08-12", 2200763, "notices/600962.SH/2026-08/2200763.pdf"),
        ("600962.SH", None, 2200763, "notices/600962.SH/unknown/2200763.pdf"),
        ("600962.SH", "not-a-date", 2200763, "notices/600962.SH/unknown/2200763.pdf"),
        ("600962.SH", "2026081", 1, "notices/600962.SH/unknown/1.pdf"),
        ("600962.SH", "20261301", 1, "notices/600962.SH/unknown/1.pdf"),
        ("600962.SH", "2026-8-12", 1, "notices/600962.SH/unknown/1.pdf"),
        ("600962 SH", "20260812", 1, "notices/600962SH/2026-08/1.pdf"),
        ("600962/SH", "20260812", 1, "notices/600962SH/2026-08/1.pdf"),
    ],
)
def test_canonical_pdf_relpath(ts_code: str, ann_date: str | None, ann_id: str | int, expected: str) -> None:
    assert canonical_pdf_relpath(ts_code, ann_date, ann_id) == expected


@pytest.mark.parametrize("prefix", LEGACY_PREFIXES)
def test_resolves_both_legacy_prefixes(tmp_path: Path, prefix: str) -> None:
    expected = _touch(tmp_path / "notices" / "600962.SH" / "2026-08" / "1225468566.PDF")

    stored = f"{prefix}/notices/600962.SH/2026-08/1225468566.PDF"

    resolved = resolve_pdf_path(
        stored,
        ts_code="600962.SH",
        ann_date="20260812",
        ann_id=2200763,
        root=tmp_path,
    )

    assert resolved == expected.resolve()


def test_falls_back_to_canonical_ann_id_filename(tmp_path: Path) -> None:
    expected = _touch(tmp_path / "notices" / "600962.SH" / "2026-08" / "2200763.pdf")

    resolved = resolve_pdf_path(
        None,
        ts_code="600962.SH",
        ann_date="20260812",
        ann_id=2200763,
        root=tmp_path,
    )

    assert resolved == expected.resolve()


def test_stored_path_wins_over_canonical_fallback(tmp_path: Path) -> None:
    stored_file = _touch(tmp_path / "notices" / "600962.SH" / "2026-08" / "1225468566.PDF")
    _touch(tmp_path / "notices" / "600962.SH" / "2026-08" / "2200763.pdf")

    resolved = resolve_pdf_path(
        "/data/qingshui-pdfs/notices/600962.SH/2026-08/1225468566.PDF",
        ts_code="600962.SH",
        ann_date="20260812",
        ann_id=2200763,
        root=tmp_path,
    )

    assert resolved == stored_file.resolve()


def test_rejects_traversal_and_missing(tmp_path: Path) -> None:
    kwargs = dict(ts_code="600962.SH", ann_date="20260812", ann_id=2200763, root=tmp_path)
    (tmp_path / "notices").mkdir()

    assert resolve_pdf_path("/x/notices/../../etc/passwd", **kwargs) is None
    assert resolve_pdf_path("/x/notices/a/b/none.pdf", **kwargs) is None


def test_rejects_escape_through_symlink(tmp_path: Path) -> None:
    outside = _touch(tmp_path.parent / "outside-secret.pdf")
    linked_dir = tmp_path / "notices" / "600962.SH" / "2026-08"
    linked_dir.mkdir(parents=True)
    (linked_dir / "1225468566.PDF").symlink_to(outside)

    resolved = resolve_pdf_path(
        "/data/qingshui-pdfs/notices/600962.SH/2026-08/1225468566.PDF",
        ts_code="600962.SH",
        ann_date="20260812",
        ann_id=2200763,
        root=tmp_path,
    )

    assert resolved is None


def test_ignores_candidate_that_is_a_directory(tmp_path: Path) -> None:
    (tmp_path / "notices" / "600962.SH" / "2026-08" / "2200763.pdf").mkdir(parents=True)

    resolved = resolve_pdf_path(
        None,
        ts_code="600962.SH",
        ann_date="20260812",
        ann_id=2200763,
        root=tmp_path,
    )

    assert resolved is None
