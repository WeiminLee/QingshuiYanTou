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


def _extract_db_name(url: str) -> str:
    """从 MongoDB URL 中提取数据库名（忽略查询参数）"""
    match = re.search(r"://[^/]+/([^/?]+)", url)
    return match.group(1) if match else "qingshui"


def get_mongo_client() -> AsyncIOMotorClient:
    """获取 MongoDB 客户端（单例）"""
    global _client
    if _client is None:
        _client = AsyncIOMotorClient(settings.mongodb_url)
        logger.info("MongoDB 客户端已初始化")
    return _client


def get_mongo_db() -> AsyncIOMotorDatabase:
    """获取默认数据库实例"""
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
