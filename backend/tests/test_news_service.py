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


def test_stable_event_id_deduplicates():
    """相同标题产生相同的 stable_event_id。"""
    from app.data_pipeline.services.news_service import stable_event_id

    title = "同一标题"
    assert stable_event_id(title) == stable_event_id(title)
    assert stable_event_id(title) != stable_event_id("不同标题")


def _setup(svc, ns_mod, *, flash_records, execute=None, tushare_df=None):
    """构造 tinyshare 失败 + 快讯兜底场景的 mocks，返回 patches 列表。"""
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

    return [
        patch.object(ns_mod, "_get_ts_pro", return_value=fake_pro),
        patch.object(svc, "_fetch_eastmoney_flash", return_value=flash_records),
        patch.object(svc, "_load_concept_names", new_callable=AsyncMock, return_value=[]),
        patch.object(ns_mod, "engine", fake_engine),
    ]


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
    patches = _setup(svc, ns_mod, flash_records=flash_records)
    for p in patches:
        p.start()
    try:
        result = await svc.fetch_and_save()
    finally:
        for p in patches:
            p.stop()

    assert result["fetched"] == 2
    assert result["inserted"] == 1
    assert result["skipped"] == 1


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
    patches = _setup(svc, ns_mod, flash_records=flash_records, execute=fake_execute)
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
    patches = _setup(svc, ns_mod, flash_records=[], execute=fake_execute, tushare_df=tushare_df)
    for p in patches:
        p.start()
    try:
        await svc.fetch_and_save()
    finally:
        for p in patches:
            p.stop()

    assert captured["source"] == "tushare"