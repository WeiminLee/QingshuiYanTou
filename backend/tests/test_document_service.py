"""Announcement chapter aggregation for the artifact reader.

The builder is pure: plain evidence dicts in, a reader-shaped document out.
Only ``pdf.exists``/``size`` touch the filesystem, and only under the explicit
``root`` passed by the caller.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.knowledge.document_service import (
    FILENAME_TITLE_RE,
    ann_id_variants,
    build_document_response,
    classify_title,
    ensure_document_indexes,
    load_document,
    load_pdf_path,
    parse_range,
)

TS_CODE = "600962.SH"
ANN_ID = 2200763
SHA256 = "aa29" + "0" * 60


def _source_ref(**overrides: Any) -> dict[str, Any]:
    ref: dict[str, Any] = {
        "ann_id": ANN_ID,
        "ann_date": "2026-08-12",
        "pdf_path": None,
        "pdf_sha256": SHA256,
        "chapter_index": 91,
        "chapter_heading": "",
        "total_chapters": 103,
    }
    ref.update(overrides)
    return ref


def _row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "evidence_id": "EV:068b" + "a" * 60,
        "text_excerpt": "第一章正文" * 3,
        "subject_hint": {"ts_code": TS_CODE, "title": "关于重大资产重组的公告"},
        "metadata": {"title": "关于重大资产重组的公告", "total_chapters": 103},
        "source_ref": _source_ref(),
        "publish_date": "2026-08-12",
        "source_name": f"公告:{TS_CODE}",
    }
    row.update(overrides)
    return row


def _touch(path: Path, payload: bytes = b"%PDF-1.4 test") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def test_builds_document_from_evidence_rows(tmp_path: Path) -> None:
    rows = [
        _row(
            evidence_id="EV:chapter-92",
            text_excerpt="第二章正文",
            source_ref=_source_ref(chapter_index=92, chapter_heading="第二节"),
        ),
        _row(evidence_id="EV:chapter-91", text_excerpt="第一章正文" * 5),
    ]

    doc = build_document_response(rows, root=tmp_path)

    assert doc is not None
    assert doc["chapters_kept"] == 2
    assert doc["chapters_parsed"] == 103
    assert doc["chapters"][0]["chapter_index"] == 91
    assert doc["chapters"][1]["chapter_index"] == 92
    assert doc["chapters"][0]["evidence_id"] == "EV:chapter-91"
    assert doc["chapters"][0]["chars"] == len("第一章正文" * 5)
    assert doc["chapters"][1]["heading"] == "第二节"
    assert doc["pdf"]["exists"] is False
    assert doc["pdf"]["size"] is None
    assert doc["pdf"]["sha256"] == SHA256
    assert doc["ann_id"] == "2200763"
    assert doc["ts_code"] == TS_CODE
    assert doc["source_name"] == f"公告:{TS_CODE}"
    assert doc["publish_date"] == "2026-08-12"
    assert doc["title"] == "关于重大资产重组的公告"
    assert doc["title_is_filename"] is False


def test_chapter_indexes_sort_numerically_not_lexicographically(tmp_path: Path) -> None:
    rows = [
        _row(evidence_id="EV:10", source_ref=_source_ref(chapter_index=10)),
        _row(evidence_id="EV:2", source_ref=_source_ref(chapter_index=2)),
        _row(evidence_id="EV:1", source_ref=_source_ref(chapter_index=1)),
    ]

    doc = build_document_response(rows, root=tmp_path)

    assert doc is not None
    assert [chapter["chapter_index"] for chapter in doc["chapters"]] == [1, 2, 10]


def test_chapter_without_index_sorts_last(tmp_path: Path) -> None:
    rows = [
        _row(evidence_id="EV:none", source_ref=_source_ref(chapter_index=None)),
        _row(evidence_id="EV:3", source_ref=_source_ref(chapter_index=3)),
    ]

    doc = build_document_response(rows, root=tmp_path)

    assert doc is not None
    assert [chapter["evidence_id"] for chapter in doc["chapters"]] == ["EV:3", "EV:none"]


def test_chapters_parsed_takes_max_total_chapters(tmp_path: Path) -> None:
    rows = [
        _row(source_ref=_source_ref(chapter_index=1, total_chapters=100)),
        _row(source_ref=_source_ref(chapter_index=2, total_chapters=103)),
        _row(
            source_ref=_source_ref(chapter_index=3, total_chapters=None),
            metadata={"title": "关于重大资产重组的公告", "total_chapters": 101},
        ),
    ]

    doc = build_document_response(rows, root=tmp_path)

    assert doc is not None
    assert doc["chapters_parsed"] == 103
    assert doc["chapters_kept"] == 3


def test_blank_heading_is_none(tmp_path: Path) -> None:
    rows = [_row(source_ref=_source_ref(chapter_heading="   "))]

    doc = build_document_response(rows, root=tmp_path)

    assert doc is not None
    assert doc["chapters"][0]["heading"] is None


def test_pdf_probe_reports_exists_and_size(tmp_path: Path) -> None:
    payload = b"%PDF-1.4 retained"
    _touch(tmp_path / "notices" / TS_CODE / "2026-08" / f"{ANN_ID}.pdf", payload)

    doc = build_document_response([_row()], root=tmp_path)

    assert doc is not None
    assert doc["pdf"] == {"exists": True, "sha256": SHA256, "size": len(payload)}


def test_pdf_resolves_through_legacy_stored_path(tmp_path: Path) -> None:
    payload = b"%PDF-1.4 legacy"
    _touch(tmp_path / "notices" / TS_CODE / "2026-08" / "1225468566.PDF", payload)
    rows = [_row(source_ref=_source_ref(pdf_path="/data/qingshui-pdfs/notices/600962.SH/2026-08/1225468566.PDF"))]

    doc = build_document_response(rows, root=tmp_path)

    assert doc is not None
    assert doc["pdf"]["exists"] is True
    assert doc["pdf"]["size"] == len(payload)


def test_response_never_exposes_server_paths(tmp_path: Path) -> None:
    _touch(tmp_path / "notices" / TS_CODE / "2026-08" / f"{ANN_ID}.pdf")
    rows = [_row(source_ref=_source_ref(pdf_path="/data/qingshui-pdfs/notices/600962.SH/2026-08/1225468566.PDF"))]

    doc = build_document_response(rows, root=tmp_path)

    assert doc is not None
    assert "pdf_path" not in doc["pdf"]
    serialized = json.dumps(doc, ensure_ascii=False)
    assert str(tmp_path) not in serialized
    assert "/data/qingshui" not in serialized
    assert "notices/" not in serialized


def test_filename_title_is_not_a_title() -> None:
    assert classify_title("1225468566.PDF") == (None, True)
    assert classify_title("关于重大资产重组的公告") == ("关于重大资产重组的公告", False)


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("1225468566.pdf", (None, True)),
        ("1225468566.PDF", (None, True)),
        ("2026-08-12_600962.SH_公告.pdf", (None, True)),
        ("第 91 章 风险提示", ("第 91 章 风险提示", False)),
        ("关于重大资产重组的公告", ("关于重大资产重组的公告", False)),
        (None, (None, False)),
        ("", (None, False)),
        ("   ", (None, False)),
    ],
)
def test_classify_title_table(title: str | None, expected: tuple[str | None, bool]) -> None:
    assert classify_title(title) == expected


def test_filename_title_falls_back_to_null(tmp_path: Path) -> None:
    rows = [
        _row(
            subject_hint={"ts_code": TS_CODE, "title": None},
            metadata={"title": "1225468566.PDF", "total_chapters": 103},
        )
    ]

    doc = build_document_response(rows, root=tmp_path)

    assert doc is not None
    assert doc["title"] is None
    assert doc["title_is_filename"] is True


def test_real_title_prefers_subject_hint_over_metadata(tmp_path: Path) -> None:
    rows = [
        _row(metadata={"title": "元数据标题", "total_chapters": 103}),
    ]

    doc = build_document_response(rows, root=tmp_path)

    assert doc is not None
    assert doc["title"] == "关于重大资产重组的公告"


def test_empty_rows_return_none(tmp_path: Path) -> None:
    assert build_document_response([], root=tmp_path) is None


def test_filename_title_regex_shape() -> None:
    assert FILENAME_TITLE_RE.pattern == r"^[\w.-]+\.(?:pdf|PDF)$"


def test_ann_id_variants_covers_int_and_str() -> None:
    assert ann_id_variants("2200763") == [2200763, "2200763"]
    assert ann_id_variants("EV:abc") == ["EV:abc"]


class _FakeCursor:
    def __init__(self, docs: list[dict[str, Any]]) -> None:
        self._docs = docs

    async def to_list(self, length: int | None = None) -> list[dict[str, Any]]:
        return list(self._docs)


class _FakeCollection:
    def __init__(self, docs: list[dict[str, Any]] | None = None) -> None:
        self.docs = docs or []
        self.queries: list[Any] = []
        self.projections: list[Any] = []
        self.indexes: list[tuple[Any, dict[str, Any]]] = []

    def find(self, query: Any, *args: Any, **kwargs: Any) -> _FakeCursor:
        self.queries.append(query)
        self.projections.append(args[0] if args else kwargs.get("projection"))
        return _FakeCursor(self.docs)

    async def find_one(self, query: Any, projection: Any = None) -> dict[str, Any] | None:
        # Mongo returns an arbitrary match; the stub mirrors "first row only",
        # the behavior the document loader must not depend on.
        return self.docs[0] if self.docs else None

    async def create_index(self, keys: Any, **kwargs: Any) -> str:
        self.indexes.append((keys, kwargs))
        return "source_ref_ann_id"


class _FakeDB:
    def __init__(self, docs: list[dict[str, Any]] | None = None) -> None:
        self.kg_evidence = _FakeCollection(docs)


async def test_load_document_queries_int_and_str_variants(tmp_path: Path) -> None:
    db = _FakeDB([_row()])

    doc = await load_document(db, str(ANN_ID), root=tmp_path)

    assert doc is not None
    assert doc["chapters_kept"] == 1
    assert db.kg_evidence.queries == [{"source_ref.ann_id": {"$in": [ANN_ID, str(ANN_ID)]}}]


async def test_load_document_returns_none_for_unknown_ann_id(tmp_path: Path) -> None:
    assert await load_document(_FakeDB(), "999", root=tmp_path) is None


async def test_load_pdf_path_resolves_existing_file(tmp_path: Path) -> None:
    expected = _touch(tmp_path / "notices" / TS_CODE / "2026-08" / f"{ANN_ID}.pdf")

    path, status = await load_pdf_path(_FakeDB([_row()]), str(ANN_ID), root=tmp_path)

    assert path == expected.resolve()
    assert status == "ok"


async def test_load_pdf_path_returns_none_when_missing(tmp_path: Path) -> None:
    (tmp_path / "notices").mkdir()

    assert await load_pdf_path(_FakeDB([_row()]), str(ANN_ID), root=tmp_path) == (
        None,
        "missing",
    )


async def test_load_pdf_path_returns_missing_for_absent_stored_path(tmp_path: Path) -> None:
    """A stored path that is merely absent (not an escape) is ``missing``."""
    (tmp_path / "notices").mkdir()
    rows = [_row(source_ref=_source_ref(pdf_path="/data/qingshui-pdfs/notices/600962.SH/2026-08/gone.pdf"))]

    assert await load_pdf_path(_FakeDB(rows), str(ANN_ID), root=tmp_path) == (
        None,
        "missing",
    )


async def test_load_pdf_path_returns_none_without_rows(tmp_path: Path) -> None:
    assert await load_pdf_path(_FakeDB(), str(ANN_ID), root=tmp_path) == (
        None,
        "missing",
    )


async def test_load_pdf_path_reports_invalid_for_escaping_pdf_path(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    # The escaped target exists, which is exactly why it must not be probed.
    _touch(tmp_path / "etc" / "passwd")
    rows = [_row(source_ref=_source_ref(pdf_path="/x/notices/../../etc/passwd"))]

    assert await load_pdf_path(_FakeDB(rows), str(ANN_ID), root=root) == (
        None,
        "invalid",
    )


async def test_load_pdf_path_escape_outranks_existing_canonical_file(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    _touch(root / "notices" / TS_CODE / "2026-08" / f"{ANN_ID}.pdf")
    rows = [_row(source_ref=_source_ref(pdf_path="/x/notices/../../etc/passwd"))]

    assert await load_pdf_path(_FakeDB(rows), str(ANN_ID), root=root) == (
        None,
        "invalid",
    )


async def test_load_pdf_path_picks_later_row_that_carries_pdf_path(tmp_path: Path) -> None:
    expected = _touch(tmp_path / "notices" / TS_CODE / "2026-08" / "1225468566.PDF")
    rows = [
        _row(evidence_id="EV:no-path", source_ref=_source_ref(chapter_index=91, pdf_path=None)),
        _row(
            evidence_id="EV:with-path",
            text_excerpt="第二章",
            source_ref=_source_ref(
                chapter_index=92,
                pdf_path="/data/qingshui-pdfs/notices/600962.SH/2026-08/1225468566.PDF",
            ),
        ),
    ]
    db = _FakeDB(rows)

    resolved, status = await load_pdf_path(db, str(ANN_ID), root=tmp_path)

    # The canonical fallback (2200763.pdf) does not exist; only the legacy file
    # named on the second row does, so a first-row-only lookup would return None.
    assert resolved == expected.resolve()
    assert status == "ok"
    assert db.kg_evidence.queries == [{"source_ref.ann_id": {"$in": [ANN_ID, str(ANN_ID)]}}]

    doc = build_document_response(rows, root=tmp_path)
    assert doc is not None
    assert doc["pdf"]["exists"] is True
    assert resolved is not None and resolved.stat().st_size == doc["pdf"]["size"]


async def test_ensure_document_indexes_creates_source_ref_ann_id_index() -> None:
    db = _FakeDB()

    await ensure_document_indexes(db)

    assert [keys for keys, _ in db.kg_evidence.indexes] == ["source_ref.ann_id"]


@pytest.mark.parametrize(
    ("header", "size", "expected"),
    [
        (None, 100, None),
        ("bytes=0-9", 100, (0, 9)),
        ("bytes=90-", 100, (90, 99)),
        ("bytes=-10", 100, (90, 99)),
        ("bytes=0-0", 100, (0, 0)),
        ("bytes=0-999", 100, (0, 99)),
        ("bytes=-999", 100, (0, 99)),
        (" bytes=0-9 ", 100, (0, 9)),
    ],
)
def test_parse_range(header: str | None, size: int, expected: tuple[int, int] | None) -> None:
    assert parse_range(header, size) == expected


@pytest.mark.parametrize(
    "bad",
    [
        "bytes=abc",
        "bytes=200-300",
        "bytes=5-1",
        "items=0-1",
        "bytes=",
        "bytes=-",
        "bytes=-0",
        "bytes=0-9,20-29",
        "bytes=0-9, 20-29",
        "bytes=+1-2",
        "bytes=1.5-2",
        "bytes=--1",
    ],
)
def test_parse_range_rejects_bad_input(bad: str) -> None:
    with pytest.raises(ValueError):
        parse_range(bad, 100)


def test_parse_range_rejects_any_range_on_empty_file() -> None:
    with pytest.raises(ValueError):
        parse_range("bytes=0-", 0)


def test_load_document_accepts_string_root(tmp_path: Path) -> None:
    doc = build_document_response([_row()], root=str(tmp_path))

    assert doc is not None
    assert doc["pdf"]["exists"] is False
