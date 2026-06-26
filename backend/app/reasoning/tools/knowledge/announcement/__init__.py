"""
公告检索 Tool — 本地数据库版

数据来源：PostgreSQL（ReportService）→ 定时任务写入
"""

import logging
from typing import Annotated

from langchain_core.tools import tool

from app.reasoning.tools._async_runner import run_async

logger = logging.getLogger(__name__)


@tool("get_announcement")
def get_announcement(
    ts_code: Annotated[str, "股票代码，如 300308.SZ"] = "",
    keyword: Annotated[str, "关键词，搜索公告标题"] = "",
    start_date: Annotated[str, "开始日期，YYYYMMDD"] = "",
    end_date: Annotated[str, "结束日期，YYYYMMDD"] = "",
    page_size: Annotated[int, "返回条数，默认10"] = 10,
) -> str:
    """检索上市公司公告，查看重要事件披露。输入股票代码、关键词和日期范围，返回公告列表和内容摘要。"""
    return run_async(_fetch_announcements(ts_code, keyword, start_date, end_date, page_size))


async def _fetch_announcements(ts_code: str, keyword: str, start_date: str, end_date: str, page_size: int) -> str:
    """从本地数据库读取公告数据"""
    try:
        from app.data_pipeline.services.report_service import get_report_service

        service = get_report_service()
        items = await service.search_announcements(
            ts_code=ts_code or None,
            keyword=keyword or None,
            start_date=start_date or None,
            end_date=end_date or None,
            limit=min(page_size, 50),
        )
        if items:
            return _format_announcements(items)
    except Exception as e:
        logger.warning(f"[AnnouncementTool] 本地查询失败: {e}")

    return "未找到匹配的公告数据。本地数据库可能尚未同步数据，请稍后再试。"


def _format_announcements(items: list[dict]) -> str:
    """格式化公告数据"""
    lines = [f"## 公告检索结果（共 {len(items)} 条）\n\n"]

    for item in items:
        title = item.get("title", "无标题")
        ann_date = item.get("ann_date", "")
        ann_type = item.get("type", item.get("announcement_type", ""))
        ts = item.get("ts_code", "")

        lines.append(f"**{title}**")
        meta = []
        if ts:
            meta.append(f"股票：{ts}")
        if ann_date:
            meta.append(f"日期：{ann_date}")
        if ann_type:
            meta.append(f"类型：{ann_type}")
        if meta:
            lines.append("（" + " | ".join(meta) + "）")
        lines.append("\n\n")

    return "".join(lines)
