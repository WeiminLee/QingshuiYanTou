"""
AuditExportService - 审计日志导出服务

支持 CSV 和 JSON 格式导出
"""

import json
from collections.abc import AsyncIterator
from datetime import datetime

from fastapi.responses import StreamingResponse

from app.logging.log_service import LogService


class AuditExportService:
    """审计日志导出服务"""

    def __init__(self):
        self.log_service = LogService()

    async def export_logs_csv(
        self,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        service: str | None = None,
        level: str | None = None,
    ) -> StreamingResponse:
        """
        导出日志为 CSV 格式

        Returns:
            StreamingResponse
        """
        filename = f"logs_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

        async def generate() -> AsyncIterator[bytes]:
            yield b"id,timestamp,level,service,module,message,trace_id,task_id,duration_ms,extra_data\n"

            page = 1
            page_size = 1000

            while True:
                result = await self.log_service.query_logs(
                    start_time=start_time,
                    end_time=end_time,
                    service=service,
                    level=level,
                    page=page,
                    page_size=page_size,
                )

                for item in result["items"]:
                    row = [
                        str(item["id"]),
                        item["timestamp"] or "",
                        item["level"] or "",
                        item["service"] or "",
                        item["module"] or "",
                        (item["message"] or "").replace('"', '""'),
                        item["trace_id"] or "",
                        item["task_id"] or "",
                        str(item["duration_ms"]) if item["duration_ms"] else "",
                        json.dumps(item["extra_data"]) if item["extra_data"] else "",
                    ]
                    yield ",".join(f'"{v}"' for v in row).encode() + b"\n"

                if page * page_size >= result["total"]:
                    break
                page += 1

        return StreamingResponse(
            generate(),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

    async def export_logs_json(
        self,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        service: str | None = None,
        level: str | None = None,
    ) -> StreamingResponse:
        """
        导出日志为 JSON 格式

        Returns:
            StreamingResponse
        """
        filename = f"logs_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

        async def generate() -> AsyncIterator[bytes]:
            yield b'{"logs": [\n'

            page = 1
            page_size = 1000
            first = True

            while True:
                result = await self.log_service.query_logs(
                    start_time=start_time,
                    end_time=end_time,
                    service=service,
                    level=level,
                    page=page,
                    page_size=page_size,
                )

                for item in result["items"]:
                    if not first:
                        yield b",\n"
                    first = False
                    yield json.dumps(item, ensure_ascii=False).encode()

                if page * page_size >= result["total"]:
                    break
                page += 1

            yield b'\n],"export_time": "' + datetime.now().isoformat().encode() + b'"}'

        return StreamingResponse(
            generate(),
            media_type="application/json",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
