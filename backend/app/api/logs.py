"""
日志查询 API 路由

提供日志查询接口:
- GET /api/v1/logs/ - 查询日志列表
- GET /api/v1/logs/stats - 获取统计信息
- GET /api/v1/logs/export - 导出日志
"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from fastapi.params import Optional as FastAPIOptional

from app.logging.log_service import LogService
from app.logging.audit_export import AuditExportService

router = APIRouter(tags=["logs"])


@router.get("/")
async def query_logs(
    start_time: FastAPIOptional[datetime] = Query(None, description="开始时间 (ISO格式)"),
    end_time: FastAPIOptional[datetime] = Query(None, description="结束时间 (ISO格式)"),
    service: FastAPIOptional[str] = Query(None, description="服务名称过滤"),
    level: FastAPIOptional[str] = Query(None, description="日志级别过滤 (DEBUG/INFO/WARNING/ERROR/CRITICAL)"),
    module: FastAPIOptional[str] = Query(None, description="模块名称过滤"),
    trace_id: FastAPIOptional[str] = Query(None, description="trace_id 过滤"),
    task_id: FastAPIOptional[str] = Query(None, description="task_id 过滤"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(50, ge=1, le=100, description="每页大小"),
) -> dict:
    """
    查询日志列表

    支持按时间、服务、模块、级别、trace_id 等条件过滤
    """
    service_obj = LogService()
    result = await service_obj.query_logs(
        start_time=start_time,
        end_time=end_time,
        service=service,
        level=level,
        module=module,
        trace_id=trace_id,
        task_id=task_id,
        page=page,
        page_size=page_size,
    )
    return result


@router.get("/stats")
async def get_stats(
    start_time: FastAPIOptional[datetime] = Query(None, description="开始时间 (ISO格式)"),
    end_time: FastAPIOptional[datetime] = Query(None, description="结束时间 (ISO格式)"),
    service: FastAPIOptional[str] = Query(None, description="服务名称过滤"),
) -> dict:
    """
    获取日志统计信息

    返回:
    - total: 总日志数
    - error_count: 错误日志数
    - error_rate: 错误率 (%)
    - by_level: 按级别统计
    - by_service: 按服务统计
    """
    service_obj = LogService()
    result = await service_obj.get_stats(
        start_time=start_time,
        end_time=end_time,
        service=service,
    )
    return result


@router.get("/export")
async def export_logs(
    format: str = Query("csv", regex="^(csv|json)$", description="导出格式 (csv/json)"),
    start_time: FastAPIOptional[datetime] = Query(None, description="开始时间 (ISO格式)"),
    end_time: FastAPIOptional[datetime] = Query(None, description="结束时间 (ISO格式)"),
    service: FastAPIOptional[str] = Query(None, description="服务名称过滤"),
    level: FastAPIOptional[str] = Query(None, description="日志级别过滤"),
) -> StreamingResponse:
    """
    导出日志

    支持 CSV 和 JSON 格式导出。
    返回文件下载。
    """
    export_service = AuditExportService()

    if format == "csv":
        return await export_service.export_logs_csv(
            start_time=start_time,
            end_time=end_time,
            service=service,
            level=level,
        )
    else:
        return await export_service.export_logs_json(
            start_time=start_time,
            end_time=end_time,
            service=service,
            level=level,
        )
