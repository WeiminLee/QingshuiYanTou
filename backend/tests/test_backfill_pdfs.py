"""tests/test_backfill_pdfs.py — 公告 PDF 回补脚本单测"""

from __future__ import annotations

import asyncio
import sys
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

# 确保能正确导入 scripts 模块
sys.path.insert(0, str(Path(__file__).parent.parent))


def _script():
    from scripts import backfill_announcement_pdfs

    return backfill_announcement_pdfs


def _candidate(**overrides):
    cand = {
        "id": 2200763,
        "ts_code": "600962.SH",
        "ann_date": "20260812",
        "title": "关于召开股东会的公告",
        "source_url": "https://static.cninfo.com.cn/finalpage/2026-08-12/2200763.PDF",
        "file_path": None,
    }
    cand.update(overrides)
    return cand


# ── 目标路径 ──────────────────────────────────────────────────────────────


def test_target_path_is_canonical(tmp_path):
    script = _script()

    assert script.backfill_target_path("600962.SH", "20260812", 2200763, tmp_path) == (
        tmp_path / "notices" / "600962.SH" / "2026-08" / "2200763.pdf"
    )


def test_target_path_accepts_date_objects_and_dashed_strings(tmp_path):
    script = _script()

    expected = tmp_path / "notices" / "600962.SH" / "2026-08" / "2200763.pdf"
    assert script.backfill_target_path("600962.SH", date(2026, 8, 12), 2200763, tmp_path) == expected
    assert script.backfill_target_path("600962.SH", "2026-08-12", 2200763, str(tmp_path)) == expected


# ── 候选 SQL ──────────────────────────────────────────────────────────────


def test_candidates_sql_only_targets_purged_rows():
    sql = _script().build_candidates_sql()

    assert "evidence_at IS NOT NULL" in sql and "ORDER BY ann_date DESC" in sql
    assert "minishare_announcements" in sql
    assert "file_path IS NULL" in sql and "file_path = ''" in sql
    assert ":since" not in sql
    assert ":ann_ids" not in sql


def test_candidates_sql_optional_filters():
    script = _script()

    assert "ann_date >= :since" in script.build_candidates_sql(since=True)
    assert "id IN :ann_ids" in script.build_candidates_sql(ann_ids=True)


# ── 幂等闸门 ──────────────────────────────────────────────────────────────


def test_plan_download_is_idempotent(tmp_path):
    script = _script()
    cand = {"id": 2200763, "ts_code": "600962.SH", "ann_date": "20260812"}

    assert script.plan_download(cand, tmp_path) == "download"
    target = script.backfill_target_path("600962.SH", "20260812", 2200763, tmp_path)
    target.parent.mkdir(parents=True)
    target.write_bytes(b"%PDF-1.4")
    assert script.plan_download(cand, tmp_path) == "skip"


def test_plan_download_never_overwrites_an_existing_directory(tmp_path):
    """目标路径已存在（哪怕不是普通文件）一律 skip，绝不覆盖。"""
    script = _script()
    cand = {"id": 2200763, "ts_code": "600962.SH", "ann_date": "20260812"}

    target = script.backfill_target_path("600962.SH", "20260812", 2200763, tmp_path)
    target.mkdir(parents=True)

    assert script.plan_download(cand, tmp_path) == "skip"


# ── 下载 ──────────────────────────────────────────────────────────────────


def test_attempt_download_uses_ann_id_filename(tmp_path):
    script = _script()
    storage = MagicMock()
    saved = tmp_path / "notices" / "600962.SH" / "2026-08" / "2200763.pdf"
    storage.download_notice = MagicMock(return_value=saved)

    result = script._attempt_download(storage, _candidate(), tmp_path, 0.0)

    assert result == saved
    storage.download_notice.assert_called_once()
    args, _kwargs = storage.download_notice.call_args
    url, ts_code, filename, pub_date = args
    assert (url, ts_code, filename) == (
        "https://static.cninfo.com.cn/finalpage/2026-08-12/2200763.PDF",
        "600962.SH",
        "2200763.pdf",
    )
    assert pub_date == "20260812"


def test_attempt_download_retries_three_times(tmp_path):
    script = _script()
    storage = MagicMock()
    storage.download_notice = MagicMock(return_value=None)

    assert script._attempt_download(storage, _candidate(), tmp_path, 0.0) is None
    assert storage.download_notice.call_count == 3


def test_attempt_download_stops_retrying_after_success(tmp_path):
    script = _script()
    saved = tmp_path / "notices" / "600962.SH" / "2026-08" / "2200763.pdf"
    storage = MagicMock()
    storage.download_notice = MagicMock(side_effect=[None, saved])

    assert script._attempt_download(storage, _candidate(), tmp_path, 0.0) == saved
    assert storage.download_notice.call_count == 2


def test_attempt_download_without_url_does_not_hit_network(tmp_path):
    script = _script()
    storage = MagicMock()

    assert script._attempt_download(storage, _candidate(source_url="  "), tmp_path, 0.0) is None
    storage.download_notice.assert_not_called()


# ── run() ─────────────────────────────────────────────────────────────────


def _patch_run(monkeypatch, tmp_path, rows):
    script = _script()
    fetch = AsyncMock(return_value=rows)
    write_back = AsyncMock()
    storage = MagicMock()
    monkeypatch.setattr(script, "_fetch_candidates", fetch)
    monkeypatch.setattr(script, "_write_back", write_back)
    monkeypatch.setattr(script, "_make_storage", lambda: storage)
    monkeypatch.setattr(script, "_resolve_root", lambda: tmp_path)
    return script, fetch, write_back, storage


def test_dry_run_makes_no_network_and_no_writes(monkeypatch, tmp_path):
    script, fetch, write_back, storage = _patch_run(monkeypatch, tmp_path, [_candidate()])

    counts = asyncio.run(script.run(dry_run=True, limit=10, since=None, sleep_s=0.0))

    assert counts == {"candidates": 1, "downloaded": 0, "skipped": 0, "failed": 0}
    fetch.assert_awaited_once()
    storage.download_notice.assert_not_called()
    write_back.assert_not_awaited()
    assert not (tmp_path / "notices").exists()


def test_run_downloads_and_writes_back(monkeypatch, tmp_path):
    script, _fetch, write_back, storage = _patch_run(monkeypatch, tmp_path, [_candidate()])
    saved = tmp_path / "notices" / "600962.SH" / "2026-08" / "2200763.pdf"
    storage.download_notice.return_value = saved

    counts = asyncio.run(script.run(dry_run=False, limit=10, since=None, sleep_s=0.0))

    assert counts == {"candidates": 1, "downloaded": 1, "skipped": 0, "failed": 0}
    write_back.assert_awaited_once_with(2200763, saved)


def test_run_skips_rows_whose_target_already_exists(monkeypatch, tmp_path):
    script, _fetch, write_back, storage = _patch_run(monkeypatch, tmp_path, [_candidate()])
    target = script.backfill_target_path("600962.SH", "20260812", 2200763, tmp_path)
    target.parent.mkdir(parents=True)
    target.write_bytes(b"%PDF-1.4")

    counts = asyncio.run(script.run(dry_run=False, limit=10, since=None, sleep_s=0.0))

    assert counts == {"candidates": 1, "downloaded": 0, "skipped": 1, "failed": 0}
    storage.download_notice.assert_not_called()
    write_back.assert_not_awaited()
    assert target.read_bytes() == b"%PDF-1.4"


def test_run_counts_failures_without_aborting(monkeypatch, tmp_path):
    script, _fetch, write_back, storage = _patch_run(monkeypatch, tmp_path, [_candidate()])
    storage.download_notice.return_value = None

    counts = asyncio.run(script.run(dry_run=False, limit=10, since=None, sleep_s=0.0))

    assert counts == {"candidates": 1, "downloaded": 0, "skipped": 0, "failed": 1}
    write_back.assert_not_awaited()


def test_run_binds_optional_filters(monkeypatch, tmp_path):
    script, fetch, _write_back, _storage = _patch_run(monkeypatch, tmp_path, [])

    asyncio.run(script.run(dry_run=True, limit=5, since="20260101", sleep_s=0.0, ann_ids=[1, 2]))
    _stmt, params = fetch.await_args.args
    assert params["since"] == date(2026, 1, 1)
    assert params["ann_ids"] == [1, 2]
    assert params["limit"] == 5

    asyncio.run(script.run(dry_run=True, limit=None, since=None, sleep_s=0.0))
    _stmt, params = fetch.await_args.args
    assert params == {"limit": None}


# ── CLI 辅助 ──────────────────────────────────────────────────────────────


def test_parse_since():
    script = _script()

    assert script._parse_since("20260812") == date(2026, 8, 12)
    assert script._parse_since("2026-08-12") == date(2026, 8, 12)


def test_parse_since_rejects_garbage():
    script = _script()

    with_since = script._parse_since
    try:
        with_since("2026/08/12")
    except ValueError as exc:
        assert "since" in str(exc).lower()
    else:  # pragma: no cover - 防御：非法 since 必须报错
        raise AssertionError("expected ValueError")


def test_parse_ann_ids():
    script = _script()

    assert script._parse_ann_ids("2200763, 2200764") == [2200763, 2200764]
    assert script._parse_ann_ids(None) == []
    assert script._parse_ann_ids(" ") == []
