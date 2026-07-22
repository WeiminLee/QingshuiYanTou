import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.signals.api import router
from app.utils.auth import verify_api_key


def test_build_concept_board_fixture_records_generates_kg_secondary_signal():
    from app.signals.fixtures import build_concept_board_fixture_records

    signals, propagations = build_concept_board_fixture_records("optical_module")

    assert signals
    assert propagations
    assert any(signal["signal_type"] == "mass_production" for signal in signals)
    assert any(prop["target_name"] == "光芯片" for prop in propagations)
    assert propagations[0]["metadata"]["path_hops"] <= 2
    assert propagations[0]["metadata"]["path_nodes"]


@pytest.mark.asyncio
async def test_seed_fixture_endpoint_returns_stats(monkeypatch):
    async def fake_seed(session, concept: str):
        return {
            "concept": concept,
            "signals_upserted": 2,
            "propagations_upserted": 3,
        }

    monkeypatch.setattr("app.signals.api.seed_concept_board_fixture", fake_seed)

    app = FastAPI()
    app.dependency_overrides[verify_api_key] = lambda: "test-api-key"
    app.include_router(router, prefix="/api/v1/signals")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post(
            "/api/v1/signals/fixtures/concept-board",
            params={"concept": "optical_module"},
            headers={"x-api-key": "test-api-key"},
        )

    assert res.status_code == 200
    assert res.json() == {
        "concept": "optical_module",
        "signals_upserted": 2,
        "propagations_upserted": 3,
    }
