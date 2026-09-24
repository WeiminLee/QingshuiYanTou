"""
数据库连接工具
"""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

from app.config import settings

# 创建异步引擎
# 连接池需覆盖远端 worker 并发（link/upsert 每个请求占一条连接）：
# 原 10+10 在 48 并发下会 "QueuePool limit ... connection timed out"，
# 导致 link/upsert 超时失败。默认提到 30+20，可用环境变量按机器规格调整。
import os as _os

engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    pool_pre_ping=True,
    pool_size=int(_os.getenv("DB_POOL_SIZE", "30")),
    max_overflow=int(_os.getenv("DB_MAX_OVERFLOW", "20")),
    pool_timeout=float(_os.getenv("DB_POOL_TIMEOUT", "30")),
    pool_recycle=300,
)

# 创建会话工厂
async_session = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# 基础模型
Base = declarative_base()


async def get_db():
    """获取数据库会话"""
    async with async_session() as session:
        yield session
