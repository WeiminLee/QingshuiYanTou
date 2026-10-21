"""指数日线映射、事件日期、大盘快照整形。"""

from datetime import date

import pytest

from app.data_pipeline.services.kline_service import shape_market_snapshot
from app.data_pipeline.tinyshare_client import assert_tinyshare_gateway
from app.data_pipeline.services.news_service import list_recent_events, parse_event_day, search_events
from scripts.sync_index_daily import next_index_start, rows_from_index_frame


def test_tinyshare_gateway_rejects_official_tushare():
    assert_tinyshare_gateway("http://mintree.site:8080")
    with pytest.raises(RuntimeError):
        assert_tinyshare_gateway("https://api.tushare.pro")
    with pytest.raises(RuntimeError):
        assert_tinyshare_gateway("http://api.waditu.com")


def test_next_index_start_uses_day_after_max():
    assert next_index_start(date(2026, 8, 17)) == "20260818"
    assert next_index_start(None) == "20260801"


def test_index_fetch_outcome_empty_weekday_is_failure():
    from scripts.sync_index_daily import index_fetch_outcome

    assert index_fetch_outcome("20261016", "20261016", 0) == "fail"
    assert index_fetch_outcome("20261017", "20261018", 0) == "ok"
    assert index_fetch_outcome("20261016", "20261016", 1) == "ok"


def test_rows_from_index_frame_maps_daily_data_record():
    records = rows_from_index_frame(
        "000001.SH",
        [
            {
                "trade_date": "20261016",
                "open": 3900,
                "high": 3950,
                "low": 3890,
                "close": 3920.5,
                "pre_close": 3910,
                "change": 10.5,
                "pct_chg": 0.27,
                "vol": 1_000,
                "amount": 500_000,
            }
        ],
    )
    assert records[0]["ts_code"] == "000001.SH"
    assert records[0]["trade_date"] == date(2026, 10, 16)
    assert records[0]["pct_chg"] == 0.27
    assert records[0]["is_suspended"] is False


def test_rows_from_index_frame_treats_blank_volume_as_suspended():
    records = rows_from_index_frame("399001.SZ", [{"trade_date": "20261016", "vol": None}])
    assert records[0]["vol"] == 0
    assert records[0]["is_suspended"] is True


def test_parse_event_day_accepts_both_formats():
    assert parse_event_day("20261016") == date(2026, 10, 16)
    assert parse_event_day("2026-10-16") == date(2026, 10, 16)
    assert parse_event_day("  ") is None


def test_parse_event_day_rejects_garbage():
    with pytest.raises(ValueError):
        parse_event_day("2026-13-40")


@pytest.mark.asyncio
async def test_search_events_binds_calendar_dates(monkeypatch):
    captured: dict = {}

    class _Result:
        def fetchall(self):
            return []

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def execute(self, stmt, params):
            captured["sql"] = str(stmt)
            captured["params"] = params
            return _Result()

    monkeypatch.setattr("app.core.database.async_session", lambda: _Session())
    out = await search_events(query="上证", date_from="2026-10-16", date_to="20261016")
    assert out["count"] == 0
    assert captured["params"]["date_from"] == date(2026, 10, 16)
    assert captured["params"]["date_to"] == date(2026, 10, 16)
    assert "Asia/Shanghai" in captured["sql"]


@pytest.mark.asyncio
async def test_list_recent_events_orders_by_publish_time(monkeypatch):
    captured: dict = {}

    class _Result:
        def fetchall(self):
            return [("EV:abc", "存储芯片", "摘要", "tushare", "2026-10-19 01:41:00+00:00")]

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def execute(self, stmt, params):
            captured["sql"] = str(stmt)
            captured["params"] = params
            return _Result()

    monkeypatch.setattr("app.core.database.async_session", lambda: _Session())
    out = await list_recent_events(50)
    assert out["count"] == 1
    assert out["items"][0]["event_id"] == "EV:abc"
    assert out["items"][0]["summary"] == "摘要"
    assert captured["params"]["limit"] == 30
    assert "publish_at DESC" in captured["sql"]


@pytest.mark.asyncio
async def test_search_events_bad_date_does_not_query():
    out = await search_events(query="上证", date_from="202610")
    assert out["count"] == 0
    assert "日期" in out["note"]


def test_shape_market_snapshot_converts_qianyuan_to_yi():
    # 1.55 万亿元 = 1_550_000_000 千元 / 100000 = 15500 亿元
    out = shape_market_snapshot("20261016", 3061, 2021, 132, 1_550_023_000, [])
    assert out["up"] == 3061
    assert out["amount_yi"] == 15500.23
