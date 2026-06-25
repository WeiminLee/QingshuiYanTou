"""集成测：/api/v1/auth/* 和 /api/v1/users"""
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.main as main_mod
from app.models.models import User
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
            ])
            await s.commit()
        yield c
    fastapi_app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_login_success_and_whoami(client):
    r = await client.post("/api/v1/auth/login", json={"password": "test-master-pass-1234"})
    assert r.status_code == 200
    assert "master_token" in r.cookies
    body = r.json()
    assert body["ok"] is True
    assert {u["user_id"] for u in body["users"]} == {"alice", "bob"}

    r = await client.get("/api/v1/auth/whoami")
    assert r.status_code == 200
    body = r.json()
    assert body["user"] is None
    assert {u["user_id"] for u in body["users"]} == {"alice", "bob"}


@pytest.mark.asyncio
async def test_login_wrong_password(client):
    r = await client.post("/api/v1/auth/login", json={"password": "wrong"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_switch_user_and_whoami(client):
    await client.post("/api/v1/auth/login", json={"password": "test-master-pass-1234"})
    r = await client.post("/api/v1/auth/switch-user", json={"user_id": "alice"})
    assert r.status_code == 200
    body = r.json()
    assert body["current_user"]["user_id"] == "alice"

    r = await client.get("/api/v1/auth/whoami")
    body = r.json()
    assert body["user"]["user_id"] == "alice"


@pytest.mark.asyncio
async def test_users_list_requires_login(client):
    r = await client.get("/api/v1/users")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_logout_clears_cookie(client):
    await client.post("/api/v1/auth/login", json={"password": "test-master-pass-1234"})
    r = await client.post("/api/v1/auth/logout")
    assert r.status_code == 200
    r = await client.get("/api/v1/auth/whoami")
    assert r.status_code == 401
