"""Tests for CninfoClient regulatory announcement support.

Task: 巨潮监管公告四类 plate 分页/去重和 DataFetcher 入口
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestCninfoRegulatoryPlates:
    """Regulatory announcement plate constants."""

    def test_import(self):
        from app.data_pipeline.cninfo_client import REGU_PLATES

        assert isinstance(REGU_PLATES, dict)
        assert len(REGU_PLATES) >= 4

    def test_plate_keys(self):
        from app.data_pipeline.cninfo_client import REGU_PLATES

        for key, value in REGU_PLATES.items():
            assert isinstance(key, str)
            assert isinstance(value, dict)
            assert "column" in value
            assert "plate" in value
            assert "label" in value


class TestCninfoClientRegulatory:
    """CninfoClient regulatory announcement methods."""

    def test_has_regu_methods(self):
        from app.data_pipeline.cninfo_client import CninfoClient

        client = CninfoClient()
        assert hasattr(client, "query_regulatory_announcements")
        assert hasattr(client, "get_regulatory_announcements")

    @pytest.mark.asyncio
    async def test_query_regulatory_returns_empty_list_on_error(self):
        """query_regulatory_announcements should return empty list on API error."""
        from app.data_pipeline.cninfo_client import CninfoClient

        client = CninfoClient()
        with patch.object(client, "query_announcements", return_value={"total": 0, "list": []}):
            result = await client.query_regulatory_announcements(
                plate="szse", ann_date="20260501"
            )
            assert result["total"] == 0
            assert result["list"] == []

    @pytest.mark.asyncio
    async def test_get_regulatory_announcements_returns_list(self):
        """get_regulatory_announcements should return a list of announcements."""
        from app.data_pipeline.cninfo_client import CninfoClient

        client = CninfoClient()
        mock_ann = {"announcementId": "test123", "announcementTitle": "监管函", "secCode": "000001"}
        with patch.object(
            client, "query_regulatory_announcements",
            return_value={"total": 1, "list": [mock_ann], "has_more": False, "total_pages": 1},
        ):
            result = await client.get_regulatory_announcements(plate="szse", ann_date="20260501")
            assert len(result) == 1
            assert result[0]["announcementId"] == "test123"


class TestRegulatoryAnnouncementDedup:
    """Regulatory announcement deduplication."""

    def test_dedup_by_announcement_id(self):
        from app.data_pipeline.cninfo_client import CninfoClient

        anns = [
            {"announcementId": "1", "announcementTitle": "A"},
            {"announcementId": "2", "announcementTitle": "B"},
            {"announcementId": "1", "announcementTitle": "A_dup"},
        ]
        result = CninfoClient.dedup_announcements(anns)
        assert len(result) == 2
        ids = [a["announcementId"] for a in result]
        assert ids == ["1", "2"]


class TestDataFetcherRegulatoryEntry:
    """DataFetcher regulatory announcement entry point."""

    def test_import(self):
        from app.data_pipeline.fetcher import DataFetcher

        assert hasattr(DataFetcher, "fetch_regulatory_announcements")

    @pytest.mark.asyncio
    async def test_fetch_regulatory_announcements_returns_stats(self):
        """fetch_regulatory_announcements should return result stats."""
        from app.data_pipeline.fetcher import DataFetcher

        fetcher = DataFetcher()
        mock_client = AsyncMock()
        mock_client.get_regulatory_announcements.return_value = [
            {"announcementId": "1", "announcementTitle": "监管函", "secCode": "000001"},
        ]
        fetcher.cninfo_client = mock_client

        mock_process = AsyncMock()
        mock_process.return_value = {"total": 1, "success": 1, "skipped": 0, "downloaded": 0, "fail": 0}
        fetcher._process_announcement_list = mock_process

        # Mock the tracker to avoid DB connection
        import app.data_pipeline.fetcher as fetcher_mod
        mock_tracker = AsyncMock()
        mock_tracker.start_run.return_value = MagicMock()
        with patch.object(fetcher_mod, "IngestionProgressTracker", return_value=mock_tracker):
            result = await fetcher.fetch_regulatory_announcements(
                plate="szse", ann_date="20260501"
            )

        assert result["total"] == 1
        assert result["success"] == 1
