"""tests/test_pdf_retention.py — 公告 PDF 保留策略（抽完不删 + 轮转默认关）。

设计稿 §4.2：公告 PDF 是长期保留的原文资产，evidence 构建完成后只改状态、
保留 file_path，不再 unlink；两年期轮转保留代码但默认不注册。
"""

from __future__ import annotations

from app.config import settings
from app.data_pipeline.scheduler import add_pdf_rotation_job, finalize_announcement_batch


async def test_finalize_keeps_pdf_and_marks_stored(tmp_path):
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    seen: list[tuple[str, dict]] = []

    async def execute(sql, params):
        seen.append((sql, params))

    n = await finalize_announcement_batch([{"id": 7, "file_path": str(pdf)}], execute)

    assert n == 1
    assert pdf.exists()
    assert "download_status = 'stored'" in seen[0][0]
    assert "file_path = NULL" not in seen[0][0]
    assert seen[0][1] == {"ids": [7]}


class _FakeScheduler:
    """只记录 add_job 的假 scheduler。"""

    def __init__(self) -> None:
        self.jobs: list[tuple] = []

    def add_job(self, func, trigger=None, **kwargs) -> None:
        self.jobs.append((func, trigger, kwargs))


def test_rotation_job_is_off_by_default(monkeypatch):
    monkeypatch.setattr(settings, "pdf_rotation_enabled", False, raising=False)
    fake = _FakeScheduler()

    add_pdf_rotation_job(fake)

    assert fake.jobs == []


def test_rotation_job_registers_when_enabled(monkeypatch):
    monkeypatch.setattr(settings, "pdf_rotation_enabled", True, raising=False)
    fake = _FakeScheduler()

    add_pdf_rotation_job(fake)

    assert [job[2]["id"] for job in fake.jobs] == ["pdf_rotation_weekly"]
