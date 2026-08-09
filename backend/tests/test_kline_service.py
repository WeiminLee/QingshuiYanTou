"""Tests for KlineService weekly/monthly aggregation.

Task 4: 实现周线/月线查询聚合
"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest


def _make_kline_row(
    trade_date: str,
    open_p: float = 10.0,
    high: float = 10.5,
    low: float = 9.8,
    close: float = 10.2,
    volume: float = 1000000,
    amount: float = 10200000,
    pct_chg: float = 2.0,
    turnover_rate: float | None = 1.5,
):
    return {
        "ts_code": "600000.SH",
        "trade_date": trade_date,
        "open": open_p,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "amount": amount,
        "pct_chg": pct_chg,
        "turnover_rate": turnover_rate,
    }


class _MockConn:
    """Mock async connection that returns predefined rows."""

    def __init__(self, rows: list[dict]):
        self._rows = rows

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def execute(self, *args, **kwargs):
        result = MagicMock()
        result.fetchall.return_value = [
            (
                r["ts_code"],
                date.fromisoformat(r["trade_date"]),
                r["open"],
                r["high"],
                r["low"],
                r["close"],
                r["volume"],
                r["amount"],
                r["pct_chg"],
                r.get("turnover_rate"),
            )
            for r in self._rows
        ]
        return result


class TestKlineServiceAggregation:
    """KlineService weekly/monthly aggregation tests."""

    def test_import(self):
        from app.data_pipeline.services.kline_service import KlineService

        assert callable(KlineService)

    @pytest.mark.asyncio
    async def test_daily_remains_unchanged(self):
        """frequency='d' returns daily rows as-is."""
        import app.data_pipeline.services.kline_service as ks_mod
        from app.data_pipeline.services.kline_service import KlineService

        svc = KlineService()
        rows = [_make_kline_row("2026-05-12")]
        mock_engine = MagicMock()
        mock_engine.connect.return_value = _MockConn(rows)

        with patch.object(ks_mod, "engine", mock_engine):
            result = await svc.get_stock_kline("600000.SH", "20260501", "20260531", frequency="d")

        assert len(result) == 1
        assert result[0]["trade_date"] == "20260512"

    @pytest.mark.asyncio
    async def test_weekly_aggregation(self):
        """frequency='w' groups by ISO trading week."""
        import app.data_pipeline.services.kline_service as ks_mod
        from app.data_pipeline.services.kline_service import KlineService

        svc = KlineService()
        rows = [
            _make_kline_row("2026-05-04", open_p=10.0, high=10.5, low=9.8, close=10.2, volume=1_000_000, amount=10_000_000, pct_chg=2.0),
            _make_kline_row("2026-05-05", open_p=10.3, high=10.8, low=10.1, close=10.6, volume=1_100_000, amount=11_000_000, pct_chg=3.0),
            _make_kline_row("2026-05-11", open_p=10.4, high=10.7, low=10.0, close=10.5, volume=900_000, amount=9_000_000, pct_chg=1.0),
        ]
        mock_engine = MagicMock()
        mock_engine.connect.return_value = _MockConn(rows)

        with patch.object(ks_mod, "engine", mock_engine):
            result = await svc.get_stock_kline("600000.SH", "20260501", "20260531", frequency="w")

        assert len(result) == 2

        w1 = result[0]
        assert w1["trade_date"] == "20260504"
        assert w1["open"] == 10.0
        assert w1["high"] == 10.8
        assert w1["low"] == 9.8
        assert w1["close"] == 10.6
        assert w1["volume"] == 2_100_000
        assert w1["amount"] == 21_000_000
        assert w1["turnover_rate"] is not None

        w2 = result[1]
        assert w2["trade_date"] == "20260511"
        assert w2["open"] == 10.4
        assert w2["close"] == 10.5
        assert w2["volume"] == 900_000

    @pytest.mark.asyncio
    async def test_monthly_aggregation(self):
        """frequency='m' groups by YYYY-MM."""
        import app.data_pipeline.services.kline_service as ks_mod
        from app.data_pipeline.services.kline_service import KlineService

        svc = KlineService()
        rows = [
            _make_kline_row("2026-05-04", open_p=10.0, high=10.5, low=9.8, close=10.2, volume=1_000_000, amount=10_000_000, pct_chg=2.0),
            _make_kline_row("2026-05-12", open_p=10.3, high=10.8, low=10.1, close=10.6, volume=1_100_000, amount=11_000_000, pct_chg=3.0),
            _make_kline_row("2026-06-01", open_p=10.4, high=10.7, low=10.0, close=10.5, volume=900_000, amount=9_000_000, pct_chg=1.0),
        ]
        mock_engine = MagicMock()
        mock_engine.connect.return_value = _MockConn(rows)

        with patch.object(ks_mod, "engine", mock_engine):
            result = await svc.get_stock_kline("600000.SH", "20260501", "20260630", frequency="m")

        assert len(result) == 2

        m1 = result[0]
        assert m1["trade_date"] == "20260504"
        assert m1["open"] == 10.0
        assert m1["high"] == 10.8
        assert m1["low"] == 9.8
        assert m1["close"] == 10.6
        assert m1["volume"] == 2_100_000
        assert m1["amount"] == 21_000_000

        m2 = result[1]
        assert m2["trade_date"] == "20260601"
        assert m2["open"] == 10.4
        assert m2["close"] == 10.5

    @pytest.mark.asyncio
    async def test_invalid_frequency_returns_empty(self):
        """Invalid frequency returns [] with a warning log."""
        from app.data_pipeline.services.kline_service import KlineService

        svc = KlineService()
        result = await svc.get_stock_kline("600000.SH", "20260501", "20260531", frequency="x")
        assert result == []

    @pytest.mark.asyncio
    async def test_empty_daily_returns_empty_for_weekly(self):
        """When daily query returns empty, weekly also returns empty."""
        import app.data_pipeline.services.kline_service as ks_mod
        from app.data_pipeline.services.kline_service import KlineService

        svc = KlineService()
        mock_engine = MagicMock()
        mock_engine.connect.return_value = _MockConn([])

        with patch.object(ks_mod, "engine", mock_engine):
            result = await svc.get_stock_kline("600000.SH", "20260501", "20260531", frequency="w")

        assert result == []

    @pytest.mark.asyncio
    async def test_weekly_volume_and_amount_are_summed(self):
        """volume/amount should be summed across the week."""
        import app.data_pipeline.services.kline_service as ks_mod
        from app.data_pipeline.services.kline_service import KlineService

        svc = KlineService()
        rows = [
            _make_kline_row("2026-05-04", volume=500_000, amount=5_000_000),
            _make_kline_row("2026-05-05", volume=700_000, amount=7_000_000),
            _make_kline_row("2026-05-06", volume=300_000, amount=3_000_000),
        ]
        mock_engine = MagicMock()
        mock_engine.connect.return_value = _MockConn(rows)

        with patch.object(ks_mod, "engine", mock_engine):
            result = await svc.get_stock_kline("600000.SH", "20260501", "20260531", frequency="w")

        assert len(result) == 1
        assert result[0]["volume"] == 1_500_000
        assert result[0]["amount"] == 15_000_000