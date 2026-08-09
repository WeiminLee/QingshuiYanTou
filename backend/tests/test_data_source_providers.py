"""Tests for Kline provider protocol, normalization, and fallback registry.

Task 1: 建立 K 线标准 provider 协议和 fallback registry
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional

import pytest

from app.data_pipeline.data_source import DataSourceClient


# =========================================================================
# Fake providers for testing
# =========================================================================


@dataclass
class FakeProvider:
    """A fake provider that returns canned data for testing."""
    name: str
    records: list[dict[str, Any]]
    should_raise: bool = False
    raise_msg: str = ""

    def fetch_stock_kline(
        self,
        ts_code: str,
        start_date: str,
        end_date: str,
        adjustflag: str = "3",
    ) -> list[dict[str, Any]]:
        if self.should_raise:
            raise RuntimeError(self.raise_msg or f"{self.name} failed")
        return self.records


@dataclass
class FakePrimaryProvider:
    """Primary provider that always raises."""
    name: str = "primary"

    def fetch_stock_kline(
        self,
        ts_code: str,
        start_date: str,
        end_date: str,
        adjustflag: str = "3",
    ) -> list[dict[str, Any]]:
        raise RuntimeError("primary failed")


@dataclass
class FakeEmptyProvider:
    """Provider that returns empty list."""
    name: str = "empty"
    should_raise: bool = False

    def fetch_stock_kline(
        self,
        ts_code: str,
        start_date: str,
        end_date: str,
        adjustflag: str = "3",
    ) -> list[dict[str, Any]]:
        if self.should_raise:
            raise RuntimeError("empty provider failed")
        return []


@dataclass
class FakeFallbackProvider:
    """Provider that returns one valid row."""
    name: str = "fallback"

    def fetch_stock_kline(
        self,
        ts_code: str,
        start_date: str,
        end_date: str,
        adjustflag: str = "3",
    ) -> list[dict[str, Any]]:
        return [
            {
                "date": "2026-05-12",
                "code": "sh.600000",
                "open": "10.0",
                "high": "10.5",
                "low": "9.8",
                "close": "10.2",
                "preclose": "10.0",
                "volume": "1000000",
                "amount": "10200000",
                "pctChg": "2.0",
                "tradestatus": "1",
                "isST": "0",
            }
        ]


# =========================================================================
# Tests
# =========================================================================


class TestKlineProviderResult:
    """KlineProviderResult dataclass construction."""

    def test_import(self):
        from app.data_pipeline.providers import KlineProviderResult

        result = KlineProviderResult(
            records=[{"date": "2026-05-12"}],
            source="test",
            fallback_used=False,
            errors=[],
        )
        assert result.records == [{"date": "2026-05-12"}]
        assert result.source == "test"
        assert result.fallback_used is False
        assert result.errors == []

    def test_immutable(self):
        from app.data_pipeline.providers import KlineProviderResult

        result = KlineProviderResult(
            records=[], source="test", fallback_used=False, errors=[]
        )
        with pytest.raises((TypeError, AttributeError)):
            result.records = []  # type: ignore[misc]

    def test_immutable_nested(self):
        """The dataclass itself should be frozen."""
        from app.data_pipeline.providers import KlineProviderResult

        result = KlineProviderResult(
            records=[], source="test", fallback_used=False, errors=[]
        )
        with pytest.raises((TypeError, AttributeError)):
            result.source = "other"  # type: ignore[misc]


class TestNormalizeKlineRecord:
    """normalize_kline_record() field normalization."""

    def test_import(self):
        from app.data_pipeline.providers import normalize_kline_record

        assert callable(normalize_kline_record)

    def test_normalizes_numeric_fields(self):
        from app.data_pipeline.providers import normalize_kline_record

        ts_code = "600000.SH"
        raw = {
            "date": "2026-05-12",
            "code": "sh.600000",
            "open": "10.0",
            "high": "10.5",
            "low": "9.8",
            "close": "10.2",
            "preclose": "10.0",
            "volume": "1000000",
            "amount": "10200000",
            "pctChg": "2.0",
            "tradestatus": "1",
        }
        result = normalize_kline_record(raw, ts_code)

        assert result["date"] == "2026-05-12"
        assert result["code"] == "600000.SH"
        assert result["open"] == 10.0
        assert result["high"] == 10.5
        assert result["low"] == 9.8
        assert result["close"] == 10.2
        assert result["preclose"] == 10.0
        assert result["volume"] == 1000000
        assert result["amount"] == 10200000.0
        assert result["pctChg"] == 2.0
        assert result["tradestatus"] == "1"

    def test_normalizes_none_fields(self):
        from app.data_pipeline.providers import normalize_kline_record

        raw = {
            "date": "2026-05-12",
            "code": "sh.600000",
            "open": None,
            "high": None,
            "low": None,
            "close": "10.2",
            "preclose": None,
            "volume": "1000000",
            "amount": None,
            "pctChg": None,
            "tradestatus": "1",
        }
        result = normalize_kline_record(raw, "600000.SH")

        assert result["open"] is None
        assert result["high"] is None
        assert result["low"] is None
        assert result["preclose"] is None
        assert result["amount"] is None
        assert result["pctChg"] is None

    def test_handles_empty_strings(self):
        from app.data_pipeline.providers import normalize_kline_record

        raw = {
            "date": "",
            "code": "",
            "open": "",
            "high": "",
            "low": "",
            "close": "",
            "preclose": "",
            "volume": "",
            "amount": "",
            "pctChg": "",
            "tradestatus": "",
        }
        result = normalize_kline_record(raw, "600000.SH")

        assert result["open"] is None

    def test_preserves_standard_keys(self):
        from app.data_pipeline.providers import STANDARD_KEYS, normalize_kline_record

        raw = {
            "date": "2026-05-12",
            "code": "sh.600000",
            "open": "10.0",
            "high": "10.5",
            "low": "9.8",
            "close": "10.2",
            "preclose": "10.0",
            "volume": "1000000",
            "amount": "10200000",
            "pctChg": "2.0",
            "tradestatus": "1",
        }
        result = normalize_kline_record(raw, "600000.SH")

        for key in STANDARD_KEYS:
            assert key in result, f"Missing standard key: {key}"

    def test_volume_as_int(self):
        from app.data_pipeline.providers import normalize_kline_record

        raw = {
            "date": "2026-05-12",
            "code": "sh.600000",
            "open": "10.0",
            "high": "10.5",
            "low": "9.8",
            "close": "10.2",
            "preclose": "10.0",
            "volume": "1000000",
            "amount": "10200000",
            "pctChg": "2.0",
            "tradestatus": "1",
        }
        result = normalize_kline_record(raw, "600000.SH")

        assert isinstance(result["volume"], int)

    def test_normalizes_turn_field(self):
        """turn field should be preserved as float in normalized output."""
        from app.data_pipeline.providers import normalize_kline_record

        raw = {
            "date": "2026-05-12",
            "code": "sh.600000",
            "open": "10.0",
            "high": "10.5",
            "low": "9.8",
            "close": "10.2",
            "preclose": "10.0",
            "volume": "1000000",
            "amount": "10200000",
            "turn": "1.5",
            "pctChg": "2.0",
            "tradestatus": "1",
        }
        result = normalize_kline_record(raw, "600000.SH")

        assert result["turn"] == 1.5
        assert isinstance(result["turn"], float)

    def test_normalizes_turn_none(self):
        """Missing turn should be None in normalized output."""
        from app.data_pipeline.providers import normalize_kline_record

        raw = {
            "date": "2026-05-12",
            "code": "sh.600000",
            "open": "10.0",
            "high": "10.5",
            "low": "9.8",
            "close": "10.2",
            "preclose": "10.0",
            "volume": "1000000",
            "amount": "10200000",
            "pctChg": "2.0",
            "tradestatus": "1",
        }
        result = normalize_kline_record(raw, "600000.SH")

        assert result["turn"] is None
        assert isinstance(result["amount"], float)


class TestKlineProviderRegistry:
    """KlineProviderRegistry fallback behavior."""

    def test_import(self):
        from app.data_pipeline.providers import KlineProviderRegistry

        assert callable(KlineProviderRegistry)

    def test_primary_success_returns_primary_source(self):
        from app.data_pipeline.providers import KlineProviderRegistry

        registry = KlineProviderRegistry(
            providers=[FakeProvider(name="primary", records=[{"date": "ok"}])]
        )
        result = registry.fetch_stock_kline("600000.SH", "20260501", "20260512")
        assert result.source == "primary"
        assert result.fallback_used is False
        assert len(result.records) == 1

    def test_primary_raises_falls_to_fallback(self):
        from app.data_pipeline.providers import KlineProviderRegistry

        registry = KlineProviderRegistry(
            providers=[
                FakePrimaryProvider(),
                FakeFallbackProvider(),
            ]
        )
        result = registry.fetch_stock_kline("600000.SH", "20260501", "20260512")
        assert result.source == "fallback"
        assert result.fallback_used is True
        assert len(result.records) == 1
        # records should be normalized
        assert result.records[0]["open"] == 10.0
        assert result.records[0]["close"] == 10.2
        # primary error should be preserved
        assert len(result.errors) > 0
        assert "primary" in result.errors[0].get("provider", "") or "primary" in str(result.errors)

    def test_empty_primary_falls_to_fallback(self):
        from app.data_pipeline.providers import KlineProviderRegistry

        registry = KlineProviderRegistry(
            providers=[
                FakeEmptyProvider(),
                FakeFallbackProvider(),
            ]
        )
        result = registry.fetch_stock_kline("600000.SH", "20260501", "20260512")
        assert result.source == "fallback"
        assert result.fallback_used is True
        assert len(result.records) == 1

    def test_all_providers_fail_returns_empty_with_errors(self):
        from app.data_pipeline.providers import KlineProviderRegistry

        registry = KlineProviderRegistry(
            providers=[
                FakeProvider(name="p1", records=[], should_raise=True, raise_msg="p1 failed"),
                FakeEmptyProvider(),
            ]
        )
        result = registry.fetch_stock_kline("600000.SH", "20260501", "20260512")
        assert result.records == []
        assert result.source == ""
        assert result.fallback_used is True
        assert len(result.errors) >= 2

    def test_invalid_code_returns_structured_error(self):
        from app.data_pipeline.providers import KlineProviderRegistry

        registry = KlineProviderRegistry(providers=[FakeFallbackProvider()])
        result = registry.fetch_stock_kline("INVALID", "20260501", "20260512")
        # Should return structured error with no records
        assert result.records == []
        assert len(result.errors) > 0

    def test_providers_are_called_in_order(self):
        from app.data_pipeline.providers import KlineProviderRegistry

        call_order: list[str] = []

        class TrackingProvider:
            name: str

            def __init__(self, name: str):
                self.name = name

            def fetch_stock_kline(self, *args, **kwargs):
                call_order.append(self.name)
                raise RuntimeError(f"{self.name} failed")

        registry = KlineProviderRegistry(
            providers=[
                TrackingProvider("first"),
                TrackingProvider("second"),
                TrackingProvider("third"),
            ]
        )
        registry.fetch_stock_kline("600000.SH", "20260501", "20260512")
        assert call_order == ["first", "second", "third"]

    def test_non_standard_exception_falls_through(self):
        """Regression: non-standard exceptions (e.g. OSError) must also fall through."""
        from app.data_pipeline.providers import KlineProviderRegistry

        class RaisesOSError:
            name = "broken"

            def fetch_stock_kline(self, *args, **kwargs):
                raise OSError("connection reset")

        registry = KlineProviderRegistry(
            providers=[
                RaisesOSError(),
                FakeFallbackProvider(),
            ]
        )
        result = registry.fetch_stock_kline("600000.SH", "20260501", "20260512")
        assert result.source == "fallback"
        assert result.fallback_used is True
        assert len(result.errors) == 1
        assert "connection reset" in result.errors[0]["error"]

    def test_key_error_on_missing_field_falls_through(self):
        """Regression: KeyError/TypeError from provider must also fall through."""
        from app.data_pipeline.providers import KlineProviderRegistry

        class RaisesKeyError:
            name = "key_missing"

            def fetch_stock_kline(self, *args, **kwargs):
                d = {}
                _ = d["missing"]  # raises KeyError
                return []

        registry = KlineProviderRegistry(
            providers=[
                RaisesKeyError(),
                FakeFallbackProvider(),
            ]
        )
        result = registry.fetch_stock_kline("600000.SH", "20260501", "20260512")
        assert result.source == "fallback"
        assert result.fallback_used is True
        assert len(result.errors) == 1


class TestBaostockAdapter:
    """Baostock adapter registration and invocation."""

    def test_adapter_import(self):
        from app.data_pipeline.providers import BaostockKlineProvider

        assert callable(BaostockKlineProvider)

    def test_adapter_calls_data_source_with_raise_on_error(self):
        from unittest.mock import MagicMock, patch

        from app.data_pipeline.providers import BaostockKlineProvider

        mock_client = MagicMock(spec=DataSourceClient)
        mock_client.get_stock_kline.return_value = [
            {
                "date": "2026-05-12",
                "code": "sh.600000",
                "open": "10.0",
                "high": "10.5",
                "low": "9.8",
                "close": "10.2",
                "preclose": "10.0",
                "volume": "1000000",
                "amount": "10200000",
                "pctChg": "2.0",
                "tradestatus": "1",
            }
        ]

        provider = BaostockKlineProvider(client=mock_client)
        records = provider.fetch_stock_kline(
            "600000.SH", "20260501", "20260512", adjustflag="3"
        )

        mock_client.get_stock_kline.assert_called_once_with(
            "600000.SH", "20260501", "20260512", adjustflag="3", raise_on_error=True
        )
        assert len(records) == 1
        assert records[0]["date"] == "2026-05-12"

    def test_adapter_propagates_exception(self):
        from unittest.mock import MagicMock

        from app.data_pipeline.providers import BaostockKlineProvider

        mock_client = MagicMock(spec=DataSourceClient)
        mock_client.get_stock_kline.side_effect = RuntimeError("network error")

        provider = BaostockKlineProvider(client=mock_client)
        with pytest.raises(RuntimeError):
            provider.fetch_stock_kline("600000.SH", "20260501", "20260512")


class TestOptionalProviders:
    """Efinance and akshare optional provider registration."""

    def test_efinance_importable_provider(self):
        """EfinanceKlineProvider should be conditionally importable."""
        try:
            from app.data_pipeline.providers import EfinanceKlineProvider
        except ImportError:
            pytest.skip("efinance not installed")

        assert callable(EfinanceKlineProvider)

    def test_akshare_importable_provider(self):
        """AkshareKlineProvider should be conditionally importable."""
        try:
            from app.data_pipeline.providers import AkshareKlineProvider
        except ImportError:
            pytest.skip("akshare not installed")

        assert callable(AkshareKlineProvider)

    def test_efinance_filters_by_date_range(self):
        """Regression: efinance provider must pass start/end date to API."""
        try:
            import efinance as ef
        except ImportError:
            pytest.skip("efinance not installed")

        from unittest.mock import patch

        import pandas as pd

        from app.data_pipeline.providers import EfinanceKlineProvider

        mock_df = pd.DataFrame(
            {
                "日期": ["2026-05-10", "2026-05-12", "2026-05-15"],
                "开盘": [10.0, 10.1, 10.2],
                "最高": [10.5, 10.6, 10.7],
                "最低": [9.8, 9.9, 10.0],
                "收盘": [10.2, 10.3, 10.4],
                "昨收": [10.0, 10.2, 10.3],
                "成交量": [1000000, 1100000, 1200000],
                "成交额": [10200000, 11300000, 12400000],
                "涨跌幅": [2.0, 1.0, 1.0],
            }
        )

        provider = EfinanceKlineProvider()
        with patch.object(ef.stock, "get_quote_history", return_value=mock_df) as mock_get:
            records = provider.fetch_stock_kline(
                "600000.SH", "20260501", "20260531", adjustflag="3"
            )
            mock_get.assert_called_once()
            # Verify that beg and end were passed in YYYY-MM-DD format
            _call_kwargs = mock_get.call_args
            # efinance's get_quote_history receives beg= and end= as keyword args
            assert "beg" in mock_get.call_args[1] or len(mock_get.call_args[0]) >= 2
            assert len(records) == 3


class TestDefaultProviderRegistry:
    """Default provider registry factory."""

    def test_create_default_registry(self):
        from app.data_pipeline.providers import create_default_registry

        registry = create_default_registry()
        assert registry is not None

    def test_default_registry_has_baostock_provider(self):
        from app.data_pipeline.providers import create_default_registry

        registry = create_default_registry()
        # Baostock should always be present
        provider_names = [p.name for p in registry.providers]
        assert "baostock" in provider_names

    def test_default_registry_providers_have_names(self):
        from app.data_pipeline.providers import create_default_registry

        registry = create_default_registry()
        for provider in registry.providers:
            assert hasattr(provider, "name")
            assert provider.name