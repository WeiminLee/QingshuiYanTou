"""Tests for NewsService (tinyshare → 东方财富 7x24 快讯兜底)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def test_news_service_imports_without_tinyshare(monkeypatch):
    """NewsService module import should not require optional tinyshare package."""
    import builtins
    import importlib
    import sys

    module_name = "app.data_pipeline.services.news_service"
    original_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "tinyshare":
            raise ModuleNotFoundError("No module named 'tinyshare'")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    sys.modules.pop(module_name, None)

    module = importlib.import_module(module_name)

    assert module.get_news_service() is not None


def test_public_flash_payloads_become_records():
    """华尔街见闻、同花顺、新浪滚动的 JSON 解析成可入库的快讯。"""
    from datetime import UTC, datetime

    from app.data_pipeline.services.news_service import (
        parse_sina_roll_payload,
        parse_ths_payload,
        parse_wallstreetcn_payload,
    )

    wallstreet = parse_wallstreetcn_payload(
        {
            "data": {
                "items": [
                    {
                        "title": "",
                        "content_text": "美联储维持利率不变",
                        "content": "<p>忽略</p>",
                        "uri": "https://wallstcn.com/l/1",
                        "display_time": 1792480050,
                    },
                    {
                        "title": "已有标题",
                        "content_text": "正文",
                        "uri": "https://wallstcn.com/l/2",
                        "display_time": 1792480050000,
                    },
                    {
                        "title": "",
                        "content_text": "",
                        "content": "<p>只有<b>网页</b></p>",
                        "uri": "https://wallstcn.com/l/3",
                        "display_time": "1792480100",
                    },
                    {"title": "", "content_text": "", "content": ""},
                ]
            }
        }
    )
    assert [row["title"] for row in wallstreet] == ["美联储维持利率不变", "已有标题", "只有网页"]
    assert wallstreet[0]["summary"] == "美联储维持利率不变"
    assert wallstreet[0]["url"] == "https://wallstcn.com/l/1"
    assert wallstreet[0]["source"] == "wallstreetcn"
    assert wallstreet[0]["publish_at"] == datetime.fromtimestamp(1792480050, tz=UTC)
    assert wallstreet[1]["summary"] == "正文"
    assert wallstreet[1]["publish_at"] == datetime.fromtimestamp(1792480050, tz=UTC)
    assert wallstreet[2]["summary"] == "只有网页"

    ths = parse_ths_payload(
        {
            "data": {
                "list": [
                    {
                        "title": "同花顺标题",
                        "digest": "摘要",
                        "url": "https://news.10jqka.com.cn/1",
                        "ctime": 1792480050,
                    },
                    {"title": "  ", "digest": "空标题", "ctime": 1792480050},
                ]
            }
        }
    )
    assert len(ths) == 1
    assert ths[0]["source"] == "ths"
    assert ths[0]["summary"] == "摘要"
    assert ths[0]["url"] == "https://news.10jqka.com.cn/1"
    assert ths[0]["publish_at"] == datetime.fromtimestamp(1792480050, tz=UTC)

    sina = parse_sina_roll_payload(
        {
            "result": {
                "data": [
                    {
                        "title": "新浪标题",
                        "intro": "导语",
                        "url": "https://finance.sina.com.cn/1",
                        "ctime": 1792480050,
                    }
                ]
            }
        }
    )
    assert sina[0]["source"] == "sina"
    assert sina[0]["summary"] == "导语"
    assert sina[0]["publish_at"] == datetime.fromtimestamp(1792480050, tz=UTC)
    assert parse_sina_roll_payload({"result": {"data": {"zhibo": 0}}}) == []


def test_stable_event_id_deduplicates():
    """相同标题产生相同的 stable_event_id。"""
    from app.data_pipeline.services.news_service import stable_event_id

    title = "同一标题"
    assert stable_event_id(title) == stable_event_id(title)
    assert stable_event_id(title) != stable_event_id("不同标题")


def _setup(svc, ns_mod, *, flash_records, execute=None, tushare_df=None, public=None):
    """构造 tinyshare 失败 + 快讯兜底场景的 mocks，返回 patches 列表。"""
    public = public or {}
    fake_pro = MagicMock()
    if tushare_df is not None:
        fake_pro.news.return_value = tushare_df
    else:
        fake_pro.news.side_effect = Exception("no news permission")

    fake_conn = AsyncMock()
    fake_conn.__aenter__.return_value = fake_conn
    if execute is not None:
        fake_conn.execute = execute
    else:
        fake_conn.execute.return_value.rowcount = 1

    fake_engine = MagicMock()
    fake_engine.connect.return_value = fake_conn

    ingest = AsyncMock()
    return [
        patch.object(ns_mod, "_get_ts_pro", return_value=fake_pro),
        patch.object(svc, "_fetch_eastmoney_flash", return_value=flash_records),
        patch.object(svc, "_fetch_wallstreetcn", return_value=public.get("wallstreetcn", [])),
        patch.object(svc, "_fetch_ths", return_value=public.get("ths", [])),
        patch.object(svc, "_fetch_sina_roll", return_value=public.get("sina", [])),
        patch.object(svc, "_load_concept_names", new_callable=AsyncMock, return_value=[]),
        patch.object(ns_mod, "engine", fake_engine),
        patch("app.signals.auto_ingestion.ingest_event_signals", ingest),
    ], ingest


@pytest.mark.asyncio
async def test_tushare_exception_triggers_eastmoney_fallback():
    """tinyshare news 无权限时，走东方财富快讯兜底并写入（相同标题去重）。"""
    import app.data_pipeline.services.news_service as ns_mod
    from app.data_pipeline.services.news_service import NewsService

    svc = NewsService()
    flash_records = [
        {"title": "利好公告", "summary": "某公司发布业绩预增", "url": "https://a", "publish_at": "2026-05-12 09:00"},
        {"title": "利好公告", "summary": "重复内容", "url": "https://b", "publish_at": "2026-05-12 09:00"},
    ]
    patches, _ingest = _setup(svc, ns_mod, flash_records=flash_records)
    for p in patches:
        p.start()
    try:
        result = await svc.fetch_and_save()
    finally:
        for p in patches:
            p.stop()

    assert result["fetched"] == 2
    # mock 的 execute 恒返回 rowcount=1，inserted/skipped 按 mock 计 2/0；
    # 真实去重由 ON CONFLICT 在 DB 层完成（见 test_stable_event_id_deduplicates）
    assert result["inserted"] == 2


@pytest.mark.asyncio
async def test_eastmoney_fields_mapped_correctly():
    """快讯记录的 title/summary/source 正确映射到 events 表字段。"""
    import app.data_pipeline.services.news_service as ns_mod
    from app.data_pipeline.services.news_service import NewsService, stable_event_id

    svc = NewsService()
    captured = {}

    async def fake_execute(stmt, params):
        captured.update(params)
        result = MagicMock()
        result.rowcount = 1
        return result

    flash_records = [{"title": "标题A", "summary": "内容A", "url": "https://a", "publish_at": "2026-05-12 08:30"}]
    patches, _ingest = _setup(svc, ns_mod, flash_records=flash_records, execute=fake_execute)
    for p in patches:
        p.start()
    try:
        await svc.fetch_and_save()
    finally:
        for p in patches:
            p.stop()

    assert captured["title"] == "标题A"
    assert captured["summary"] == "内容A"
    assert captured["source"] == "eastmoney_flash"
    assert captured["event_id"] == stable_event_id("标题A")


@pytest.mark.asyncio
async def test_tushare_source_tag():
    """tinyshare news 成功路径使用 source='tushare'。"""
    import pandas as pd

    import app.data_pipeline.services.news_service as ns_mod
    from app.data_pipeline.services.news_service import NewsService

    svc = NewsService()
    captured = {}

    async def fake_execute(stmt, params):
        captured["source"] = params.get("source")
        result = MagicMock()
        result.rowcount = 1
        return result

    tushare_df = pd.DataFrame([{"title": "Tushare新闻", "content": "内容", "pub_time": "2026-05-12 09:00", "url": "http://t.cn"}])
    patches, ingest = _setup(svc, ns_mod, flash_records=[], execute=fake_execute, tushare_df=tushare_df)
    for p in patches:
        p.start()
    try:
        await svc.fetch_and_save()
    finally:
        for p in patches:
            p.stop()

    assert captured["source"] == "tushare"
    rows = ingest.await_args.args[0]
    assert rows[0]["source"] == "tushare"
    assert rows[0]["title"] == "Tushare新闻"


@pytest.mark.asyncio
async def test_already_stored_flash_still_goes_to_signal_extraction():
    """已存在的快讯也要二次加工。冲突跳过不能把 signal 漏掉。"""
    import app.data_pipeline.services.news_service as ns_mod
    from app.data_pipeline.services.news_service import NewsService

    svc = NewsService()

    async def fake_execute(stmt, params):
        result = MagicMock()
        result.rowcount = 0
        return result

    flash_records = [{"title": "业绩预增", "summary": "公司业绩预增", "url": "https://a", "publish_at": "2026-05-12 08:30"}]
    patches, ingest = _setup(svc, ns_mod, flash_records=flash_records, execute=fake_execute)
    for p in patches:
        p.start()
    try:
        result = await svc.fetch_and_save()
    finally:
        for p in patches:
            p.stop()

    assert result["inserted"] == 0
    rows = ingest.await_args.args[0]
    assert rows[0]["source"] == "eastmoney_flash"
    assert rows[0]["title"] == "业绩预增"


@pytest.mark.asyncio
async def test_signal_extraction_failure_keeps_the_saved_event():
    import app.data_pipeline.services.news_service as ns_mod
    from app.data_pipeline.services.news_service import NewsService

    svc = NewsService()
    flash_records = [{"title": "标题A", "summary": "内容A", "url": "https://a", "publish_at": "2026-05-12 08:30"}]
    patches, ingest = _setup(svc, ns_mod, flash_records=flash_records)
    ingest.side_effect = RuntimeError("signals down")
    for p in patches:
        p.start()
    try:
        result = await svc.fetch_and_save()
    finally:
        for p in patches:
            p.stop()

    assert result["inserted"] == 1


@pytest.mark.asyncio
async def test_new_wires_are_stored_and_only_fresh_rows_are_derived():
    """三路新源入库；只有新插入的行进推导。东财已入库的仍要加工。"""
    import app.data_pipeline.services.news_service as ns_mod
    from app.data_pipeline.services.news_service import NewsService

    svc = NewsService()
    saved: list[dict] = []

    async def fake_execute(stmt, params):
        saved.append(dict(params))
        result = MagicMock()
        result.rowcount = 0 if params["source"] in {"eastmoney_flash", "sina"} else 1
        return result

    flash_records = [
        {"title": "东财旧闻", "summary": "东财摘要", "url": "https://e", "publish_at": "2026-05-12 08:30"},
    ]
    public = {
        "wallstreetcn": [
            {
                "title": "见闻新讯",
                "summary": "见闻正文",
                "url": "https://w",
                "publish_at": "2026-05-12 08:31",
                "source": "wallstreetcn",
            }
        ],
        "ths": [
            {
                "title": "同花顺一条",
                "summary": "同花顺正文",
                "url": "https://t",
                "publish_at": "2026-05-12 08:32",
                "source": "ths",
            }
        ],
        "sina": [
            {
                "title": "新浪已有",
                "summary": "新浪正文",
                "url": "https://s",
                "publish_at": "2026-05-12 08:33",
                "source": "sina",
            }
        ],
    }
    patches, ingest = _setup(
        svc,
        ns_mod,
        flash_records=flash_records,
        execute=fake_execute,
        public=public,
    )
    for p in patches:
        p.start()
    try:
        result = await svc.fetch_and_save()
    finally:
        for p in patches:
            p.stop()

    assert result["fetched"] == 4
    assert result["inserted"] == 2
    assert [row["source"] for row in saved] == ["eastmoney_flash", "wallstreetcn", "ths", "sina"]
    assert saved[1]["content"] == "见闻正文"
    derived = [row["source"] for row in ingest.await_args.args[0]]
    assert derived == ["eastmoney_flash", "wallstreetcn", "ths"]


def test_public_fetch_caps_the_page_and_isolates_failure(monkeypatch):
    """单路失败不影响另外两路，每路最多 50 条。"""
    import requests

    from app.data_pipeline.services.news_service import NewsService

    seen: list[tuple[str, dict]] = []

    def fake_get(url, params=None, headers=None, timeout=None):
        seen.append((url, params or {}))
        if "sina.com.cn" in url:
            raise requests.ConnectionError("sina down")

        class Resp:
            def raise_for_status(self):
                return None

            def json(self):
                if "wallstcn.com" in url:
                    return {
                        "data": {
                            "items": [
                                {"content_text": "一条见闻", "uri": "https://w", "display_time": 1792480050}
                            ]
                        }
                    }
                return {
                    "data": {
                        "list": [
                            {"title": "一条同花顺", "digest": "摘要", "url": "https://t", "ctime": 1792480050}
                        ]
                    }
                }

        return Resp()

    monkeypatch.setattr(requests, "get", fake_get)
    svc = NewsService()
    wallstreet = svc._fetch_wallstreetcn(200)
    ths = svc._fetch_ths(200)
    sina = svc._fetch_sina_roll(200)

    assert wallstreet[0]["title"] == "一条见闻"
    assert wallstreet[0]["source"] == "wallstreetcn"
    assert ths[0]["source"] == "ths"
    assert sina == []
    assert seen[0][1]["limit"] == 50
    assert seen[1][1]["pagesize"] == 50