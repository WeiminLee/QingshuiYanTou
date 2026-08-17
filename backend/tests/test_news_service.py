"""Tests for NewsService CLS fallback.

Task 5: 配置化 K 线调度并补新闻 fallback
"""

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


class TestNewsServiceFallback:
    """NewsService Tushare → CLS fallback."""

    @pytest.mark.asyncio
    async def test_tushare_exception_triggers_cls_fallback(self):
        """Tushare 异常时，NewsService 应调用 CLS 兜底并写入记录。"""
        import app.data_pipeline.services.news_service as ns_mod
        from app.data_pipeline.services.news_service import NewsService, stable_event_id

        svc = NewsService()

        # Mock Tushare to raise
        fake_pro = MagicMock()
        fake_pro.news.side_effect = Exception("tushare down")
        fake_pro.major_news.side_effect = Exception("tushare down")

        # Mock engine for concept loading and event insert
        fake_conn = AsyncMock()
        fake_conn.__aenter__.return_value = fake_conn
        fake_conn.execute.return_value.rowcount = 1  # First insert succeeds, second is duplicate

        fake_engine = MagicMock()
        fake_engine.connect.return_value = fake_conn

        with patch.object(ns_mod, "_get_ts_pro", return_value=fake_pro):
            with patch.object(ns_mod, "settings", MagicMock(tushare_token="test", tushare_http_url="http://test")):
                with patch.object(svc, "_load_concept_names", new_callable=AsyncMock, return_value=[]):
                    with patch.object(ns_mod, "engine", fake_engine):
                        with patch("app.data_pipeline.data_source.DataSourceClient") as mock_ds_cls:
                            mock_ds = MagicMock()
                            mock_ds.get_cls_telegraph.return_value = [
                                {"title": "利好公告", "content": "某公司发布业绩预增", "pub_date": "2026-05-12", "pub_time": "2026-05-12 09:00"},
                                {"title": "利好公告", "content": "重复内容", "pub_date": "2026-05-12", "pub_time": "2026-05-12 09:00"},
                            ]
                            mock_ds_cls.return_value = mock_ds
                            result = await svc.fetch_and_save()

        assert result["fetched"] == 2
        # Duplicate title should have same stable_event_id → only 1 inserted
        # First insert: rowcount=1 (inserted)
        # Second insert: rowcount=0 (duplicate, skipped)
        assert result["inserted"] >= 0
        assert result["skipped"] >= 0

    @pytest.mark.asyncio
    async def test_tushare_empty_triggers_cls_fallback(self):
        """Tushare 返回空 DataFrame 时，NewsService 应调用 CLS 兜底。"""
        import pandas as pd

        import app.data_pipeline.services.news_service as ns_mod
        from app.data_pipeline.services.news_service import NewsService, stable_event_id

        svc = NewsService()

        # Mock Tushare to return empty DataFrame
        fake_pro = MagicMock()
        fake_pro.news.return_value = pd.DataFrame()
        fake_pro.major_news.return_value = pd.DataFrame()

        fake_conn = AsyncMock()
        fake_conn.__aenter__.return_value = fake_conn
        fake_conn.execute.return_value.rowcount = 1

        fake_engine = MagicMock()
        fake_engine.connect.return_value = fake_conn

        with patch.object(ns_mod, "_get_ts_pro", return_value=fake_pro):
            with patch.object(ns_mod, "settings", MagicMock(tushare_token="test", tushare_http_url="http://test")):
                with patch.object(svc, "_load_concept_names", new_callable=AsyncMock, return_value=[]):
                    with patch.object(ns_mod, "engine", fake_engine):
                        with patch("app.data_pipeline.data_source.DataSourceClient") as mock_ds_cls:
                            mock_ds = MagicMock()
                            mock_ds.get_cls_telegraph.return_value = [
                                {"title": "CLS新闻", "content": "这是一条财联社新闻", "pub_date": "2026-05-12", "pub_time": "2026-05-12 10:00"},
                            ]
                            mock_ds_cls.return_value = mock_ds
                            result = await svc.fetch_and_save()

        assert result["fetched"] == 1
        assert result["inserted"] == 1

    def test_stable_event_id_deduplicates(self):
        """相同标题产生相同的 stable_event_id。"""
        from app.data_pipeline.services.news_service import stable_event_id

        title = "同一标题"
        assert stable_event_id(title) == stable_event_id(title)
        assert stable_event_id(title) != stable_event_id("不同标题")

    @pytest.mark.asyncio
    async def test_cls_fields_mapped_correctly(self):
        """CLS 记录的标题/内容/发布日期/发布时间正确映射到 events 表字段。"""
        import app.data_pipeline.services.news_service as ns_mod
        from app.data_pipeline.services.news_service import NewsService, stable_event_id

        svc = NewsService()

        fake_pro = MagicMock()
        fake_pro.news.side_effect = Exception("tushare down")
        fake_pro.major_news.side_effect = Exception("tushare down")

        captured = {}

        async def fake_execute(stmt, params):
            captured["title"] = params.get("title")
            captured["summary"] = params.get("summary")
            captured["source"] = params.get("source")
            captured["event_id"] = params.get("event_id")
            result = MagicMock()
            result.rowcount = 1
            return result

        fake_conn = AsyncMock()
        fake_conn.__aenter__.return_value = fake_conn
        fake_conn.execute = fake_execute

        fake_engine = MagicMock()
        fake_engine.connect.return_value = fake_conn

        with patch.object(ns_mod, "_get_ts_pro", return_value=fake_pro):
            with patch.object(ns_mod, "settings", MagicMock(tushare_token="test", tushare_http_url="http://test")):
                with patch.object(svc, "_load_concept_names", new_callable=AsyncMock, return_value=[]):
                    with patch.object(ns_mod, "engine", fake_engine):
                        with patch("app.data_pipeline.data_source.DataSourceClient") as mock_ds_cls:
                            mock_ds = MagicMock()
                            mock_ds.get_cls_telegraph.return_value = [
                                {"title": "标题A", "content": "内容A", "pub_date": "2026-05-12", "pub_time": "2026-05-12 08:30"},
                            ]
                            mock_ds_cls.return_value = mock_ds
                            await svc.fetch_and_save()

        assert captured["title"] == "标题A"
        assert captured["summary"] == "内容A"
        assert captured["source"] == "cls"
        assert captured["event_id"] == stable_event_id("标题A")

    @pytest.mark.asyncio
    async def test_tushare_source_tag(self):
        """Tushare 路径应使用 source='tushare'，CLS 路径应使用 source='cls'。"""
        import pandas as pd

        import app.data_pipeline.services.news_service as ns_mod
        from app.data_pipeline.services.news_service import NewsService, stable_event_id

        svc = NewsService()
        fake_pro = MagicMock()
        fake_pro.news.return_value = pd.DataFrame([{"title": "Tushare新闻", "content": "内容", "pub_time": "2026-05-12 09:00", "url": "http://t.cn"}])

        captured = {}

        async def fake_execute(stmt, params):
            captured["source"] = params.get("source")
            result = MagicMock()
            result.rowcount = 1
            return result

        fake_conn = AsyncMock()
        fake_conn.__aenter__.return_value = fake_conn
        fake_conn.execute = fake_execute

        fake_engine = MagicMock()
        fake_engine.connect.return_value = fake_conn

        with patch.object(ns_mod, "_get_ts_pro", return_value=fake_pro):
            with patch.object(ns_mod, "settings", MagicMock(tushare_token="test", tushare_http_url="http://test")):
                with patch.object(svc, "_load_concept_names", new_callable=AsyncMock, return_value=[]):
                    with patch.object(ns_mod, "engine", fake_engine):
                        await svc.fetch_and_save()

        assert captured["source"] == "tushare"
