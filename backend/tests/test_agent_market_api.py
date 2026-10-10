from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import settings
from app.knowledge.api.agent_market import router as agent_market_router

HEADERS = {"X-API-Key": "test-key"}


@pytest.fixture(autouse=True)
def _api_key(monkeypatch):
    monkeypatch.setattr(settings, "knowledge_api_key", "test-key", raising=False)
    monkeypatch.setattr(settings, "api_key", "", raising=False)


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(agent_market_router)
    return TestClient(app)


def test_kline_requires_ts_code_and_auth(client):
    r = client.get("/api/v1/knowledge/market/kline", params={"ts_code": "300308.SZ"})
    assert r.status_code in (401, 403)


def test_kline_ok(client):
    rows = [
        {
            "ts_code": "300308.SZ",
            "trade_date": "20261009",
            "open": 10.0,
            "high": 11.0,
            "low": 9.5,
            "close": 10.5,
            "volume": 1000,
            "pct_chg": 1.2,
        }
    ]
    with patch(
        "app.knowledge.api.agent_market.get_kline_service",
    ) as mock_svc:
        mock_svc.return_value.get_stock_kline = AsyncMock(return_value=rows)
        r = client.get(
            "/api/v1/knowledge/market/kline",
            headers=HEADERS,
            params={"ts_code": "300308.SZ", "start_date": "20260101", "end_date": "20261009", "freq": "D"},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["ts_code"] == "300308.SZ"
    assert body["count"] == 1
    assert body["items"][0]["close"] == 10.5
    assert "text" in body


def test_stock_profile_ok(client):
    profile = {
        "ts_code": "300308.SZ",
        "main_business": "光模块",
        "business_scope": "通信设备",
    }
    with patch(
        "app.knowledge.api.agent_market.get_stock_service",
    ) as mock_svc:
        mock_svc.return_value.get_stock_profile = AsyncMock(return_value=profile)
        r = client.get(
            "/api/v1/knowledge/market/stock_profile",
            headers=HEADERS,
            params={"ts_code": "300308.SZ"},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["ts_code"] == "300308.SZ"
    assert body["main_business"] == "光模块"
    assert "text" in body
    assert "光模块" in body["text"]


def test_market_http_has_no_langchain():
    import ast
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "app/knowledge/api/agent_market.py"
    tree = ast.parse(src.read_text())
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    joined = " ".join(imports)
    assert "langchain" not in joined
    assert "reasoning.tools" not in joined
