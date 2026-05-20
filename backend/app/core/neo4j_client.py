"""
Neo4j 连接池管理

- 同步驱动（neo4j），FastAPI 路由中用 run_in_executor 包装
- 线程池执行器由 FastAPI/Starlette 自动提供，无需手动创建
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Generator

from neo4j import GraphDatabase, Driver
from neo4j.graph import Node

from app.config import settings

logger = logging.getLogger(__name__)

# ── 连接池 ──────────────────────────────────────────────

_driver: Driver | None = None
_async_driver: "AsyncDriver | None" = None


def get_driver() -> Driver:
    """全局 Driver 单例（线程安全，neo4j 驱动本身是线程安全的）"""
    global _driver
    if _driver is None:
        _driver = GraphDatabase.driver(
            settings.neo4j_url,
            auth=(settings.neo4j_user, settings.neo4j_password),
            max_connection_pool_size=50,
            connection_acquisition_timeout=30,
        )
        logger.info("Neo4j 驱动已初始化: %s", settings.neo4j_url)
    return _driver


def close_driver() -> None:
    """关闭同步驱动（可从同步上下文调用）"""
    global _driver
    if _driver is not None:
        _driver.close()
        _driver = None
        logger.info("Neo4j 驱动已关闭")


async def close_async_driver() -> None:
    """关闭异步驱动（必须在异步上下文中调用，如 FastAPI lifespan）"""
    global _async_driver
    if _async_driver is not None:
        await _async_driver.close()
        _async_driver = None
        logger.info("Neo4j 异步驱动已关闭")


# ── 异步驱动单例 ──────────────────────────────────────────────

from neo4j import AsyncGraphDatabase as _AGD

if TYPE_CHECKING:
    from neo4j import AsyncDriver


async def get_async_driver() -> "AsyncDriver":
    """全局异步 Driver 单例（所有异步 Neo4j 操作必须用此方法）"""
    global _async_driver
    if _async_driver is None:
        _async_driver = _AGD.driver(
            settings.neo4j_url,
            auth=(settings.neo4j_user, settings.neo4j_password),
            max_connection_pool_size=50,
            connection_acquisition_timeout=30,
        )
        logger.info("Neo4j 异步驱动已初始化: %s", settings.neo4j_url)
    return _async_driver


# ── 会话上下文管理器 ────────────────────────────────────

@contextmanager
def session(
    database: str | None = None,
) -> Generator[Any, None, None]:
    """
    同步会话上下文管理器（用于 FastAPI 同步路由或脚本）。

    用法：
        with session() as s:
            s.run("MATCH (n) RETURN count(n) AS cnt")
    """
    driver = get_driver()
    ses = driver.session(database=database)
    try:
        yield ses
    finally:
        ses.close()


@contextmanager
def write_transaction() -> Generator[Any, None, None]:
    """
    显式写事务上下文管理器。

    - begin_transaction() 后所有操作在同一个事务中
    - 正常退出：自动 commit
    - 异常退出：自动 rollback

    用法：
        with write_transaction() as tx:
            tx.run("CREATE (n:Test {v: 1})")
            tx.run("CREATE (m:Test2 {v: 2})")
        # 退出时自动 commit
    """
    driver = get_driver()
    ses = driver.session()
    tx = ses.begin_transaction()
    try:
        yield tx
        tx.commit()
    except Exception:
        logger.exception("[Neo4j] Transaction failed, rolling back")
        tx.rollback()
        raise
    finally:
        tx.close()
        ses.close()


# ── 便捷执行方法 ─────────────────────────────────────────

def run(cypher: str, params: dict | None = None) -> list[dict[str, Any]]:
    """
    执行只读查询，返回列表。
    用法：run("MATCH (n) RETURN n.name", {"name": "foo"})
    """
    with session() as s:
        result = s.run(cypher, params or {})
        return [dict(r) for r in result]


def run_write(cypher: str, params: dict | None = None) -> list[dict[str, Any]]:
    """执行写查询（使用显式事务，自动 commit）"""
    with write_transaction() as tx:
        result = tx.run(cypher, params or {})
        return [dict(r) for r in result]


def run_single(cypher: str, params: dict | None = None) -> dict[str, Any] | None:
    """执行只读查询，返回单条，无结果时返回 None"""
    rows = run(cypher, params)
    return rows[0] if rows else None


def run_write_single(cypher: str, params: dict | None = None) -> dict[str, Any] | None:
    """执行写查询，返回单条"""
    rows = run_write(cypher, params)
    return rows[0] if rows else None


# ── 健康检查 ─────────────────────────────────────────────

def health_check() -> bool:
    """Neo4j 健康检查"""
    try:
        with session() as s:
            r = s.run("RETURN 1 AS n").single()
            return r is not None and r["n"] == 1
    except Exception as e:
        logger.error("Neo4j 健康检查失败: %s", e)
        return False
