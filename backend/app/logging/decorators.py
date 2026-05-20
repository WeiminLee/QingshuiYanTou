"""
日志装饰器 - 用于自动注入 trace_id 和 task_id

用法:
    @with_trace_id()
    async def my_function():
        ...

    @with_task_log("fetcher")
    async def fetch_data():
        ...
"""
import functools
import logging
import time
import uuid
from typing import Any, Callable, Optional

from app.logging.logger import (
    generate_task_id,
    generate_trace_id,
    get_logger,
    get_task_id,
    get_trace_id,
    set_task_id,
    set_trace_id,
)

logger = logging.getLogger(__name__)


def with_trace_id(func: Callable[..., Any]) -> Callable[..., Any]:
    """
    装饰器: 为函数自动生成并管理 trace_id

    用法:
        @with_trace_id()
        async def my_request_handler():
            trace_id = get_trace_id()  # 在函数内获取 trace_id
            ...
    """
    @functools.wraps(func)
    async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
        trace_id = generate_trace_id()
        old_trace_id = get_trace_id()
        set_trace_id(trace_id)
        try:
            result = await func(*args, **kwargs)
            return result
        finally:
            set_trace_id(old_trace_id)

    @functools.wraps(func)
    def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
        trace_id = generate_trace_id()
        old_trace_id = get_trace_id()
        set_trace_id(trace_id)
        try:
            result = func(*args, **kwargs)
            return result
        finally:
            set_trace_id(old_trace_id)

    import asyncio
    if asyncio.iscoroutinefunction(func):
        return async_wrapper
    return sync_wrapper


def with_task_log(
    module: str,
    service: str = "data_pipeline",
    log_result: bool = True,
) -> Callable[..., Any]:
    """
    装饰器: 自动记录任务开始/结束日志

    Args:
        module: 模块名称 (如 "fetcher", "scheduler")
        service: 服务名称 (默认 "data_pipeline")
        log_result: 是否记录结果和耗时 (默认 True)

    用法:
        @with_task_log("fetcher")
        async def fetch_kline():
            ...

        @with_task_log("scheduler", service="reasoning")
        async def run_task():
            ...
    """
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            task_id = generate_task_id()
            old_task_id = get_task_id()
            set_task_id(task_id)

            audit_logger = get_logger(service)
            start_time = time.time()

            # 记录任务开始
            audit_logger.info(module, f"任务开始: {func.__name__}", task_id=task_id)

            try:
                result = await func(*args, **kwargs)

                if log_result:
                    duration_ms = int((time.time() - start_time) * 1000)
                    audit_logger.info(
                        module,
                        f"任务完成: {func.__name__}",
                        task_id=task_id,
                        duration_ms=duration_ms,
                    )

                return result

            except Exception as e:
                if log_result:
                    duration_ms = int((time.time() - start_time) * 1000)
                    audit_logger.error(
                        module,
                        f"任务失败: {func.__name__}",
                        task_id=task_id,
                        duration_ms=duration_ms,
                        error=str(e),
                    )
                raise
            finally:
                set_task_id(old_task_id)

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            task_id = generate_task_id()
            old_task_id = get_task_id()
            set_task_id(task_id)

            audit_logger = get_logger(service)
            start_time = time.time()

            audit_logger.info(module, f"任务开始: {func.__name__}", task_id=task_id)

            try:
                result = func(*args, **kwargs)

                if log_result:
                    duration_ms = int((time.time() - start_time) * 1000)
                    audit_logger.info(
                        module,
                        f"任务完成: {func.__name__}",
                        task_id=task_id,
                        duration_ms=duration_ms,
                    )

                return result

            except Exception as e:
                if log_result:
                    duration_ms = int((time.time() - start_time) * 1000)
                    audit_logger.error(
                        module,
                        f"任务失败: {func.__name__}",
                        task_id=task_id,
                        duration_ms=duration_ms,
                        error=str(e),
                    )
                raise
            finally:
                set_task_id(old_task_id)

        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator
