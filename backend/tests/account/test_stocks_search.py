"""stocks_search 复用 Tushare stock_basic 表做模糊匹配"""
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.models import Stock
from app.account import stocks_search


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Stock.__table__.create)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        session.add_all([
            Stock(ts_code="600519.SH", symbol="600519", name="贵州茅台", industry="白酒"),
            Stock(ts_code="300750.SZ", symbol="300750", name="宁德时代", industry="电池"),
            Stock(ts_code="000001.SZ", symbol="000001", name="平安银行", industry="银行"),
        ])
        await session.commit()
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_search_by_name(db_session):
    items = await stocks_search.search(db_session, "茅台", limit=10)
    assert any(i.ts_code == "600519.SH" for i in items)


@pytest.mark.asyncio
async def test_search_by_ts_code_prefix(db_session):
    items = await stocks_search.search(db_session, "300750", limit=10)
    assert any(i.ts_code == "300750.SZ" for i in items)


@pytest.mark.asyncio
async def test_search_limit(db_session):
    items = await stocks_search.search(db_session, "", limit=2)
    assert len(items) <= 2
