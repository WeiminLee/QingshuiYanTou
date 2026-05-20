"""
AuditLogger - 结构化日志记录器

提供统一的日志记录接口，支持:
- JSON 格式输出
- PostgreSQL 持久化
- trace_id 和 task_id 追踪
"""
import json
import logging
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import engine

logger = logging.getLogger(__name__)

# Context variables for request tracing
_current_trace_id: ContextVar[Optional[str]] = ContextVar("trace_id", default=None)
_current_task_id: ContextVar[Optional[str]] = ContextVar("task_id", default=None)


def generate_trace_id() -> str:
    """生成新的 trace_id"""
    return str(uuid.uuid4())


def generate_task_id() -> str:
    """生成新的 task_id"""
    return str(uuid.uuid4())


def get_trace_id() -> Optional[str]:
    """获取当前 trace_id"""
    return _current_trace_id.get()


def set_trace_id(trace_id: str) -> None:
    """设置当前 trace_id"""
    _current_trace_id.set(trace_id)


def get_task_id() -> Optional[str]:
    """获取当前 task_id"""
    return _current_task_id.get()


def set_task_id(task_id: str) -> None:
    """设置当前 task_id"""
    _current_task_id.set(task_id)


class AuditLogger:
    """
    结构化日志记录器

    用法:
        logger = AuditLogger("data_pipeline")
        logger.info("fetcher", "K线同步完成", duration_ms=1234)
        logger.error("scheduler", "任务执行失败", error=str(e))
    """

    def __init__(self, service: str):
        """
        初始化 AuditLogger

        Args:
            service: 服务名称 (如 "data_pipeline", "reasoning")
        """
        self.service = service
        self._console_logger = logging.getLogger(f"audit.{service}")

    def _log(
        self,
        level: str,
        module: str,
        message: str,
        duration_ms: Optional[int] = None,
        **kwargs: Any,
    ) -> None:
        """
        内部日志记录方法

        Args:
            level: 日志级别 (DEBUG, INFO, WARNING, ERROR, CRITICAL)
            module: 模块名称
            message: 日志消息
            duration_ms: 执行耗时 (毫秒)
            **kwargs: 额外的元数据
        """
        timestamp = datetime.now(timezone.utc)
        trace_id = get_trace_id()
        task_id = get_task_id()

        log_entry = {
            "timestamp": timestamp.isoformat(),
            "level": level,
            "service": self.service,
            "module": module,
            "message": message,
            "trace_id": trace_id,
            "task_id": task_id,
            "duration_ms": duration_ms,
            "extra_data": kwargs if kwargs else None,
        }

        # 输出到控制台 (JSON 格式)
        self._console_logger.log(
            getattr(logging, level),
            json.dumps(log_entry, ensure_ascii=False),
        )

    def debug(self, module: str, message: str, **kwargs: Any) -> None:
        self._log("DEBUG", module, message, **kwargs)

    def info(self, module: str, message: str, **kwargs: Any) -> None:
        self._log("INFO", module, message, **kwargs)

    def warning(self, module: str, message: str, **kwargs: Any) -> None:
        self._log("WARNING", module, message, **kwargs)

    def error(self, module: str, message: str, **kwargs: Any) -> None:
        self._log("ERROR", module, message, **kwargs)

    def critical(self, module: str, message: str, **kwargs: Any) -> None:
        self._log("CRITICAL", module, message, **kwargs)


class AsyncAuditLogger(AuditLogger):
    """
    异步版本日志记录器

    除了控制台输出外，还支持写入 PostgreSQL
    """

    async def log_to_db(
        self,
        level: str,
        module: str,
        message: str,
        duration_ms: Optional[int] = None,
        **kwargs: Any,
    ) -> None:
        """
        将日志写入 PostgreSQL

        Args:
            level: 日志级别
            module: 模块名称
            message: 日志消息
            duration_ms: 执行耗时
            **kwargs: 额外的元数据
        """
        timestamp = datetime.now(timezone.utc)
        trace_id = get_trace_id()
        task_id = get_task_id()

        try:
            async with engine.connect() as conn:
                await conn.execute(
                    text("""
                        INSERT INTO logs (timestamp, level, service, module, message, trace_id, task_id, duration_ms, extra_data)
                        VALUES (:timestamp, :level, :service, :module, :message, :trace_id, :task_id, :duration_ms, :extra_data::jsonb)
                    """),
                    {
                        "timestamp": timestamp,
                        "level": level,
                        "service": self.service,
                        "module": module,
                        "message": message,
                        "trace_id": trace_id,
                        "task_id": task_id,
                        "duration_ms": duration_ms,
                        "extra_data": json.dumps(kwargs) if kwargs else None,
                    },
                )
                await conn.commit()
        except Exception as e:
            # 日志写入失败不影响主流程
            self._console_logger.error(f"Failed to write log to database: {e}")

    async def ainfo(self, module: str, message: str, **kwargs: Any) -> None:
        """异步记录 INFO 级别日志"""
        await self.log_to_db("INFO", module, message, **kwargs)

    async def aerror(self, module: str, message: str, **kwargs: Any) -> None:
        """异步记录 ERROR 级别日志"""
        await self.log_to_db("ERROR", module, message, **kwargs)


# 全局日志实例缓存
_loggers: dict[str, AuditLogger] = {}


def get_logger(service: str) -> AuditLogger:
    """
    获取指定服务的 AuditLogger 实例

    Args:
        service: 服务名称

    Returns:
        AuditLogger 实例
    """
    if service not in _loggers:
        _loggers[service] = AuditLogger(service)
    return _loggers[service]
