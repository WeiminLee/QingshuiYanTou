"""
ReportService - 研报/公告/互动易查询服务

从本地 PostgreSQL 查询研报和公告数据，供 Agent 工具调用。
互动易复用 announcements 表，靠 announcement_type 前缀 'irm:' 标识。
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text

from app.core.database import engine

logger = logging.getLogger(__name__)


def _parse_yyyymmdd(value: str | None) -> str | None:
    if not value or len(value) < 8 or not value[:8].isdigit():
        return None
    return f"{value[:4]}-{value[4:6]}-{value[6:8]}"


class ReportService:
    """研报/公告/互动易查询服务"""

    async def search_reports(
        self,
        ts_code: str | None = None,
        keyword: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        sql = """
        SELECT trade_date, ts_code, title, inst_csname, author
        FROM research_report_meta
        WHERE 1=1
        """
        params: dict[str, Any] = {}

        if ts_code:
            sql += " AND ts_code = :ts_code"
            params["ts_code"] = ts_code
        if keyword:
            sql += " AND title LIKE :keyword"
            params["keyword"] = f"%{keyword}%"
        if sd := _parse_yyyymmdd(start_date):
            sql += " AND trade_date >= :start_date"
            params["start_date"] = sd
        if ed := _parse_yyyymmdd(end_date):
            sql += " AND trade_date <= :end_date"
            params["end_date"] = ed

        sql += " ORDER BY trade_date DESC LIMIT :limit"
        params["limit"] = limit

        try:
            async with engine.connect() as conn:
                result = await conn.execute(text(sql), params)
                rows = result.fetchall()
            return [
                {
                    "trade_date": row[0].strftime("%Y%m%d") if row[0] else "",
                    "ts_code": row[1] or "",
                    "title": row[2] or "",
                    "institution": row[3] or "",
                    "author": row[4] or "",
                }
                for row in rows
            ]
        except Exception as exc:
            logger.warning("查询研报失败: %s", exc)
            return []

    async def search_announcements(
        self,
        ts_code: str | None = None,
        keyword: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """查询正式公告（排除互动易）。"""
        sql = """
        SELECT ann_date, ts_code, title, announcement_type, type
        FROM announcements
        WHERE (announcement_type IS NULL OR announcement_type NOT LIKE 'irm:%%')
        """
        params: dict[str, Any] = {}

        if ts_code:
            sql += " AND ts_code = :ts_code"
            params["ts_code"] = ts_code
        if keyword:
            sql += " AND title LIKE :keyword"
            params["keyword"] = f"%{keyword}%"
        if sd := _parse_yyyymmdd(start_date):
            sql += " AND ann_date >= :start_date"
            params["start_date"] = sd
        if ed := _parse_yyyymmdd(end_date):
            sql += " AND ann_date <= :end_date"
            params["end_date"] = ed

        sql += " ORDER BY ann_date DESC LIMIT :limit"
        params["limit"] = limit

        try:
            async with engine.connect() as conn:
                result = await conn.execute(text(sql), params)
                rows = result.fetchall()
            return [
                {
                    "ann_date": row[0].strftime("%Y%m%d") if row[0] else "",
                    "ts_code": row[1] or "",
                    "title": row[2] or "",
                    "type": row[3] or "",
                    "summary": row[4] or "",
                }
                for row in rows
            ]
        except Exception as exc:
            logger.warning("查询公告失败: %s", exc)
            return []

    async def search_irm(
        self,
        ts_code: str | None = None,
        keyword: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """查询互动易 Q&A（announcements 表中 announcement_type LIKE 'irm:%'）。"""
        sql = """
        SELECT ann_date, ts_code, title, type, announcement_type
        FROM announcements
        WHERE announcement_type LIKE 'irm:%%'
        """
        params: dict[str, Any] = {}

        if ts_code:
            sql += " AND ts_code = :ts_code"
            params["ts_code"] = ts_code
        if keyword:
            sql += " AND (title LIKE :keyword OR type LIKE :keyword)"
            params["keyword"] = f"%{keyword}%"
        if sd := _parse_yyyymmdd(start_date):
            sql += " AND ann_date >= :start_date"
            params["start_date"] = sd
        if ed := _parse_yyyymmdd(end_date):
            sql += " AND ann_date <= :end_date"
            params["end_date"] = ed

        sql += " ORDER BY ann_date DESC LIMIT :limit"
        params["limit"] = limit

        try:
            async with engine.connect() as conn:
                result = await conn.execute(text(sql), params)
                rows = result.fetchall()
            return [
                {
                    "ann_date": row[0].strftime("%Y%m%d") if row[0] else "",
                    "ts_code": row[1] or "",
                    "question": row[2] or "",
                    "answer": row[3] or "",
                    "exchange": (row[4] or "").split(":", 1)[-1] if row[4] else "",
                }
                for row in rows
            ]
        except Exception as exc:
            logger.warning("查询互动易失败: %s", exc)
            return []


_report_service: ReportService | None = None


def get_report_service() -> ReportService:
    """获取 ReportService 单例"""
    global _report_service
    if _report_service is None:
        _report_service = ReportService()
    return _report_service
