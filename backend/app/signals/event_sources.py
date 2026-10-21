"""Event origins that are secondary-processed into signals.

公告语料的 signal 用 source_type=announcement（公告栏）。
财联社、东财和一般新闻用 news（新闻快讯栏）。
互动易、央行政策、彭博用 event（事件栏）。
未知新闻来源归到 news，不丢弃。
"""

from __future__ import annotations

_ORIGIN_BY_SOURCE: dict[str, str] = {
    "announcement": "announcement",
    "cninfo_announcement": "announcement",
    "公告": "announcement",
    "irm": "irm",
    "interactive_qa": "irm",
    "互动易": "irm",
    "cls": "cls",
    "cailian": "cls",
    "cailianshe": "cls",
    "财联社": "cls",
    "tushare": "cls",
    "eastmoney_flash": "eastmoney",
    "eastmoney": "eastmoney",
    "东财": "eastmoney",
    "wallstreetcn": "news",
    "华尔街见闻": "news",
    "ths": "news",
    "同花顺": "news",
    "sina": "news",
    "新浪": "news",
    "news": "news",
    "news_flash": "news",
    "pboc": "pboc",
    "pbc": "pboc",
    "央行": "pboc",
    "央行政策": "pboc",
    "bloomberg": "bloomberg",
    "彭博": "bloomberg",
    "彭博社": "bloomberg",
}

_SOURCE_TYPE_BY_ORIGIN: dict[str, str] = {
    "announcement": "announcement",
    "irm": "event",
    "cls": "news",
    "eastmoney": "news",
    "news": "news",
    "pboc": "event",
    "bloomberg": "event",
}


def resolve_event_origin(source: str | None) -> str:
    raw = (source or "").strip()
    if raw in _ORIGIN_BY_SOURCE:
        return _ORIGIN_BY_SOURCE[raw]
    lowered = raw.lower()
    if lowered in _ORIGIN_BY_SOURCE:
        return _ORIGIN_BY_SOURCE[lowered]
    return "news"


def signal_source_type_for_origin(origin: str) -> str:
    return _SOURCE_TYPE_BY_ORIGIN.get(origin, "event")
