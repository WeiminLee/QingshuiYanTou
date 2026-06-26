"""portfolio_service: 持仓增删查 + 跨用户隔离"""

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.account.services import portfolio_service
from app.models.models import PortfolioPosition, User


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(User.__table__.create)
        await conn.run_sync(PortfolioPosition.__table__.create)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        session.add_all(
            [
                User(user_id="alice", display_name="Alice"),
                User(user_id="bob", display_name="Bob"),
            ]
        )
        await session.commit()
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_add_and_list(db_session):
    p = await portfolio_service.add(db_session, "alice", "600519.SH", "贵州茅台")
    assert p.ts_code == "600519.SH"
    rows = await portfolio_service.list_for_user(db_session, "alice")
    assert [r.ts_code for r in rows] == ["600519.SH"]


@pytest.mark.asyncio
async def test_add_duplicate_raises(db_session):
    await portfolio_service.add(db_session, "alice", "600519.SH", "贵州茅台")
    with pytest.raises(Exception):  # IntegrityError in SQLite
        await portfolio_service.add(db_session, "alice", "600519.SH", "贵州茅台")
    await db_session.rollback()


@pytest.mark.asyncio
async def test_list_isolates_users(db_session):
    await portfolio_service.add(db_session, "alice", "600519.SH", "贵州茅台")
    await portfolio_service.add(db_session, "bob", "300750.SZ", "宁德时代")
    a_rows = await portfolio_service.list_for_user(db_session, "alice")
    b_rows = await portfolio_service.list_for_user(db_session, "bob")
    assert [r.ts_code for r in a_rows] == ["600519.SH"]
    assert [r.ts_code for r in b_rows] == ["300750.SZ"]


@pytest.mark.asyncio
async def test_remove_own(db_session):
    await portfolio_service.add(db_session, "alice", "600519.SH", "贵州茅台")
    ok = await portfolio_service.remove(db_session, "alice", "600519.SH")
    assert ok is True
    rows = await portfolio_service.list_for_user(db_session, "alice")
    assert rows == []


@pytest.mark.asyncio
async def test_remove_other_user_returns_false(db_session):
    await portfolio_service.add(db_session, "alice", "600519.SH", "贵州茅台")
    ok = await portfolio_service.remove(db_session, "bob", "600519.SH")
    assert ok is False
    rows = await portfolio_service.list_for_user(db_session, "alice")
    assert [r.ts_code for r in rows] == ["600519.SH"]


@pytest.mark.asyncio
async def test_remove_nonexistent_returns_false(db_session):
    ok = await portfolio_service.remove(db_session, "alice", "999999.SH")
    assert ok is False
