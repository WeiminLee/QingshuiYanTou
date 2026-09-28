"""
数据库连接工具
"""

# 创建异步引擎
# 连接池需覆盖远端 worker 并发（link/upsert 每个请求占一条连接）：
# 原 10+10 在 48 并发下会 "QueuePool limit ... connection timed out"，
# 导致 link/upsert 超时失败。默认提到 30+20，可用环境变量按机器规格调整。
import os as _os

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

from app.config import settings

engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    pool_pre_ping=True,
    pool_size=int(_os.getenv("DB_POOL_SIZE", "30")),
    max_overflow=int(_os.getenv("DB_MAX_OVERFLOW", "20")),
    pool_timeout=float(_os.getenv("DB_POOL_TIMEOUT", "30")),
    pool_recycle=300,
)

# 创建会话工厂（默认池）。注意：对外暴露为 callable，见下方 async_session()。
_default_sessionmaker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# ── 隔离会话（工具跨 loop 调用用）────────────────────────────────────────
# 背景：agent 在自身 event loop 里调用 sync 工具（run_in_executor），工具内部
# 用 asyncio.run 另起 loop；而全局 engine 的连接池绑定主 loop → asyncpg 报
# 'got Future attached to a different loop'。修法：工具执行窗口内把 contextvar
# 指向一个 NullPool 临时 engine，async_session() 优先使用它（与主 loop 零共享）。
import contextvars as _contextvars

_isolated_engine: _contextvars.ContextVar = _contextvars.ContextVar(
    "qingshui_isolated_engine", default=None
)


def async_session():
    """返回一个 AsyncSession（async context manager）。

    行为等同原 async_sessionmaker()。若当前执行窗口注入了隔离 engine
    （工具跨 loop 调用，见 _async_runner），则使用隔离 engine 的 sessionmaker。
    """
    e = _isolated_engine.get()
    maker = (
        _default_sessionmaker
        if e is None
        else async_sessionmaker(e, class_=AsyncSession, expire_on_commit=False)
    )
    return maker()


def use_isolated_engine(engine_obj):
    return _isolated_engine.set(engine_obj)


def reset_isolated_engine(token) -> None:
    _isolated_engine.reset(token)


def make_nullpool_engine(url: str | None = None):
    """创建一个 NullPool 一次性 engine（连接用后即闭，不跨 loop 复用）。"""
    from sqlalchemy.pool import NullPool

    return create_async_engine(url or settings.database_url, poolclass=NullPool)

# 基础模型
Base = declarative_base()


async def get_db():
    """获取数据库会话"""
    async with async_session() as session:
        yield session
