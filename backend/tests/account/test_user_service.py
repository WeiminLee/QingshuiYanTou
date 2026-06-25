"""user_service: yaml 同步、活跃用户查询"""
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.models import User
from app.account.services import user_service


@pytest_asyncio.fixture
async def db_session():
    """内存 SQLite 异步 session（仅 user_service 内部 get_active 用得到）"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(User.__table__.create)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_sync_creates_new_users(db_session, temp_users_yaml):
    n = await user_service.sync_from_yaml(db_session, temp_users_yaml)
    assert n == 2
    rows = (await db_session.execute(User.__table__.select())).fetchall()
    ids = {r[0] for r in rows}
    assert ids == {"alice", "bob"}


@pytest.mark.asyncio
async def test_sync_updates_display_name(db_session, temp_users_yaml):
    await user_service.sync_from_yaml(db_session, temp_users_yaml)
    temp_users_yaml.write_text(
        "users:\n  - user_id: alice\n    display_name: Alice2\n  - user_id: bob\n    display_name: Bob\n",
        encoding="utf-8",
    )
    await user_service.sync_from_yaml(db_session, temp_users_yaml)
    u = await user_service.get_active(db_session, "alice")
    assert u.display_name == "Alice2"
    assert u.is_active is True


@pytest.mark.asyncio
async def test_sync_deactivates_removed_user(db_session, temp_users_yaml):
    await user_service.sync_from_yaml(db_session, temp_users_yaml)
    temp_users_yaml.write_text(
        "users:\n  - user_id: alice\n    display_name: Alice\n",
        encoding="utf-8",
    )
    await user_service.sync_from_yaml(db_session, temp_users_yaml)
    u = await user_service.get_active(db_session, "bob")
    assert u is None


@pytest.mark.asyncio
async def test_get_active_returns_none_for_missing(db_session):
    u = await user_service.get_active(db_session, "ghost")
    assert u is None
