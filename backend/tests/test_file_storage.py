"""
Test _resolve_pdf_url static method of FileStorage.
"""

from unittest.mock import patch

import pytest

from app.data_pipeline.file_storage import FileStorage


class TestResolvePdfUrl:
    """_resolve_pdf_url 测试"""

    def test_direct_pdf_url_https(self):
        """HTTPS 直接 PDF 链接原样返回"""
        url = "https://www.cninfo.com.cn/finalpage/2024-01-01/12345678.PDF"
        assert FileStorage._resolve_pdf_url(url) == url

    def test_direct_pdf_url_http(self):
        """HTTP 协议升级为 HTTPS"""
        url = "http://www.cninfo.com.cn/finalpage/2024-01-01/12345678.PDF"
        expected = "https://www.cninfo.com.cn/finalpage/2024-01-01/12345678.PDF"
        assert FileStorage._resolve_pdf_url(url) == expected

    def test_direct_pdf_url_lowercase_ext(self):
        """小写 .pdf 扩展名"""
        url = "https://www.cninfo.com.cn/finalpage/2024-01-01/12345678.pdf"
        assert FileStorage._resolve_pdf_url(url) == url

    @patch("app.data_pipeline.file_storage.requests.post")
    def test_detail_page_url(self, mock_post):
        """详情页 URL 用 mock 调 bulletin_detail API 返回 fileUrl"""
        mock_post.return_value.ok = True
        mock_post.return_value.json.return_value = {
            "fileUrl": "https://static.cninfo.com.cn/finalpage/2024-01-01/12345678.PDF"
        }
        url = "http://www.cninfo.com.cn/new/disclosure/detail?announcementId=123456&announceTime=2024-01-01"
        expected = "https://static.cninfo.com.cn/finalpage/2024-01-01/12345678.PDF"
        assert FileStorage._resolve_pdf_url(url) == expected
        mock_post.assert_called_once()

    def test_detail_page_without_announce_id(self):
        """缺少 announcementId 返回 None"""
        url = "http://www.cninfo.com.cn/new/disclosure/detail?orgId=abc"
        assert FileStorage._resolve_pdf_url(url) is None

    @patch("app.data_pipeline.file_storage.requests.post")
    def test_detail_page_api_fails(self, mock_post):
        """API 调用失败返回 None"""
        mock_post.return_value.ok = False
        url = "http://www.cninfo.com.cn/new/disclosure/detail?announcementId=123456&announceTime=2024-01-01"
        assert FileStorage._resolve_pdf_url(url) is None

    @patch("app.data_pipeline.file_storage.requests.post")
    def test_detail_page_api_no_fileurl(self, mock_post):
        """API 返回缺失 fileUrl 返回 None"""
        mock_post.return_value.ok = True
        mock_post.return_value.json.return_value = {"someOtherKey": "value"}
        url = "http://www.cninfo.com.cn/new/disclosure/detail?announcementId=123456&announceTime=2024-01-01"
        assert FileStorage._resolve_pdf_url(url) is None

    def test_unknown_url_format(self):
        """未知格式返回 None"""
        url = "https://example.com/some-page.html"
        assert FileStorage._resolve_pdf_url(url) is None

    def test_empty_url(self):
        """空 URL 返回 None"""
        assert FileStorage._resolve_pdf_url("") is None
        assert FileStorage._resolve_pdf_url("   ") is None
        assert FileStorage._resolve_pdf_url(None) is None
