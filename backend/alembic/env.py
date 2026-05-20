import asyncio
import os
from logging.config import fileConfig

from alembic import context

# 加载 .env 环境变量
from dotenv import load_dotenv
load_dotenv()

# 导入模型和数据库 Base
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from app.core.database import Base
from app.models.models import (  # noqa: E402, F401
    Stock, DailyData, Watchlist,
    MonitorRule, Alert, AnalysisReport,
)

# Alembic Config 对象
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 模型元数据，用于 autogenerate
target_metadata = Base.metadata

# 从环境变量读取数据库 URL
database_url = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://qingshui:qingshui123@localhost:5432/qingshui"
)
config.set_main_option("sqlalchemy.url", database_url)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    """在已有连接上执行迁移"""
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Run migrations in 'online' mode（异步）."""
    from sqlalchemy.ext.asyncio import create_async_engine

    async_engine = create_async_engine(database_url, echo=False)

    async with async_engine.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await async_engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
