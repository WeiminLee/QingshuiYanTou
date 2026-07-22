import os
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("MONGODB_URL", "mongodb://localhost:27017/test")
os.environ.setdefault("LLM_API_KEY", "test-key")
os.environ.setdefault("NEO4J_PASSWORD", "test-password")
os.environ.setdefault("MASTER_PASSWORD", "test-master-pass-1234")

from app.reasoning.context.schemas import UserSnapshotDTO
from app.signals.api import router


def _test_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/signals")
    return app


@pytest.mark.asyncio
async def test_list_signals_returns_items(monkeypatch):
    async def fake_list_signals(*args, **kwargs):
        return [
            {
                "signal_id": "SIG:abc",
                "title": "800G 光模块规模量产",
                "summary": "量产确认 -> 订单兑现 -> 供应链需求增强",
                "source_type": "announcement",
                "published_at": datetime(2026, 7, 13, tzinfo=UTC),
                "subject_name": "光模块",
                "signal_type": "mass_production",
                "polarity": "positive",
                "value_score": 92,
                "confidence": 0.92,
                "portfolio_hits": ["中际旭创"],
            }
        ], 1

    monkeypatch.setattr("app.signals.api.list_signals", fake_list_signals)

    async with AsyncClient(transport=ASGITransport(app=_test_app()), base_url="http://test") as client:
        res = await client.get("/api/v1/signals")

    assert res.status_code == 200
    assert res.json()["items"][0]["signal_id"] == "SIG:abc"


@pytest.mark.asyncio
async def test_get_signal_detail_returns_propagations(monkeypatch):
    async def fake_get_signal_detail(*args, **kwargs):
        return {
            "signal_id": "SIG:abc",
            "title": "800G 光模块规模量产",
            "summary": "量产确认 -> 订单兑现 -> 供应链需求增强",
            "source_type": "announcement",
            "source_title": "公告标题",
            "source_url": None,
            "published_at": datetime(2026, 7, 13, tzinfo=UTC),
            "subject_name": "光模块",
            "subject_type": "product",
            "signal_type": "mass_production",
            "polarity": "positive",
            "strength": 88,
            "confidence": 0.92,
            "value_score": 92,
            "evidence_excerpt": "相关产品进入规模量产",
            "status": "new",
            "portfolio_hits": ["中际旭创"],
            "propagations": [
                {
                    "target_name": "光芯片",
                    "target_type": "concept",
                    "relation_path": "量产确认 -> 订单兑现概率提升 -> 供应链需求增强",
                    "direction": "beneficiary",
                    "impact_horizon": "short",
                    "confidence": 0.7,
                    "reasoning": "高速光模块放量可能提升上游需求",
                    "signal_path": {
                        "nodes": ["中际旭创", "800G光模块", "光芯片"],
                        "edges": [
                            {
                                "src": "中际旭创",
                                "rel_type": "RELATES",
                                "tgt": "800G光模块",
                                "weight": 0.9,
                                "text": "生产 800G 光模块",
                            },
                            {
                                "src": "800G光模块",
                                "rel_type": "RELATES",
                                "tgt": "光芯片",
                                "weight": 0.8,
                                "text": "上游依赖光芯片",
                            },
                        ],
                        "hops": 2,
                        "confidence": 0.7,
                    },
                }
            ],
        }

    monkeypatch.setattr("app.signals.api.get_signal_detail", fake_get_signal_detail)

    async with AsyncClient(transport=ASGITransport(app=_test_app()), base_url="http://test") as client:
        res = await client.get("/api/v1/signals/SIG:abc")

    assert res.status_code == 200
    assert res.json()["propagations"][0]["target_name"] == "光芯片"
    assert res.json()["propagations"][0]["signal_path"]["nodes"] == ["中际旭创", "800G光模块", "光芯片"]


@pytest.mark.asyncio
async def test_get_signal_detail_accepts_context_dto_fields(monkeypatch):
    async def fake_get_signal_detail(*args, **kwargs):
        return {
            "schema_version": "signal.context.v1",
            "signal_id": "SIG:abc",
            "title": "800G 光模块规模量产",
            "summary": "量产确认",
            "source_type": "announcement",
            "source_title": "公告标题",
            "source_url": None,
            "published_at": datetime(2026, 7, 13, tzinfo=UTC),
            "subject_name": "光模块",
            "subject_type": "product",
            "signal_type": "mass_production",
            "polarity": "positive",
            "strength": 88,
            "confidence": 0.92,
            "value_score": 92,
            "evidence_excerpt": "相关产品进入规模量产",
            "status": "new",
            "portfolio_hits": ["中际旭创"],
            "source": {"type": "announcement", "id": "EV:1", "title": "公告标题", "url": None},
            "primary_signal": {"subject_name": "光模块", "signal_type": "mass_production"},
            "memory": {
                "schema_version": "signal.memory.v1",
                "signal_id": "SIG:abc",
                "lifecycle_status": "active",
                "user_status": "new",
            },
            "user_hits": {"portfolio": ["中际旭创"], "watchlist": [], "preferences": ["光模块"]},
            "propagations": [],
        }

    monkeypatch.setattr("app.signals.api.get_signal_detail", fake_get_signal_detail)

    async with AsyncClient(transport=ASGITransport(app=_test_app()), base_url="http://test") as client:
        res = await client.get("/api/v1/signals/SIG:abc")

    assert res.status_code == 200
    body = res.json()
    assert body["schema_version"] == "signal.context.v1"
    assert body["user_hits"]["preferences"] == ["光模块"]
    assert body["memory"]["lifecycle_status"] == "active"


@pytest.mark.asyncio
async def test_get_signal_detail_resolves_user_hits_from_user_id(monkeypatch):
    async def fake_get_signal_detail(*args, **kwargs):
        return {
            "schema_version": "signal.context.v1",
            "signal_id": "SIG:abc",
            "title": "800G 光模块规模量产",
            "summary": "量产确认",
            "source_type": "announcement",
            "source_title": "公告标题",
            "source_url": None,
            "published_at": datetime(2026, 7, 13, tzinfo=UTC),
            "subject_name": "中际旭创",
            "subject_type": "company",
            "signal_type": "mass_production",
            "polarity": "positive",
            "strength": 88,
            "confidence": 0.92,
            "value_score": 92,
            "evidence_excerpt": "相关产品进入规模量产",
            "status": "new",
            "portfolio_hits": ["旧持仓"],
            "memory": {
                "schema_version": "signal.memory.v1",
                "signal_id": "SIG:abc",
                "lifecycle_status": "active",
                "user_status": "new",
            },
            "user_hits": {"portfolio": [], "watchlist": [], "preferences": []},
            "propagations": [
                {
                    "target_name": "光芯片",
                    "target_type": "product",
                    "relation_path": "中际旭创 -> 光模块 -> 光芯片",
                    "direction": "beneficiary",
                    "impact_horizon": "short",
                    "confidence": 0.8,
                    "reasoning": "上游需求增强",
                    "signal_path": {
                        "nodes": ["中际旭创", "光模块", "光芯片"],
                        "edges": [],
                        "hops": 2,
                        "confidence": 0.8,
                    },
                }
            ],
        }

    async def fake_snapshot(user_id):
        assert user_id == "lwm"
        return UserSnapshotDTO(
            user_id=user_id,
            portfolio=[{"name": "中际旭创", "ts_code": "300308.SZ"}],
            preferences=[{"subject": "光模块", "stance": "关注"}],
        ), []

    monkeypatch.setattr("app.signals.api.get_signal_detail", fake_get_signal_detail)
    monkeypatch.setattr("app.reasoning.context.user_snapshot.build_user_snapshot", fake_snapshot)

    async with AsyncClient(transport=ASGITransport(app=_test_app()), base_url="http://test") as client:
        res = await client.get("/api/v1/signals/SIG:abc?user_id=lwm")

    assert res.status_code == 200
    body = res.json()
    assert body["portfolio_hits"] == ["旧持仓"]
    assert body["user_hits"]["portfolio"] == ["中际旭创"]
    assert body["user_hits"]["preferences"] == ["光模块"]
