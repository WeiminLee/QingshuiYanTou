"""minishare 公告翻页测试。

供应商 anns_d 单次最多返回 2000 条（传 5000/20000 也一样），
2026-10-30 实测单日全市场 4500+ 条，只取第一页会漏掉一半以上。
"""

import pandas as pd
import pytest

from app.data_pipeline.minishare_client import DataSourceClientMinishare


class _FakeAnnsApi:
    def __init__(self, pages):
        self._pages = pages
        self.calls = []

    def anns_d(self, **kwargs):
        self.calls.append(kwargs)
        idx = len(self.calls) - 1
        if idx >= len(self._pages):
            return None
        return self._pages[idx]


def _make_client(api) -> DataSourceClientMinishare:
    client = DataSourceClientMinishare.__new__(DataSourceClientMinishare)
    client._anns_api = api
    # 绕过 token 校验，专注翻页逻辑（token 装配由其它测试覆盖）
    client._ensure_anns_api = lambda: api
    return client


def _frame(start: int, count: int, prefix: str = "600") -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "ann_date": "20261029",
                "ts_code": f"{prefix}{i:03d}.SH",
                "name": "测试",
                "title": f"标题{i}",
                "url": f"http://example.com/{i}.pdf",
            }
            for i in range(start, start + count)
        ]
    )


def test_paginates_until_short_page():
    api = _FakeAnnsApi([_frame(0, 2000), _frame(2000, 2000), _frame(4000, 577)])
    client = _make_client(api)

    records = client.get_announcements(ann_date="20261029")

    assert len(records) == 4577
    assert [c["offset"] for c in api.calls] == [0, 2000, 4000]
    assert all(c["limit"] == 2000 for c in api.calls)


def test_dedupes_overlapping_pages():
    # 第二页有 500 条与第一页重复，只应保留新出现的
    api = _FakeAnnsApi(
        [
            _frame(0, 2000),
            _frame(1500, 2000),
            _frame(3500, 500),
        ]
    )
    client = _make_client(api)

    records = client.get_announcements(ann_date="20261029")

    assert len(records) == len({(r["ann_date"], r["ts_code"], r["title"]) for r in records})
    assert len(records) == 4000  # 0..1999 + 2000..3499 + 3500..3999


def test_stops_on_repeated_page():
    # 供应商忽略 offset 反复返回同一页时，不能死循环
    page = _frame(0, 2000)
    api = _FakeAnnsApi([page, page, page, page])
    client = _make_client(api)

    records = client.get_announcements(ann_date="20261029")

    assert len(records) == 2000
    assert len(api.calls) == 3  # 首次有新增 + 连续两页无新增即停


def test_returns_empty_without_params():
    api = _FakeAnnsApi([_frame(0, 10)])
    client = _make_client(api)

    assert client.get_announcements() == []
