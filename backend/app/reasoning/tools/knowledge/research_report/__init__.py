"""
研报检索 Tool — 本地数据库版

数据来源：PostgreSQL（ReportService）→ 定时任务写入
"""
import logging
from typing import Annotated

from langchain_core.tools import tool

from app.reasoning.tools._async_runner import run_async

logger = logging.getLogger(__name__)


@tool("get_research_report")
def get_research_report(
    ts_code: Annotated[str, "股票代码，如 300308.SZ"] = "",
    keyword: Annotated[str, "关键词，搜索研报标题或内容"] = "",
    start_date: Annotated[str, "开始日期，YYYYMMDD"] = "",
    end_date: Annotated[str, "结束日期，YYYYMMDD"] = "",
    page_size: Annotated[int, "返回条数，默认10"] = 10,
) -> str:
    """检索研报摘要，包括券商评级、目标价、核心观点等。输入股票代码、关键词和日期范围，返回研报列表和核心摘要。"""
    return run_async(_fetch_reports(ts_code, keyword, start_date, end_date, page_size))


async def _fetch_reports(
    ts_code: str, keyword: str, start_date: str, end_date: str, page_size: int
) -> str:
    """从本地数据库读取研报数据"""
    try:
        from app.data_pipeline.services.report_service import get_report_service
        service = get_report_service()
        items = await service.search_reports(
            ts_code=ts_code or None,
            keyword=keyword or None,
            start_date=start_date or None,
            end_date=end_date or None,
            limit=min(page_size, 50),
        )
        if items:
            return _format_reports(items, ts_code, keyword)
    except Exception as e:
        logger.warning(f"[ResearchReportTool] 本地查询失败: {e}")

    return "未找到匹配的研报数据。本地数据库可能尚未同步数据，请稍后再试。"


def _format_reports(items: list[dict], ts_code: str, keyword: str) -> str:
    """格式化研报数据"""
    total = len(items)
    lines = [f"## 研报检索结果（共 {total} 条）\n\n"]

    for item in items:
        title = item.get("title", "无标题")
        institution = item.get("institution", item.get("inst_csname", ""))
        analyst = item.get("analyst", item.get("author", ""))
        rating = item.get("rating", "")
        target_price = item.get("target_price", "")
        pub_date = item.get("trade_date", item.get("pub_date", ""))[:10]
        summary = item.get("summary", "")[:300]

        header = f"**{title}**"
        if rating:
            header += f"({rating})"
        lines.append(header + "\n")

        meta = []
        if institution:
            meta.append(f"券商：{institution}")
        if analyst:
            meta.append(f"分析师：{analyst}")
        if pub_date:
            meta.append(f"日期：{pub_date}")
        if target_price:
            meta.append(f"目标价：{target_price}")
        if meta:
            lines.append("  " + " | ".join(meta) + "\n")
        if summary:
            lines.append(f"  {summary}...\n")
        lines.append("\n")

    return "".join(lines)
