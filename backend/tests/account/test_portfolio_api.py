"""集成测：/api/v1/portfolio 和 /api/v1/stocks/search"""
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.main as main_mod
from app.models.models import PortfolioPosition, Stock, User
from app.core import database as db_mod

fastapi_app = main_mod.app


@pytest_asyncio.fixture
async def client(monkeypatch):
    monkeypatch.setenv("MASTER_PASSWORD", "test-master-pass-1234")
    from importlib import reload
    import app.config
    reload(app.config)

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(User.__table__.create)
        await conn.run_sync(PortfolioPosition.__table__.create)
        await conn.run_sync(Stock.__table__.create)
    db_mod.engine = engine
    db_mod.async_session = async_sessionmaker(engine, expire_on_commit=False)

    async def _override_get_db():
        async with db_mod.async_session() as s:
            yield s
    fastapi_app.dependency_overrides[db_mod.get_db] = _override_get_db

    transport = ASGITransport(app=fastapi_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        async with db_mod.async_session() as s:
            s.add_all([
                User(user_id="alice", display_name="Alice"),
                User(user_id="bob", display_name="Bob"),
                Stock(ts_code="600519.SH", symbol="600519", name="贵州茅台", industry="白酒"),
                Stock(ts_code="300750.SZ", symbol="300750", name="宁德时代", industry="电池"),
            ])
            await s.commit()
        yield c
    fastapi_app.dependency_overrides.clear()


async def _login_and_switch(client, user_id: str) -> None:
    r = await client.post("/api/v1/auth/login", json={"password": "test-master-pass-1234"})
    assert r.status_code == 200
    r = await client.post("/api/v1/auth/switch-user", json={"user_id": user_id})
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_portfolio_lifecycle(client):
    await _login_and_switch(client, "alice")
    r = await client.get("/api/v1/account/portfolio")
    assert r.status_code == 200
    assert r.json()["positions"] == []

    r = await client.post("/api/v1/account/portfolio", json={"ts_code": "600519.SH"})
    assert r.status_code == 200
    assert r.json()["position"]["ts_code"] == "600519.SH"

    r = await client.get("/api/v1/account/portfolio")
    assert len(r.json()["positions"]) == 1

    r = await client.delete("/api/v1/account/portfolio/600519.SH")
    assert r.status_code == 200
    r = await client.get("/api/v1/account/portfolio")
    assert r.json()["positions"] == []


@pytest.mark.asyncio
async def test_portfolio_duplicate_returns_409(client):
    await _login_and_switch(client, "alice")
    await client.post("/api/v1/account/portfolio", json={"ts_code": "600519.SH"})
    r = await client.post("/api/v1/account/portfolio", json={"ts_code": "600519.SH"})
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_portfolio_invalid_ts_code_returns_422(client):
    await _login_and_switch(client, "alice")
    r = await client.post("/api/v1/account/portfolio", json={"ts_code": "badcode"})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_portfolio_isolates_users(client):
    await _login_and_switch(client, "alice")
    await client.post("/api/v1/account/portfolio", json={"ts_code": "600519.SH"})

    await _login_and_switch(client, "bob")
    r = await client.get("/api/v1/account/portfolio")
    assert r.json()["positions"] == []
    r = await client.delete("/api/v1/account/portfolio/600519.SH")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_stocks_search(client):
    await _login_and_switch(client, "alice")
    r = await client.get("/api/v1/account/stocks/search", params={"q": "茅台"})
    assert r.status_code == 200
    items = r.json()["items"]
    assert any(i["ts_code"] == "600519.SH" for i in items)
