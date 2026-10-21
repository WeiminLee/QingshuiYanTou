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


def test_candidates_sql_targets_every_ingested_row():
    """不按 file_path 过滤：陈旧非空路径的行也必须成为候选，否则永不复访。"""
    sql = _script().build_candidates_sql()

    assert "evidence_at IS NOT NULL" in sql and "ORDER BY ann_date DESC" in sql
    assert "minishare_announcements" in sql
    assert "file_path IS NULL" not in sql and "file_path = ''" not in sql
    # 候选行必须带上 file_path：plan_download 靠它判断原文是否已在盘上。
    assert "SELECT id, ts_code, ann_date, title, source_url, file_path" in sql
    assert ":since" not in sql
    assert ":ann_ids" not in sql


def test_candidates_sql_optional_filters():
    script = _script()

    assert "ann_date >= :since" in script.build_candidates_sql(since=True)
    assert "id IN :ann_ids" in script.build_candidates_sql(ann_ids=True)


def test_write_back_sql_only_fills_empty_rows():
    """回写自带「空行才写」守卫，避免覆盖并发采集写入的真实路径。"""
    sql = _script()._SQL_WRITE_BACK

    assert "file_path IS NULL OR file_path = ''" in sql
    assert "WHERE id = :ann_id" in sql
    assert "download_status = 'stored'" in sql


# ── 幂等闸门 ──────────────────────────────────────────────────────────────


def test_plan_download_is_idempotent(tmp_path):
    script = _script()
    cand = {"id": 2200763, "ts_code": "600962.SH", "ann_date": "20260812"}

    assert script.plan_download(cand, tmp_path) == "download"
    target = script.backfill_target_path("600962.SH", "20260812", 2200763, tmp_path)
    target.parent.mkdir(parents=True)
    target.write_bytes(b"%PDF-1.4")
    assert script.plan_download(cand, tmp_path) == "skip"


def test_plan_download_honours_the_stored_file_path(tmp_path):
    """采集侧具名文件在盘上就跳过；文件不在才回到 canonical 目标判断。"""
    script = _script()
    stored = _write_pdf(
        tmp_path / "notices" / "600962.SH" / "2026-08" / "20260812_600962.SH_关于召开股东会的公告.pdf"
    )
    cand = {
        "id": 2200763,
        "ts_code": "600962.SH",
        "ann_date": "20260812",
        "file_path": str(stored),
    }

    assert script.plan_download(cand, tmp_path) == "skip"

    stored.unlink()
    assert script.plan_download(cand, tmp_path) == "download"


def test_plan_download_never_overwrites_an_existing_directory(tmp_path):
    """目标路径已存在（哪怕不是普通文件）一律 skip，绝不覆盖。"""
    script = _script()
    cand = {"id": 2200763, "ts_code": "600962.SH", "ann_date": "20260812"}

    target = script.backfill_target_path("600962.SH", "20260812", 2200763, tmp_path)
    target.mkdir(parents=True)

    assert script.plan_download(cand, tmp_path) == "skip"


# ── 下载 ──────────────────────────────────────────────────────────────────


def _target(tmp_path, script, ts_code="600962.SH", ann_date="20260812", ann_id=2200763):
    return script.backfill_target_path(ts_code, ann_date, ann_id, tmp_path)


def _storage_writing_to(storage, target):
    """让假 storage 的存储层落点与 canonical 目标一致。"""
    storage._get_notice_path = MagicMock(return_value=target)
    return storage


def _write_pdf(path, content=b"%PDF-1.4\n"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _fake_downloader(target, content=b"%PDF-1.4\n"):
    """模拟真实下载：调用当下才落盘，然后返回路径。"""
    return MagicMock(side_effect=lambda *_args, **_kwargs: _write_pdf(target, content))


def test_attempt_download_uses_ann_id_filename(tmp_path):
    script = _script()
    target = _target(tmp_path, script)
    storage = _storage_writing_to(MagicMock(), target)
    storage.download_notice = _fake_downloader(target)

    result = script._attempt_download(storage, _candidate(), tmp_path, 0.0)

    assert result == target
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
    storage = _storage_writing_to(MagicMock(), _target(tmp_path, script))
    storage.download_notice = MagicMock(return_value=None)

    assert script._attempt_download(storage, _candidate(), tmp_path, 0.0) is None
    assert storage.download_notice.call_count == 3


def test_attempt_download_stops_retrying_after_success(tmp_path):
    script = _script()
    target = _write_pdf(_target(tmp_path, script))
    storage = _storage_writing_to(MagicMock(), target)
    storage.download_notice = MagicMock(side_effect=[None, target])

    assert script._attempt_download(storage, _candidate(), tmp_path, 0.0) == target
    assert storage.download_notice.call_count == 2


def test_attempt_download_without_url_does_not_hit_network(tmp_path):
    script = _script()
    storage = MagicMock()

    assert script._attempt_download(storage, _candidate(source_url="  "), tmp_path, 0.0) is None
    storage.download_notice.assert_not_called()


def test_attempt_download_refuses_diverging_storage_path(tmp_path):
    """存储层会落到别处时拒绝下载：否则行被计成功、阅读器仍看不到，重跑还会截断文件。"""
    script = _script()
    elsewhere = tmp_path / "notices" / "_invalid" / "2026-08" / "2200763.pdf"
    storage = _storage_writing_to(MagicMock(), elsewhere)

    result = script._attempt_download(storage, _candidate(ts_code="600962.sh"), tmp_path, 0.0)

    assert result is None
    storage.download_notice.assert_not_called()
    assert not elsewhere.exists()


def test_real_file_storage_lands_on_the_canonical_target(tmp_path):
    """真实 ``FileStorage`` 的落点必须与 ``backfill_target_path`` 一致，否则闸门失效。"""
    from app.data_pipeline.file_storage import FileStorage

    script = _script()
    storage = FileStorage(notices_dir=tmp_path / "notices")

    actual = script._storage_target(storage, _candidate(), "20260812", "2200763.pdf")

    assert actual == _target(tmp_path, script).resolve()


def test_real_file_storage_diverges_for_invalid_ts_code(tmp_path):
    """非法 ts_code 会被存储层降级到 ``_invalid/``，与 canonical 目标分叉。"""
    from app.data_pipeline.file_storage import FileStorage

    script = _script()
    storage = FileStorage(notices_dir=tmp_path / "notices")
    candidate = _candidate(ts_code="600962.sh")

    actual = script._storage_target(storage, candidate, "20260812", "2200763.pdf")

    assert actual != script.backfill_target_path("600962.sh", "20260812", 2200763, tmp_path).resolve()


def test_attempt_download_rejects_invalid_downloaded_file(tmp_path):
    """产物为空文件/非 PDF 一律 failed，且绝不删除。"""
    script = _script()
    target = _write_pdf(_target(tmp_path, script), content=b"")
    storage = _storage_writing_to(MagicMock(), target)
    storage.download_notice = MagicMock(return_value=target)

    assert script._attempt_download(storage, _candidate(), tmp_path, 0.0) is None
    assert storage.download_notice.call_count == 3
    assert target.exists()


def test_is_valid_pdf(tmp_path):
    script = _script()

    assert script._is_valid_pdf(_write_pdf(tmp_path / "ok.pdf")) is True
    assert script._is_valid_pdf(_write_pdf(tmp_path / "empty.pdf", b"")) is False
    assert script._is_valid_pdf(_write_pdf(tmp_path / "html.pdf", b"<html>")) is False
    assert script._is_valid_pdf(tmp_path / "missing.pdf") is False


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
    saved = _target(tmp_path, script)
    _storage_writing_to(storage, saved)
    storage.download_notice = _fake_downloader(saved)

    counts = asyncio.run(script.run(dry_run=False, limit=10, since=None, sleep_s=0.0))

    assert counts == {"candidates": 1, "downloaded": 1, "skipped": 0, "failed": 0}
    write_back.assert_awaited_once_with(2200763, saved)


def test_run_downloads_rows_whose_file_path_is_stale(monkeypatch, tmp_path):
    """file_path 非空但指向旧目录的行同样是候选：canonical 目标缺失就走下载。"""
    stale = "/data/qingshui-pdfs/notices/600962.SH/2026-08/gone.pdf"
    script, _fetch, write_back, storage = _patch_run(
        monkeypatch, tmp_path, [_candidate(file_path=stale)],
    )
    saved = _target(tmp_path, script)
    _storage_writing_to(storage, saved)
    storage.download_notice = _fake_downloader(saved)

    counts = asyncio.run(script.run(dry_run=False, limit=10, since=None, sleep_s=0.0))

    assert counts == {"candidates": 1, "downloaded": 1, "skipped": 0, "failed": 0}
    write_back.assert_awaited_once_with(2200763, saved)


def test_run_skips_rows_whose_stored_file_path_resolves(monkeypatch, tmp_path):
    """正常采集的具名文件在盘上即跳过：绝不重下第二份 canonical 副本。"""
    stored = _write_pdf(
        tmp_path / "notices" / "600962.SH" / "2026-08" / "20260812_600962.SH_关于召开股东会的公告.pdf"
    )
    script, _fetch, write_back, storage = _patch_run(
        monkeypatch, tmp_path, [_candidate(file_path=str(stored))],
    )

    counts = asyncio.run(script.run(dry_run=False, limit=10, since=None, sleep_s=0.0))

    assert counts == {"candidates": 1, "downloaded": 0, "skipped": 1, "failed": 0}
    storage.download_notice.assert_not_called()
    write_back.assert_not_awaited()


def test_run_skip_repairs_missing_file_path(monkeypatch, tmp_path):
    """文件在、台账空：skip 分支要顺带回填 file_path，否则该行永久跳过且无信号。"""
    script, _fetch, write_back, storage = _patch_run(monkeypatch, tmp_path, [_candidate()])
    target = _write_pdf(_target(tmp_path, script))

    counts = asyncio.run(script.run(dry_run=False, limit=10, since=None, sleep_s=0.0))

    assert counts == {"candidates": 1, "downloaded": 0, "skipped": 1, "failed": 0}
    storage.download_notice.assert_not_called()
    write_back.assert_awaited_once_with(2200763, target)
    assert target.read_bytes() == b"%PDF-1.4\n"


def test_run_skip_leaves_healthy_rows_alone(monkeypatch, tmp_path):
    """台账已有 file_path 的 skip 行不再动库。"""
    row = _candidate(file_path="/data/qingshui/pdf/notices/600962.SH/2026-08/2200763.pdf")
    script, _fetch, write_back, storage = _patch_run(monkeypatch, tmp_path, [row])
    _write_pdf(_target(tmp_path, script))

    counts = asyncio.run(script.run(dry_run=False, limit=10, since=None, sleep_s=0.0))

    assert counts == {"candidates": 1, "downloaded": 0, "skipped": 1, "failed": 0}
    storage.download_notice.assert_not_called()
    write_back.assert_not_awaited()


def test_run_skip_never_adopts_a_broken_file(monkeypatch, tmp_path):
    """已存在的坏文件绝不写进台账（也不删除）。"""
    script, _fetch, write_back, _storage = _patch_run(monkeypatch, tmp_path, [_candidate()])
    target = _write_pdf(_target(tmp_path, script), content=b"")

    counts = asyncio.run(script.run(dry_run=False, limit=10, since=None, sleep_s=0.0))

    assert counts == {"candidates": 1, "downloaded": 0, "skipped": 0, "failed": 1}
    write_back.assert_not_awaited()
    assert target.exists()


def test_run_counts_failures_without_aborting(monkeypatch, tmp_path):
    script, _fetch, write_back, storage = _patch_run(monkeypatch, tmp_path, [_candidate()])
    _storage_writing_to(storage, _target(tmp_path, script))
    storage.download_notice.return_value = None

    counts = asyncio.run(script.run(dry_run=False, limit=10, since=None, sleep_s=0.0))

    assert counts == {"candidates": 1, "downloaded": 0, "skipped": 0, "failed": 1}
    write_back.assert_not_awaited()


def test_dry_run_skip_does_not_repair(monkeypatch, tmp_path):
    script, _fetch, write_back, storage = _patch_run(monkeypatch, tmp_path, [_candidate()])
    _write_pdf(_target(tmp_path, script))

    counts = asyncio.run(script.run(dry_run=True, limit=10, since=None, sleep_s=0.0))

    assert counts == {"candidates": 1, "downloaded": 0, "skipped": 1, "failed": 0}
    storage.download_notice.assert_not_called()
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
