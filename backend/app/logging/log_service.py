"""
LogService - 日志查询服务

提供日志查询接口，支持:
- 按时间范围查询
- 按服务/模块过滤
- 按日志级别过滤
- 按 trace_id 追踪
- 分页查询
"""
import json
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import engine


class LogService:
    """日志查询服务"""

    def __init__(self, session: Optional[AsyncSession] = None):
        self.session = session

    async def query_logs(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        service: Optional[str] = None,
        level: Optional[str] = None,
        module: Optional[str] = None,
        trace_id: Optional[str] = None,
        task_id: Optional[str] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> dict[str, Any]:
        """
        查询日志

        Args:
            start_time: 开始时间
            end_time: 结束时间
            service: 服务名称过滤
            level: 日志级别过滤
            module: 模块名称过滤
            trace_id: trace_id 过滤
            task_id: task_id 过滤
            page: 页码 (从1开始)
            page_size: 每页大小

        Returns:
            包含 items, total, page, page_size 的字典
        """
        conditions = []
        params = {}

        if start_time:
            conditions.append("timestamp >= :start_time")
            params["start_time"] = start_time

        if end_time:
            conditions.append("timestamp <= :end_time")
            params["end_time"] = end_time

        if service:
            conditions.append("service = :service")
            params["service"] = service

        if level:
            conditions.append("level = :level")
            params["level"] = level

        if module:
            conditions.append("module = :module")
            params["module"] = module

        if trace_id:
            conditions.append("trace_id = :trace_id")
            params["trace_id"] = trace_id

        if task_id:
            conditions.append("task_id = :task_id")
            params["task_id"] = task_id

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        # 计算总数
        count_sql = f"SELECT COUNT(*) FROM logs WHERE {where_clause}"
        async with engine.connect() as conn:
            result = await conn.execute(text(count_sql), params)
            total = result.scalar()

        # 分页查询
        offset = (page - 1) * page_size
        params["limit"] = page_size
        params["offset"] = offset

        query_sql = f"""
            SELECT id, timestamp, level, service, module, message,
                   trace_id, task_id, duration_ms, extra_data, created_at
            FROM logs
            WHERE {where_clause}
            ORDER BY timestamp DESC
            LIMIT :limit OFFSET :offset
        """

        async with engine.connect() as conn:
            result = await conn.execute(text(query_sql), params)
            rows = result.fetchall()

        items = []
        for row in rows:
            item = {
                "id": row[0],
                "timestamp": row[1].isoformat() if row[1] else None,
                "level": row[2],
                "service": row[3],
                "module": row[4],
                "message": row[5],
                "trace_id": str(row[6]) if row[6] else None,
                "task_id": str(row[7]) if row[7] else None,
                "duration_ms": row[8],
                "extra_data": json.loads(row[9]) if row[9] else None,
                "created_at": row[10].isoformat() if row[10] else None,
            }
            items.append(item)

        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    async def get_stats(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        service: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        获取日志统计信息

        Args:
            start_time: 开始时间
            end_time: 结束时间
            service: 服务名称过滤

        Returns:
            统计信息字典
        """
        conditions = []
        params = {}

        if start_time:
            conditions.append("timestamp >= :start_time")
            params["start_time"] = start_time

        if end_time:
            conditions.append("timestamp <= :end_time")
            params["end_time"] = end_time

        if service:
            conditions.append("service = :service")
            params["service"] = service

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        # 按级别统计
        level_sql = f"""
            SELECT level, COUNT(*) as count
            FROM logs
            WHERE {where_clause}
            GROUP BY level
            ORDER BY count DESC
        """
        async with engine.connect() as conn:
            result = await conn.execute(text(level_sql), params)
            level_counts = [{"level": row[0], "count": row[1]} for row in result.fetchall()]

        # 按服务统计
        service_sql = f"""
            SELECT service, COUNT(*) as count
            FROM logs
            WHERE {where_clause}
            GROUP BY service
            ORDER BY count DESC
        """
        async with engine.connect() as conn:
            result = await conn.execute(text(service_sql), params)
            service_counts = [{"service": row[0], "count": row[1]} for row in result.fetchall()]

        # 计算错误率
        total_sql = f"SELECT COUNT(*) FROM logs WHERE {where_clause}"
        error_sql = f"SELECT COUNT(*) FROM logs WHERE {where_clause} AND level IN ('ERROR', 'CRITICAL')"

        async with engine.connect() as conn:
            total_result = await conn.execute(text(total_sql), params)
            total = total_result.scalar()

            error_result = await conn.execute(text(error_sql), params)
            error_count = error_result.scalar()

        error_rate = (error_count / total * 100) if total > 0 else 0

        return {
            "total": total,
            "error_count": error_count,
            "error_rate": round(error_rate, 2),
            "by_level": level_counts,
            "by_service": service_counts,
        }
