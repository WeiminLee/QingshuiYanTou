from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.readiness.schemas import ReadinessSource, ReadinessSummary, SourceStatus, ThresholdKind


class FakeReadinessService:
    async def get_all(self, now=None):
        return ReadinessSummary(
            as_of=datetime(2026, 7, 21, 9, 0, tzinfo=UTC).isoformat(),
            overall_status="fresh",
            summary="全部关键数据源处于日级可靠窗口内。",
            sources=[
                ReadinessSource(
                    source="kline",
                    display_name="K-line",
                    status=SourceStatus.FRESH,
                    latest_data_date="2026-07-20",
                    latest_success_at=None,
                    lag_days=1,
                    threshold_days=1,
                    threshold_kind=ThresholdKind.TRADING_DAY,
                    recommendation="数据处于日级可靠窗口内。",
                )
            ],
        )

    async def get_source(self, source: str, now=None):
        if source != "kline":
            return None
        return (await self.get_all(now)).sources[0]


@pytest.mark.asyncio
async def test_readiness_summary_endpoint(monkeypatch):
    import app.readiness.api as api

    monkeypatch.setattr(api, "DataReadinessService", lambda: FakeReadinessService())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/readiness")

    assert resp.status_code == 200
    body = resp.json()
    assert body["overall_status"] == "fresh"
    assert body["sources"][0]["source"] == "kline"


@pytest.mark.asyncio
async def test_readiness_source_endpoint(monkeypatch):
    import app.readiness.api as api

    monkeypatch.setattr(api, "DataReadinessService", lambda: FakeReadinessService())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/readiness/kline")

    assert resp.status_code == 200
    assert resp.json()["source"] == "kline"


@pytest.mark.asyncio
async def test_readiness_unknown_source_404(monkeypatch):
    import app.readiness.api as api

    monkeypatch.setattr(api, "DataReadinessService", lambda: FakeReadinessService())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/readiness/unknown")

    assert resp.status_code == 404
    assert resp.json()["detail"] == "unknown readiness source: unknown"
