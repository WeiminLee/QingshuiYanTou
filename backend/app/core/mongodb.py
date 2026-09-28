"""
MongoDB 连接工具（异步，motor）
"""

import logging
import re

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.config import settings

logger = logging.getLogger(__name__)

_client: AsyncIOMotorClient | None = None
_db: AsyncIOMotorDatabase | None = None

# 隔离 MongoDB 客户端（工具跨 loop 调用用，见 reasoning/tools/_async_runner）。
# motor 客户端的内部连接绑定创建它的 event loop，agent 主 loop 创建的单例在
# 工具线程的新 loop 里复用时同样报 'attached to a different loop'。
import contextvars as _contextvars

_isolated_db: _contextvars.ContextVar = _contextvars.ContextVar(
    "qingshui_isolated_mongo", default=None
)


def make_isolated_mongo_db() -> tuple[AsyncIOMotorClient, AsyncIOMotorDatabase]:
    """创建一次性 motor 客户端（工具窗口内使用，调用方负责 close）。"""
    client = AsyncIOMotorClient(
        settings.mongodb_url,
        serverSelectionTimeoutMS=2000,
        connectTimeoutMS=2000,
    )
    return client, client[_extract_db_name(settings.mongodb_url)]


def use_isolated_mongo(db) -> object:
    return _isolated_db.set(db)


def reset_isolated_mongo(token) -> None:
    _isolated_db.reset(token)


def _extract_db_name(url: str) -> str:
    """从 MongoDB URL 中提取数据库名（忽略查询参数）"""
    match = re.search(r"://[^/]+/([^/?]+)", url)
    return match.group(1) if match else "qingshui"


def get_mongo_client() -> AsyncIOMotorClient:
    """获取 MongoDB 客户端（单例）"""
    global _client
    if _client is None:
        # serverSelectionTimeoutMS 调短：无 MongoDB 时快速失败并降级，
        # 避免 agent memory prefetch 卡满默认 30s 超时。
        _client = AsyncIOMotorClient(
            settings.mongodb_url,
            serverSelectionTimeoutMS=2000,
            connectTimeoutMS=2000,
        )
        logger.info("MongoDB 客户端已初始化")
    return _client


def get_mongo_db() -> AsyncIOMotorDatabase:
    """获取默认数据库实例（隔离窗口内返回临时 client 的库）。"""
    isolated = _isolated_db.get()
    if isolated is not None:
        return isolated
    global _db
    if _db is None:
        _db = get_mongo_client()[_extract_db_name(settings.mongodb_url)]
    return _db


async def close_mongo_client() -> None:
    """关闭连接（应用关闭时调用）"""
    global _client, _db
    if _client:
        _client.close()
        _client = None
        _db = None
        logger.info("MongoDB 客户端已关闭")
