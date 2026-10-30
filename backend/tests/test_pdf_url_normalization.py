"""cninfo 详情页 → static finalpage PDF 直链归一化。"""

from datetime import date

from app.data_pipeline.fetcher import normalize_cninfo_pdf_url


def test_detail_page_to_static_pdf():
    url = (
        "http://www.cninfo.com.cn/new/disclosure/detail?stockCode=688103"
        "&announcementId=1221305653&orgId=9900035534&announcementTime=2024-09-27"
    )
    assert (
        normalize_cninfo_pdf_url(url, date(2024, 9, 27))
        == "http://static.cninfo.com.cn/finalpage/2024-09-27/1221305653.PDF"
    )


def test_direct_pdf_kept():
    url = "http://static.cninfo.com.cn/finalpage/2024-09-27/1221305653.PDF"
    assert normalize_cninfo_pdf_url(url, date(2024, 9, 27)) == url


def test_non_cninfo_kept():
    url = "https://example.com/a.pdf"
    assert normalize_cninfo_pdf_url(url, date(2024, 9, 27)) == url


def test_missing_announcement_id_kept():
    url = "http://www.cninfo.com.cn/new/disclosure/detail?stockCode=688103"
    assert normalize_cninfo_pdf_url(url, date(2024, 9, 27)) == url


def test_missing_date_kept():
    url = "http://www.cninfo.com.cn/new/disclosure/detail?announcementId=1221305653"
    assert normalize_cninfo_pdf_url(url, None) == url
