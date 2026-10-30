"""海外行情解析/股票池测试（不打网络）。"""

from datetime import date

from app.data_pipeline.overseas_client import _extract_json, parse_chart
from app.data_pipeline.overseas_universe import universe_for


def _payload():
    return {
        "chart": {
            "result": [
                {
                    "meta": {"symbol": "2330.TW", "currency": "TWD", "firstTradeDate": 946947600},
                    "timestamp": [1728000000, 1728086400, 1728172800],
                    "indicators": {
                        "quote": [
                            {
                                "open": [1000.0, 1010.0, None],
                                "high": [1020.0, 1030.0, None],
                                "low": [990.0, 1000.0, None],
                                "close": [1010.0, 1020.0, None],
                                "volume": [1000, 2000, 0],
                            }
                        ]
                    },
                }
            ],
            "error": None,
        }
    }


def test_parse_chart_bars():
    bars = parse_chart(_payload())
    assert len(bars) == 2  # 第三条 close=None 被跳过
    assert bars[0]["trade_date"] == date(2024, 10, 4)
    assert bars[0]["pre_close"] is None
    assert bars[1]["pre_close"] == 1010.0
    assert bars[1]["pct_chg"] == round((1020.0 - 1010.0) / 1010.0 * 100, 4)


def test_extract_json_with_jina_header():
    body = 'Title: \n\nURL Source: https://x\n\nMarkdown Content:\n{"chart": {"result": [], "error": null}}'
    assert _extract_json(body)["chart"]["result"] == []


def test_universe_filter():
    us = universe_for(["US"])
    assert us and all(r[3] == "US" for r in us)
    assert any(r[0] == "NVDA" for r in us)
    tw = universe_for(["TW"])
    assert any(r[0] == "2330.TW" for r in tw)
    kr = universe_for(["KR"])
    assert any(r[0] == "005930.KS" for r in kr)
