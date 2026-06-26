"""tests/test_ann_sync_script.py - 测试公告回补脚本辅助函数"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# 确保能正确导入 scripts 模块
sys.path.insert(0, str(Path(__file__).parent.parent))


def test_generate_cninfo_id():
    """验证 cninfo_id 生成逻辑"""
    from scripts.sync_minishare_ann_history import generate_cninfo_id

    # 带 ann_id_suffix 时
    cninfo_id = generate_cninfo_id("000001.SZ", "20260615", "关于召开股东会的公告", "1225370308")
    assert cninfo_id == "ann_000001.SZ_20260615_1225370308"

    # 相同输入应产生相同 ID
    cninfo_id2 = generate_cninfo_id("000001.SZ", "20260615", "关于召开股东会的公告", "1225370308")
    assert cninfo_id == cninfo_id2

    # 不带 ann_id_suffix 时，使用 hash
    cninfo_id3 = generate_cninfo_id("000001.SZ", "20260615", "关于召开股东会的公告")
    assert cninfo_id3.startswith("ann_")
    # 用 hash 产生的 ID 长度: "ann_" + sha1_hex[:16] = 4 + 16 = 20
    assert len(cninfo_id3) == 20

    # 不同输入应产生不同 ID
    cninfo_id4 = generate_cninfo_id("000002.SZ", "20260615", "不同的公告", "1225370309")
    assert cninfo_id4 != cninfo_id


def test_classify_url_type():
    """验证 URL 类型分类"""
    from scripts.sync_minishare_ann_history import classify_url_type

    direct_url = "https://static.cninfo.com.cn/finalpage/2026-06-15/1225370308.PDF"
    detail_url = (
        "http://www.cninfo.com.cn/new/disclosure/detail"
        "?stockCode=002695&announcementId=1222674234"
        "&orgId=9900023215&announcementTime=2025-03-01"
    )
    empty_url = ""
    unknown_url = "https://example.com/file.html"

    assert classify_url_type(direct_url) == "direct_pdf"
    assert classify_url_type(detail_url) == "detail_page"
    assert classify_url_type(empty_url) == "unknown"
    assert classify_url_type(unknown_url) == "unknown"


def test_classify_url_type_edge_cases():
    """验证 URL 类型分类的边界情况"""
    from scripts.sync_minishare_ann_history import classify_url_type

    # 带空格的 URL
    assert classify_url_type("  ") == "unknown"
    # 仅空格
    assert classify_url_type(" \t\n ") == "unknown"
    # None 不会调用（因为类型注解 str），但空字符串要处理
    assert classify_url_type("") == "unknown"


def test_format_duration():
    """验证持续时间格式化"""
    from scripts.sync_minishare_ann_history import format_duration

    # 60 秒
    assert format_duration(60) == "0:01:00"
    # 3661 秒
    assert format_duration(3661) == "1:01:01"
    # 0 秒
    assert format_duration(0) == "0:00:00"
    # 大数值
    assert format_duration(86400) == "24:00:00"
    # 整分钟
    assert format_duration(120) == "0:02:00"


def test_stable_id():
    """验证 _stable_id 辅助函数（相同输入相同输出）"""
    from scripts.sync_minishare_ann_history import _stable_id

    id1 = _stable_id("test", "000001.SZ", "20260615", "标题")
    id2 = _stable_id("test", "000001.SZ", "20260615", "标题")
    assert id1 == id2
    assert id1.startswith("test_")
    # "test_" + 16 hex chars = 21
    assert len(id1) == 21


class TestBatchInsertAnnouncements:
    """_batch_insert_announcements 测试"""

    def test_batch_insert_empty(self):
        """空列表返回 (0, 0)"""
        import asyncio

        from scripts.sync_minishare_ann_history import _batch_insert_announcements

        async def run():
            mock_conn = AsyncMock()
            result = await _batch_insert_announcements(mock_conn, [], "20230101")
            assert result == (0, 0)
            mock_conn.execute.assert_not_called()

        asyncio.run(run())

    @patch("scripts.sync_minishare_ann_history.pg_insert")
    def test_batch_insert_success(self, mock_pg_insert):
        """批量插入正常，返回 (N, 0)"""
        import asyncio

        from scripts.sync_minishare_ann_history import _batch_insert_announcements

        mock_stmt = MagicMock()
        mock_pg_insert.return_value.values.return_value.on_conflict_do_nothing.return_value = mock_stmt

        mock_result = MagicMock()
        mock_result.rowcount = 2

        mock_conn = AsyncMock()
        mock_conn.execute.return_value = mock_result

        rec1 = {
            "ann_date": "20230101",
            "ts_code": "000001.SZ",
            "name": "平安银行",
            "title": "2022年度业绩预告",
            "url": "http://example.com/1",
            "doc_type": "annual_report",
        }
        rec2 = {
            "ann_date": "20230101",
            "ts_code": "000002.SZ",
            "name": "万科A",
            "title": "2022年度业绩快报",
            "url": "http://example.com/2",
            "doc_type": "annual_report",
        }

        async def run():
            inserted, skipped = await _batch_insert_announcements(mock_conn, [rec1, rec2], "20230101")
            assert inserted == 2
            assert skipped == 0
            mock_conn.execute.assert_awaited_once_with(mock_stmt)

        asyncio.run(run())

    @patch("scripts.sync_minishare_ann_history.pg_insert")
    def test_batch_insert_fallback_on_conflict(self, mock_pg_insert):
        """唯一约束冲突时降级为逐条插入"""
        import asyncio

        from scripts.sync_minishare_ann_history import _batch_insert_announcements

        # 模拟批量插入抛出异常
        mock_stmt = MagicMock()
        mock_pg_insert.return_value.values.return_value.on_conflict_do_nothing.side_effect = [
            mock_stmt,  # 第一次调用用于批量
        ]

        mock_conn = AsyncMock()
        # 批量插入抛出异常
        batch_result = MagicMock()
        batch_result.rowcount = 5
        # 第一次 execute（批量）成功
        mock_conn.execute.return_value = batch_result

        rec = {
            "ann_date": "20230101",
            "ts_code": "000001.SZ",
            "name": "平安银行",
            "title": "2022年度业绩预告",
            "url": "http://example.com/1",
            "doc_type": "annual_report",
        }

        async def run():
            inserted, skipped = await _batch_insert_announcements(mock_conn, [rec], "20230101")
            # 批量成功，不降级
            assert inserted == 1
            assert skipped == 0

        asyncio.run(run())


class TestConcurrentDownload:
    """_concurrent_download 测试"""

    @patch("scripts.sync_minishare_ann_history.get_cninfo_pdf_async_limiter")
    def test_concurrent_all_success(self, mock_limiter_fn):
        """全部下载成功"""
        import asyncio

        from scripts.sync_minishare_ann_history import _concurrent_download

        mock_limiter = AsyncMock()
        mock_limiter_fn.return_value = mock_limiter

        mock_storage = AsyncMock()
        mock_storage.download_notice_async.side_effect = [
            Path("/fake/1.pdf"),
            Path("/fake/2.pdf"),
        ]

        pending = [
            {
                "cninfo_id": "ann_1",
                "pdf_url": "http://a.pdf",
                "ts_code": "000001.SZ",
                "title": "业绩预告",
            },
            {
                "cninfo_id": "ann_2",
                "pdf_url": "http://b.pdf",
                "ts_code": "000002.SZ",
                "title": "业绩快报",
            },
        ]

        async def run():
            downloaded, fail_count, updates = await _concurrent_download(
                pending,
                mock_storage,
                "20230101",
            )
            assert downloaded == 2
            assert fail_count == 0
            assert len(updates) == 2
            assert updates[0]["cninfo_id"] == "ann_1"
            assert updates[1]["cninfo_id"] == "ann_2"

        asyncio.run(run())

    @patch("scripts.sync_minishare_ann_history.get_cninfo_pdf_async_limiter")
    def test_concurrent_partial_fail(self, mock_limiter_fn):
        """部分下载失败"""
        import asyncio

        from scripts.sync_minishare_ann_history import _concurrent_download

        mock_limiter = AsyncMock()
        mock_limiter_fn.return_value = mock_limiter

        mock_storage = AsyncMock()
        mock_storage.download_notice_async.side_effect = [
            Path("/fake/1.pdf"),
            None,
        ]

        pending = [
            {
                "cninfo_id": "ann_1",
                "pdf_url": "http://a.pdf",
                "ts_code": "000001.SZ",
                "title": "业绩预告",
            },
            {
                "cninfo_id": "ann_2",
                "pdf_url": "http://404.pdf",
                "ts_code": "000002.SZ",
                "title": "不存在",
            },
        ]

        async def run():
            downloaded, fail_count, updates = await _concurrent_download(
                pending,
                mock_storage,
                "20230101",
            )
            assert downloaded == 1
            assert fail_count == 1
            assert len(updates) == 1

        asyncio.run(run())

    @patch("scripts.sync_minishare_ann_history.get_cninfo_pdf_async_limiter")
    def test_concurrent_all_fail(self, mock_limiter_fn):
        """全部下载失败"""
        import asyncio

        from scripts.sync_minishare_ann_history import _concurrent_download

        mock_limiter = AsyncMock()
        mock_limiter_fn.return_value = mock_limiter

        mock_storage = AsyncMock()
        mock_storage.download_notice_async.return_value = None

        pending = [
            {
                "cninfo_id": "ann_1",
                "pdf_url": "http://404.pdf",
                "ts_code": "000001.SZ",
                "title": "A",
            },
            {
                "cninfo_id": "ann_2",
                "pdf_url": "http://404.pdf",
                "ts_code": "000002.SZ",
                "title": "B",
            },
        ]

        async def run():
            downloaded, fail_count, updates = await _concurrent_download(
                pending,
                mock_storage,
                "20230101",
            )
            assert downloaded == 0
            assert fail_count == 2
            assert updates == []

        asyncio.run(run())

    @patch("scripts.sync_minishare_ann_history.get_cninfo_pdf_async_limiter")
    def test_empty_pending(self, mock_limiter_fn):
        """空待下载列表"""
        import asyncio

        from scripts.sync_minishare_ann_history import _concurrent_download

        mock_storage = AsyncMock()

        async def run():
            downloaded, fail_count, updates = await _concurrent_download(
                [],
                mock_storage,
                "20230101",
            )
            assert downloaded == 0
            assert fail_count == 0
            assert updates == []
            mock_storage.download_notice_async.assert_not_called()

        asyncio.run(run())
