"""Phase 03 plan 03-03 — Cninfo 公告抓取链路单元 + 端到端测试。

覆盖范围（Wave 1+2 Plans 03-01 / 03-02 / 03-03）：

* ``cninfo_client``: 常量、请求头、payload 校验、静态解析助手
* ``announcement_filter``: 标题分类（半年报/年报顺序混淆是 03-02 的回归）
* ``rate_limiter``: cninfo API + PDF 限流器单例与节流参数
* ``scheduler``: cninfo_daily 任务注册 / Cron 23:00 / 启动 fire_all_once
* ``DataFetcher.fetch_announcements``: mock cninfo + filter + storage 全链路（端到端、不发真实 HTTP）

测试遵循新项目仅 ``pytest`` 的约定（无 ``pytest-asyncio``），
async 测试一律用 ``asyncio.run()`` 包装；与 ``tests/test_kg_search.py`` 保持一致。
"""
from __future__ import annotations

import asyncio
import inspect
from datetime import date as date_type
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── Section 1: cninfo_client 模块 ────────────────────────────────


class TestCninfoClientConstants:
    """API URL / PDF base / 请求头基础常量"""

    def test_cninfo_api_url(self):
        from app.data_pipeline.cninfo_client import CNINFO_QUERY_API
        assert CNINFO_QUERY_API == (
            "http://www.cninfo.com.cn/new/hisAnnouncement/query"
        )

    def test_cninfo_pdf_base(self):
        from app.data_pipeline.cninfo_client import CNINFO_PDF_BASE
        assert CNINFO_PDF_BASE == "http://static.cninfo.com.cn/"
        assert CNINFO_PDF_BASE.endswith("/"), "PDF base 必须带尾斜杠便于直接拼接 adjunctUrl"

    def test_cninfo_headers(self):
        from app.data_pipeline.cninfo_client import CNINFO_HEADERS
        # cninfo 反爬要求模拟浏览器请求
        assert "User-Agent" in CNINFO_HEADERS
        assert "Mozilla" in CNINFO_HEADERS["User-Agent"]
        assert CNINFO_HEADERS.get("X-Requested-With") == "XMLHttpRequest"
        assert CNINFO_HEADERS.get("Host") == "www.cninfo.com.cn"
        assert "Referer" in CNINFO_HEADERS


class TestCninfoStaticHelpers:
    """``CninfoClient`` 上的静态字段解析助手"""

    def test_get_announcement_id(self):
        from app.data_pipeline.cninfo_client import CninfoClient
        ann = {"announcementId": "1220118326"}
        assert CninfoClient.get_announcement_id(ann) == "1220118326"

    def test_get_announcement_id_missing_returns_empty(self):
        from app.data_pipeline.cninfo_client import CninfoClient
        assert CninfoClient.get_announcement_id({}) == ""

    def test_get_title(self):
        from app.data_pipeline.cninfo_client import CninfoClient
        ann = {"announcementTitle": "2024年年度报告"}
        assert CninfoClient.get_title(ann) == "2024年年度报告"

    def test_get_ts_code_szmain(self):
        from app.data_pipeline.cninfo_client import CninfoClient
        # 0 开头 -> SZ
        assert CninfoClient.get_ts_code({"secCode": "000001"}) == "000001.SZ"

    def test_get_ts_code_szchinext(self):
        from app.data_pipeline.cninfo_client import CninfoClient
        # 3 开头 -> SZ（创业板）
        assert CninfoClient.get_ts_code({"secCode": "300001"}) == "300001.SZ"

    def test_get_ts_code_sh(self):
        from app.data_pipeline.cninfo_client import CninfoClient
        # 6 开头 -> SH
        assert CninfoClient.get_ts_code({"secCode": "600000"}) == "600000.SH"

    def test_get_ts_code_bj(self):
        from app.data_pipeline.cninfo_client import CninfoClient
        # 8 开头 -> BJ（北交所）
        assert CninfoClient.get_ts_code({"secCode": "830000"}) == "830000.BJ"

    def test_get_ts_code_zfill(self):
        from app.data_pipeline.cninfo_client import CninfoClient
        # 不足 6 位补零（cninfo "576" 实际是深市 000576）
        assert CninfoClient.get_ts_code({"secCode": "576"}) == "000576.SZ"

    def test_get_ts_code_empty(self):
        from app.data_pipeline.cninfo_client import CninfoClient
        assert CninfoClient.get_ts_code({"secCode": ""}) == ""
        assert CninfoClient.get_ts_code({}) == ""

    def test_get_ann_date_milliseconds(self):
        from app.data_pipeline.cninfo_client import CninfoClient
        # 2024-05-17 12:00:00 CST 对应的毫秒时间戳（local time）
        # 用本地时区 localtime；只断言长度+前缀，避开运行环境时区差异
        ann = {"announcementTime": 1715918400000}
        result = CninfoClient.get_ann_date(ann)
        assert len(result) == 8
        assert result.isdigit()
        # 不严格断言具体日期（取决于运行机器的 TZ），但格式必须对
        assert result.startswith("2024"), f"unexpected: {result}"

    def test_get_ann_date_missing(self):
        from app.data_pipeline.cninfo_client import CninfoClient
        assert CninfoClient.get_ann_date({}) == ""
        assert CninfoClient.get_ann_date({"announcementTime": 0}) == ""

    def test_get_ann_date_dirty_data(self):
        """脏 announcementTime 不应让整批解析中断（Plan 03-01 Rule 2 fix）。"""
        from app.data_pipeline.cninfo_client import CninfoClient
        assert CninfoClient.get_ann_date({"announcementTime": "not-a-number"}) == ""

    def test_get_pdf_url_normal(self):
        from app.data_pipeline.cninfo_client import CninfoClient
        ann = {"adjunctUrl": "finalpage/2024-05-17/1220118326.PDF"}
        assert CninfoClient.get_pdf_url(ann) == (
            "http://static.cninfo.com.cn/finalpage/2024-05-17/1220118326.PDF"
        )

    def test_get_pdf_url_missing(self):
        from app.data_pipeline.cninfo_client import CninfoClient
        assert CninfoClient.get_pdf_url({}) == ""
        assert CninfoClient.get_pdf_url({"adjunctUrl": ""}) == ""

    def test_get_title_strips_cninfo_highlight_tags(self):
        from app.data_pipeline.cninfo_client import CninfoClient
        ann = {"announcementTitle": "关于<em>新雷能</em>2025年年度报告"}
        assert CninfoClient.get_title(ann) == "关于新雷能2025年年度报告"


class TestCninfoBuildPayload:
    """``_build_payload`` 校验：日期格式 + ts_code 去后缀。"""

    def test_payload_format_basic(self):
        from app.data_pipeline.cninfo_client import CninfoClient
        client = CninfoClient()
        with patch.object(
            CninfoClient,
            "_get_stock_org_map_sync",
            return_value={"000001": "gssz0000001"},
        ):
            payload = client._build_payload(
                ann_date="20240517",
                ts_code="000001.SZ",
                page=1,
                page_size=30,
            )
        assert payload["pageNum"] == "1"
        assert payload["pageSize"] == "30"
        assert payload["column"] == "szse"
        assert payload["stock"] == "000001,gssz0000001"
        assert payload["seDate"] == "2024-05-17~2024-05-17"
        assert payload["isHLtitle"] == "true"

    def test_payload_falls_back_to_plain_code_without_org_id(self):
        from app.data_pipeline.cninfo_client import CninfoClient
        client = CninfoClient()
        with patch.object(CninfoClient, "_get_stock_org_map_sync", return_value={}):
            payload = client._build_payload(
                ann_date="20240517",
                ts_code="300593.SZ",
                page=1,
                page_size=30,
            )
        assert payload["stock"] == "300593"
        assert payload["column"] == "szse"

    def test_payload_rejects_invalid_date(self):
        """Plan 03-01 Rule 2 fix：``2024-05-16`` 这类带横线的输入直接 ValueError。"""
        from app.data_pipeline.cninfo_client import CninfoClient
        client = CninfoClient()
        with pytest.raises(ValueError, match="YYYYMMDD"):
            client._build_payload(
                ann_date="2024-05-17", ts_code=None, page=1, page_size=100,
            )

    def test_payload_no_date_no_stock(self):
        from app.data_pipeline.cninfo_client import CninfoClient
        client = CninfoClient()
        payload = client._build_payload(
            ann_date=None, ts_code=None, page=1, page_size=100,
        )
        assert payload["stock"] == ""
        assert payload["seDate"] == ""


class TestCninfoPagination:
    """分页不能依赖 cninfo 返回的 totalpages，后者可能少算末页。"""

    def test_get_announcements_continues_when_total_pages_is_low(self):
        from app.data_pipeline.cninfo_client import CninfoClient

        client = CninfoClient()
        pages = {
            1: {
                "total": 35,
                "list": [{"announcementId": str(i)} for i in range(30)],
                "has_more": True,
                "total_pages": 1,
            },
            2: {
                "total": 35,
                "list": [{"announcementId": str(i)} for i in range(30, 35)],
                "has_more": False,
                "total_pages": 1,
            },
        }

        async def fake_query_announcements(**kwargs):
            return pages[kwargs["page"]]

        client.query_announcements = fake_query_announcements
        result = asyncio.run(client.get_announcements(ann_date="20240517"))
        assert len(result) == 35


# ── Section 2: announcement_filter 模块 ─────────────────────────


class TestClassifyTitle:
    """Plan 03-02：标题关键词分类（注意半年报/季报必须先于年报）。"""

    def test_classify_annual_report(self):
        from app.data_pipeline.announcement_filter import (
            DOC_TYPE_SAVE,
            classify_title,
        )
        # 标题不能含 "半年" / "季度" 关键词，否则会先匹配它们
        doc_type, action = classify_title("2024年年度报告")
        assert doc_type == "annual_report"
        assert action == DOC_TYPE_SAVE

    def test_classify_half_report_not_misclassified(self):
        """关键回归：'2024年半年度报告' 不应被错分为 annual_report。"""
        from app.data_pipeline.announcement_filter import (
            DOC_TYPE_SAVE,
            classify_title,
        )
        doc_type, action = classify_title("2024年半年度报告")
        assert doc_type == "half_report", (
            "'半年度报告' 必须先于 '年度报告' 匹配，否则会被错分为 annual_report"
        )
        assert action == DOC_TYPE_SAVE

    def test_classify_half_report_express(self):
        from app.data_pipeline.announcement_filter import (
            DOC_TYPE_SAVE, classify_title,
        )
        doc_type, action = classify_title("2024年半年度业绩快报")
        assert doc_type == "half_report"
        assert action == DOC_TYPE_SAVE

    def test_classify_quarter_report_q1(self):
        from app.data_pipeline.announcement_filter import (
            DOC_TYPE_SAVE, classify_title,
        )
        doc_type, action = classify_title("2024年第一季度报告")
        assert doc_type == "quarter_report"
        assert action == DOC_TYPE_SAVE

    def test_classify_quarter_report_q3(self):
        from app.data_pipeline.announcement_filter import (
            DOC_TYPE_SAVE, classify_title,
        )
        doc_type, action = classify_title("2024年第三季度报告")
        assert doc_type == "quarter_report"
        assert action == DOC_TYPE_SAVE

    def test_classify_research_survey(self):
        from app.data_pipeline.announcement_filter import (
            DOC_TYPE_SAVE, classify_title,
        )
        doc_type, action = classify_title("投资者关系活动记录表")
        assert doc_type == "research_survey"
        assert action == DOC_TYPE_SAVE

    def test_classify_ma_activity(self):
        from app.data_pipeline.announcement_filter import (
            DOC_TYPE_SAVE, classify_title,
        )
        doc_type, action = classify_title("关于重大资产重组的进展公告")
        assert doc_type == "ma_activity"
        assert action == DOC_TYPE_SAVE

    def test_classify_investment(self):
        from app.data_pipeline.announcement_filter import (
            DOC_TYPE_SAVE, classify_title,
        )
        doc_type, action = classify_title("关于对外投资设立全资子公司的公告")
        # "对外投资" 关键词最先命中
        assert doc_type == "investment"
        assert action == DOC_TYPE_SAVE

    def test_classify_other_default_skip(self):
        from app.data_pipeline.announcement_filter import (
            DOC_TYPE_SKIP, classify_title,
        )
        doc_type, action = classify_title("简式权益变动报告书")
        assert doc_type == "other"
        assert action == DOC_TYPE_SKIP

    def test_classify_empty_title(self):
        from app.data_pipeline.announcement_filter import (
            DOC_TYPE_SKIP, classify_title,
        )
        doc_type, action = classify_title("")
        assert doc_type == "unknown"
        assert action == DOC_TYPE_SKIP

    def test_should_download_save(self):
        from app.data_pipeline.announcement_filter import should_download
        assert should_download("2024年年度报告") is True
        assert should_download("2024年半年度报告") is True
        assert should_download("投资者关系活动记录表") is True

    def test_should_download_skip(self):
        from app.data_pipeline.announcement_filter import should_download
        assert should_download("简式权益变动报告书") is False
        assert should_download("") is False

    def test_get_doc_type_helper(self):
        from app.data_pipeline.announcement_filter import get_doc_type
        assert get_doc_type("2024年年度报告") == "annual_report"
        assert get_doc_type("2024年半年度报告") == "half_report"
        assert get_doc_type("简式权益变动报告书") == "other"


# ── Section 3: rate_limiter 模块 ────────────────────────────────


class TestCninfoApiLimiter:
    """``get_cninfo_api_limiter`` 异步限流器（Plan 03-01）。"""

    def test_returns_async_limiter(self):
        from app.data_pipeline.rate_limiter import (
            AsyncRateLimiter,
            get_cninfo_api_limiter,
        )
        limiter = get_cninfo_api_limiter()
        assert isinstance(limiter, AsyncRateLimiter)
        assert limiter.max_requests == 1
        assert limiter.window_seconds == 1.0
        assert limiter.name == "cninfo-api"

    def test_singleton_semantics(self):
        from app.data_pipeline.rate_limiter import get_cninfo_api_limiter
        a = get_cninfo_api_limiter()
        b = get_cninfo_api_limiter()
        assert a is b, "limiter 应该是单例"


class TestCninfoPdfLimiter:
    """``get_cninfo_pdf_limiter`` 同步限流器（D-06 PDF 1 file/sec）。"""

    def test_returns_sync_limiter(self):
        from app.data_pipeline.rate_limiter import (
            RateLimiter,
            get_cninfo_pdf_limiter,
        )
        limiter = get_cninfo_pdf_limiter()
        assert isinstance(limiter, RateLimiter)
        assert limiter.max_requests == 1
        assert limiter.window_seconds == 1.0


# ── Section 4: scheduler 模块（Plan 03-03 重点） ──────────────────


class TestSchedulerCninfoRegistration:
    """Task 1 验收：cninfo_daily 任务在 Scheduler.start() 后注册成功。"""

    def test_cninfo_fetch_hour_constant(self):
        from app.data_pipeline.scheduler import CNINFO_FETCH_HOUR
        assert CNINFO_FETCH_HOUR == 23, "D-05: 收盘后 23:00 触发"

    def test_run_cninfo_job_is_coroutine(self):
        from app.data_pipeline.scheduler import _run_cninfo_job
        assert inspect.iscoroutinefunction(_run_cninfo_job), (
            "_run_cninfo_job 必须是 async 协程函数"
        )

    def test_cninfo_daily_registered_at_2300(self):
        """需要事件循环才能 ``AsyncIOScheduler.start()``"""
        from app.data_pipeline.scheduler import Scheduler

        async def _main():
            scheduler = Scheduler()
            scheduler.start()
            try:
                jobs = list(scheduler._scheduler.get_jobs())
                job_ids = [j.id for j in jobs]
                assert "cninfo_daily" in job_ids
                cninfo_job = next(j for j in jobs if j.id == "cninfo_daily")
                fields = {f.name: str(f) for f in cninfo_job.trigger.fields}
                assert fields.get("hour") == "23"
                assert fields.get("minute") == "0"
                assert "Shanghai" in str(cninfo_job.trigger.timezone)
            finally:
                scheduler.stop()

        asyncio.run(_main())

    def test_cninfo_in_fire_all_once_specs(self):
        """启动补漏阶段必须包含 cninfo_startup（Phase 31 F 异常观测保留）。"""
        from app.data_pipeline import scheduler as sched_mod

        # 通过 inspect.getsource 静态校验 task_specs 列表
        src = inspect.getsource(sched_mod.Scheduler._fire_all_once)
        assert "cninfo_startup" in src, "task_specs 缺少 cninfo_startup"
        assert "_run_cninfo_job()" in src, "fire_all_once 未派发 _run_cninfo_job"


class TestRunCninfoJobBehavior:
    """``_run_cninfo_job`` 调用 DataFetcher.fetch_announcements + 通知 + monitor。"""

    def test_run_cninfo_job_success_flow(self):
        """成功路径：fetch -> record_task_result(SUCCESS) -> notify_success。"""
        from app.data_pipeline import scheduler as sched_mod

        fake_result = {
            "total": 30, "success": 28, "skipped": 2,
            "downloaded": 5, "fail": 0,
        }

        # patch 三个 import targets：monitor、fetcher、dingtalk
        # 注意 _run_cninfo_job 内部是局部 import，所以 patch sys.modules 的子模块
        mock_monitor = MagicMock()
        mock_monitor.init_monitor = AsyncMock()
        mock_monitor.record_task_start = AsyncMock()
        mock_monitor.record_task_result = AsyncMock()

        class _TS:
            SUCCESS = "success"
            PARTIAL = "partial"
            FAILED = "failed"
        mock_monitor.TaskStatus = _TS

        mock_fetcher_mod = MagicMock()
        fake_fetcher = MagicMock()
        fake_fetcher.fetch_announcements = AsyncMock(return_value=fake_result)
        mock_fetcher_mod.DataFetcher = MagicMock(return_value=fake_fetcher)

        mock_dingtalk = MagicMock()
        mock_dingtalk.notify_task_start = MagicMock()
        mock_dingtalk.notify_task_success = MagicMock()
        mock_dingtalk.notify_task_failed = MagicMock()

        with patch.dict("sys.modules", {
            "app.data_pipeline.monitor": mock_monitor,
            "app.data_pipeline.fetcher": mock_fetcher_mod,
            "app.data_pipeline.dingtalk": mock_dingtalk,
        }):
            asyncio.run(sched_mod._run_cninfo_job())

        # 必须调用 fetch_announcements 一次
        fake_fetcher.fetch_announcements.assert_awaited_once_with()
        # init_monitor + record_task_start
        mock_monitor.init_monitor.assert_awaited_once()
        mock_monitor.record_task_start.assert_awaited_once_with("cninfo")
        # SUCCESS 状态（fail=0）
        kwargs = mock_monitor.record_task_result.await_args.kwargs
        args = mock_monitor.record_task_result.await_args.args
        assert args[0] == "cninfo"
        assert args[1] == _TS.SUCCESS
        assert kwargs == {
            "total": 30, "success": 28, "skipped": 2, "fail": 0,
        }
        # notify_task_start / notify_task_success 被调用
        mock_dingtalk.notify_task_start.assert_called_once_with("巨潮公告同步")
        mock_dingtalk.notify_task_success.assert_called_once()
        mock_dingtalk.notify_task_failed.assert_not_called()

    def test_run_cninfo_job_partial_flow(self):
        """fail > 0 -> PARTIAL 状态。"""
        from app.data_pipeline import scheduler as sched_mod

        fake_result = {
            "total": 10, "success": 8, "skipped": 0,
            "downloaded": 2, "fail": 2,
        }

        mock_monitor = MagicMock()
        mock_monitor.init_monitor = AsyncMock()
        mock_monitor.record_task_start = AsyncMock()
        mock_monitor.record_task_result = AsyncMock()

        class _TS:
            SUCCESS = "success"
            PARTIAL = "partial"
            FAILED = "failed"
        mock_monitor.TaskStatus = _TS

        mock_fetcher_mod = MagicMock()
        fake_fetcher = MagicMock()
        fake_fetcher.fetch_announcements = AsyncMock(return_value=fake_result)
        mock_fetcher_mod.DataFetcher = MagicMock(return_value=fake_fetcher)

        mock_dingtalk = MagicMock()
        mock_dingtalk.notify_task_start = MagicMock()
        mock_dingtalk.notify_task_success = MagicMock()
        mock_dingtalk.notify_task_failed = MagicMock()

        with patch.dict("sys.modules", {
            "app.data_pipeline.monitor": mock_monitor,
            "app.data_pipeline.fetcher": mock_fetcher_mod,
            "app.data_pipeline.dingtalk": mock_dingtalk,
        }):
            asyncio.run(sched_mod._run_cninfo_job())

        args = mock_monitor.record_task_result.await_args.args
        assert args[1] == _TS.PARTIAL, "fail>0 应该是 PARTIAL"

    def test_run_cninfo_job_failure_flow(self):
        """fetch 抛异常 -> record_task_result(FAILED) + notify_task_failed + 抛出。"""
        from app.data_pipeline import scheduler as sched_mod

        mock_monitor = MagicMock()
        mock_monitor.init_monitor = AsyncMock()
        mock_monitor.record_task_start = AsyncMock()
        mock_monitor.record_task_result = AsyncMock()

        class _TS:
            SUCCESS = "success"
            PARTIAL = "partial"
            FAILED = "failed"
        mock_monitor.TaskStatus = _TS

        mock_fetcher_mod = MagicMock()
        fake_fetcher = MagicMock()
        fake_fetcher.fetch_announcements = AsyncMock(
            side_effect=RuntimeError("boom"),
        )
        mock_fetcher_mod.DataFetcher = MagicMock(return_value=fake_fetcher)

        mock_dingtalk = MagicMock()
        mock_dingtalk.notify_task_start = MagicMock()
        mock_dingtalk.notify_task_success = MagicMock()
        mock_dingtalk.notify_task_failed = MagicMock()

        with patch.dict("sys.modules", {
            "app.data_pipeline.monitor": mock_monitor,
            "app.data_pipeline.fetcher": mock_fetcher_mod,
            "app.data_pipeline.dingtalk": mock_dingtalk,
        }):
            with pytest.raises(RuntimeError, match="boom"):
                asyncio.run(sched_mod._run_cninfo_job())

        # FAILED 状态 + error_message
        kwargs = mock_monitor.record_task_result.await_args.kwargs
        args = mock_monitor.record_task_result.await_args.args
        assert args[0] == "cninfo"
        assert args[1] == _TS.FAILED
        assert kwargs.get("error_message") == "boom"

        mock_dingtalk.notify_task_failed.assert_called_once_with(
            "巨潮公告同步", "boom",
        )
        mock_dingtalk.notify_task_success.assert_not_called()


# ── Section 5: DataFetcher.fetch_announcements 端到端 ─────────────


class TestFetchAnnouncementsE2E:
    """完整链路: Cninfo response -> filter -> PDF download -> DB insert.

    全部用 mock 避免外部 IO；覆盖 Plan 03-02 的 fetch_announcements + Plan 03-03
    scheduler 调用的核心契约（input/output shape）。
    """

    def _build_announcement(
        self,
        ann_id: str,
        sec_code: str,
        sec_name: str,
        title: str,
        ann_time_ms: int = 1715918400000,
        adjunct: str = "finalpage/2024-05-17/x.PDF",
    ) -> dict:
        return {
            "announcementId": ann_id,
            "secCode": sec_code,
            "secName": sec_name,
            "announcementTitle": title,
            "announcementTime": ann_time_ms,
            "adjunctUrl": adjunct,
        }

    def test_fetch_announcements_end_to_end(self):
        """4 公告：2 save / 1 skip(other) / 1 已存在 -> success=3, skipped=1, downloaded=2。"""
        from app.data_pipeline.fetcher import DataFetcher

        anns = [
            self._build_announcement("id-aaa", "000001", "平安银行", "2024年年度报告"),
            self._build_announcement("id-bbb", "300001", "特锐德", "简式权益变动报告书"),
            self._build_announcement("id-ccc", "600000", "浦发银行", "2024年半年度报告"),
            self._build_announcement("id-ddd", "830000", "电子城", "2024年第一季度报告"),
        ]

        # 已存在且本地 PDF 仍在: id-ddd (D-04 增量去重)
        existing = {"id-ddd": "/tmp/existing.pdf"}
        Path("/tmp/existing.pdf").write_bytes(b"%PDF-test")

        engine_mock = MagicMock()
        engine_mock.connect = lambda: _FakeConnCM(existing)
        engine_mock.begin = lambda: _FakeConnCM(existing, write=True)

        # ── DataFetcher 的依赖注入（构造后替换） ──
        fetcher = DataFetcher()

        # cninfo_client.get_announcements 返回模拟数据
        fetcher.cninfo_client = MagicMock()
        fetcher.cninfo_client.get_announcements = AsyncMock(return_value=anns)

        # storage.download_notice 模拟成功，返回 Path
        fetcher.storage = MagicMock()
        fetcher.storage.download_notice = MagicMock(
            return_value=Path("/tmp/fake.pdf"),
        )

        # audit_logger
        fetcher.audit_logger = MagicMock()
        fetcher.audit_logger.ainfo = AsyncMock()

        with patch("app.data_pipeline.fetcher.engine", engine_mock), \
             patch("app.data_pipeline.fetcher.IngestionProgressTracker", _FakeTracker):
            result = asyncio.run(
                fetcher.fetch_announcements(ann_date="20240517"),
            )

        # 4 总数：3 新增 + 1 跳过；2 下载（年报 + 半年报，季报 id-ddd 已存在不下载）
        assert result["total"] == 4
        assert result["success"] == 3
        assert result["skipped"] == 1
        assert result["downloaded"] == 2
        assert result["fail"] == 0

        # storage.download_notice 仅对 SAVE 公告 + 非已存在的调用了 2 次
        assert fetcher.storage.download_notice.call_count == 2
        for call in fetcher.storage.download_notice.call_args_list:
            kwargs = call.kwargs
            # 文件名以 cninfo_id 开头（_save_announcement 落盘命名约定）
            assert kwargs["filename"].startswith("id-"), kwargs
        Path("/tmp/existing.pdf").unlink(missing_ok=True)

    def test_fetch_announcements_repairs_missing_existing_pdf(self):
        """已有 DB 记录但 file_path 缺失/丢失时，应重新下载并回写 file_path。"""
        from app.data_pipeline.fetcher import DataFetcher

        ann = self._build_announcement(
            "id-repair",
            "300593",
            "新雷能",
            "2024年年度报告",
        )
        missing_path = "/tmp/qingshui-missing-announcement.pdf"
        Path(missing_path).unlink(missing_ok=True)

        existing = {"id-repair": missing_path}
        engine_mock = MagicMock()
        engine_mock.connect = lambda: _FakeConnCM(existing)
        engine_mock.begin = lambda: _FakeConnCM(existing, write=True)

        fetcher = DataFetcher()
        fetcher.cninfo_client = MagicMock()
        fetcher.cninfo_client.get_announcements = AsyncMock(return_value=[ann])
        fetcher.storage = MagicMock()
        fetcher.storage.download_notice = MagicMock(
            return_value=Path("/tmp/repaired.pdf"),
        )
        fetcher.audit_logger = MagicMock()
        fetcher.audit_logger.ainfo = AsyncMock()

        with patch("app.data_pipeline.fetcher.engine", engine_mock), \
             patch("app.data_pipeline.fetcher.IngestionProgressTracker", _FakeTracker):
            result = asyncio.run(
                fetcher.fetch_announcements(ann_date="20240517"),
            )

        assert result["total"] == 1
        assert result["success"] == 0
        assert result["skipped"] == 1
        assert result["downloaded"] == 1
        assert result["fail"] == 0
        assert fetcher.storage.download_notice.call_count == 1
        assert existing["id-repair"] == "/tmp/repaired.pdf"

    def test_delete_announcement_pdf_clears_database_path(self):
        """通过业务入口删除 PDF 时，同步清空 announcements.file_path。"""
        from app.data_pipeline.fetcher import DataFetcher

        pdf_path = Path("/tmp/qingshui-delete-announcement.pdf")
        pdf_path.write_bytes(b"%PDF-test")
        existing = {"id-delete": str(pdf_path)}
        engine_mock = MagicMock()
        engine_mock.connect = lambda: _FakeConnCM(existing)
        engine_mock.begin = lambda: _FakeConnCM(existing, write=True)

        fetcher = DataFetcher()
        fetcher.storage = MagicMock()
        fetcher.storage.delete_file = MagicMock(return_value=True)

        with patch("app.data_pipeline.fetcher.engine", engine_mock):
            result = asyncio.run(fetcher.delete_announcement_pdf("id-delete"))

        assert result is True
        fetcher.storage.delete_file.assert_called_once_with(pdf_path)
        assert existing["id-delete"] is None
        pdf_path.unlink(missing_ok=True)

    def test_reconcile_announcement_file_paths_clears_missing_files(self):
        """维护任务应清空本地已不存在的公告 PDF 路径。"""
        from app.data_pipeline.fetcher import DataFetcher

        live_path = Path("/tmp/qingshui-live-announcement.pdf")
        live_path.write_bytes(b"%PDF-test")
        missing_path = Path("/tmp/qingshui-missing-reconcile.pdf")
        missing_path.unlink(missing_ok=True)

        existing = {
            "id-live": str(live_path),
            "id-missing": str(missing_path),
        }
        engine_mock = MagicMock()
        engine_mock.connect = lambda: _FakeConnCM(existing)
        engine_mock.begin = lambda: _FakeConnCM(existing, write=True)

        fetcher = DataFetcher()
        with patch("app.data_pipeline.fetcher.engine", engine_mock):
            result = asyncio.run(fetcher.reconcile_announcement_file_paths())

        assert result == {"checked": 2, "cleared": 1, "fail": 0}
        assert existing["id-live"] == str(live_path)
        assert existing["id-missing"] is None
        live_path.unlink(missing_ok=True)

    def test_fetch_announcements_default_yesterday(self):
        """无 ann_date 入参时取昨天（D-04 默认窗口）。"""
        from app.data_pipeline.fetcher import DataFetcher

        fetcher = DataFetcher()
        fetcher.cninfo_client = MagicMock()
        fetcher.cninfo_client.get_announcements = AsyncMock(return_value=[])
        fetcher.audit_logger = MagicMock()
        fetcher.audit_logger.ainfo = AsyncMock()

        engine_mock = MagicMock()
        engine_mock.connect = lambda: _FakeConnCM({})
        engine_mock.begin = lambda: _FakeConnCM({}, write=True)

        with patch("app.data_pipeline.fetcher.engine", engine_mock), \
             patch("app.data_pipeline.fetcher.IngestionProgressTracker", _FakeTracker):
            result = asyncio.run(fetcher.fetch_announcements())

        assert result["total"] == 0
        # 验证 cninfo_client.get_announcements 收到的 ann_date 是 YYYYMMDD 8 位数字
        called_kwargs = fetcher.cninfo_client.get_announcements.call_args.kwargs
        ann_date = called_kwargs["ann_date"]
        assert len(ann_date) == 8 and ann_date.isdigit(), (
            f"默认 ann_date 应为 YYYYMMDD: {ann_date!r}"
        )

    def test_fetch_announcements_cninfo_exception_returns_fail(self):
        """cninfo 抓取异常 -> 返回 fail=1，不让 scheduler 整体崩溃。"""
        from app.data_pipeline.fetcher import DataFetcher

        fetcher = DataFetcher()
        fetcher.cninfo_client = MagicMock()
        fetcher.cninfo_client.get_announcements = AsyncMock(
            side_effect=RuntimeError("network error"),
        )
        fetcher.audit_logger = MagicMock()
        fetcher.audit_logger.ainfo = AsyncMock()

        with patch("app.data_pipeline.fetcher.IngestionProgressTracker", _FakeTracker):
            result = asyncio.run(fetcher.fetch_announcements(ann_date="20240517"))
        assert result == {
            "total": 0, "success": 0, "skipped": 0, "downloaded": 0, "fail": 1,
        }


# ── Helpers for engine mock ───────────────────────────────────


class _FakeResult:
    """模拟 SQLAlchemy Result：fetchall + rowcount。"""

    def __init__(self, rows: list[tuple] | None = None, rowcount: int = 1):
        self._rows = rows or []
        self.rowcount = rowcount

    def fetchall(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None

    def scalar(self):
        return self._rows[0][0] if self._rows else None


class _FakeTracker:
    """隔离 DataFetcher 单元测试，不访问真实 progress 表。"""

    def __init__(self, *args, **kwargs):
        self.events = []

    async def start_run(self, *args, **kwargs):
        return SimpleNamespace(run_id="fake-run")

    async def event(self, *args, **kwargs):
        self.events.append(("event", args, kwargs))

    async def update_run(self, *args, **kwargs):
        self.events.append(("update", args, kwargs))

    async def finish_run(self, *args, **kwargs):
        self.events.append(("finish", args, kwargs))


class _FakeConn:
    """模拟 async DB connection (支持 execute / commit)。"""

    def __init__(self, existing: dict[str, str | None], write: bool = False):
        self._existing = existing
        self._write = write

    async def execute(self, sql, params=None):
        # 检测是否是预查询（按 SQL 文本简单分流）
        sql_text = str(sql)
        if "SELECT cninfo_id" in sql_text and "ANY" in sql_text:
            ids = (params or {}).get("ids", [])
            rows = [(cid, self._existing[cid]) for cid in ids if cid in self._existing]
            return _FakeResult(rows=rows)
        if "SELECT file_path" in sql_text and "cninfo_id" in sql_text:
            cid = (params or {}).get("cninfo_id")
            if cid in self._existing:
                return _FakeResult(rows=[(self._existing[cid],)])
            return _FakeResult(rows=[])
        if "SELECT cninfo_id, file_path" in sql_text and "file_path IS NOT NULL" in sql_text:
            rows = [
                (cid, path)
                for cid, path in self._existing.items()
                if path
            ]
            return _FakeResult(rows=rows)
        if "UPDATE announcements" in sql_text and "file_path = NULL" in sql_text:
            cid = (params or {}).get("cninfo_id")
            if cid in self._existing:
                self._existing[cid] = None
                return _FakeResult(rowcount=1)
            return _FakeResult(rowcount=0)
        if "UPDATE announcements" in sql_text and "file_path = :file_path" in sql_text:
            cid = (params or {}).get("cninfo_id")
            if cid in self._existing:
                self._existing[cid] = (params or {}).get("file_path")
                return _FakeResult(rowcount=1)
            return _FakeResult(rowcount=0)
        if "INSERT INTO announcements" in sql_text:
            cid = (params or {}).get("cninfo_id")
            if cid in self._existing:
                return _FakeResult(rowcount=0)
            self._existing[cid] = (params or {}).get("file_path")
            return _FakeResult(rowcount=1)
        # INSERT 语句：rowcount = 1（新增成功）
        return _FakeResult(rowcount=1)


class _FakeConnCM:
    """实现 ``async with engine.connect()/begin()`` 上下文管理。"""

    def __init__(self, existing: dict[str, str | None], write: bool = False):
        self._existing = existing
        self._write = write
        self._conn: _FakeConn | None = None

    async def __aenter__(self) -> _FakeConn:
        self._conn = _FakeConn(self._existing, self._write)
        return self._conn

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None
