"""
基本面查询 Tool — 本地数据库版

数据来源：PostgreSQL（StockService/ReportService）→ 定时任务写入
"""
import logging
from typing import Annotated

from langchain_core.tools import tool

from app.reasoning.tools._async_runner import run_async

logger = logging.getLogger(__name__)


@tool("get_stock_profile")
def get_stock_profile(
    ts_code: Annotated[str, "股票代码，如 300308.SZ"],
) -> str:
    """查询股票主营业务概况，包括主营产品、经营范围、主营业务一句话概述。输入股票代码，返回公司主营业务详细信息。"""
    return run_async(_fetch_profile(ts_code))


async def _fetch_profile(ts_code: str) -> str:
    """从本地数据库读取股票概况"""
    try:
        from app.data_pipeline.services.stock_service import get_stock_service
        service = get_stock_service()
        data = await service.get_stock_profile(ts_code)
        if data and data.get("main_business"):
            return _format_profile(ts_code, data)
    except Exception as e:
        logger.warning(f"[StockProfileTool] 本地查询失败 {ts_code}: {e}")

    return f"未找到股票 {ts_code} 的概况信息。本地数据库可能尚未同步数据，请稍后再试。"


def _format_profile(ts_code: str, data: dict) -> str:
    """格式化股票概况数据"""
    lines = [f"## {ts_code} 股票概况\n\n"]
    if data.get("main_business"):
        lines.append(f"- **主营业务**：{data['main_business']}\n")
    if data.get("product_type"):
        lines.append(f"- **产品分类**：{data['product_type']}\n")
    if data.get("product_name"):
        lines.append(f"- **具体产品**：{data['product_name']}\n")
    if data.get("business_scope"):
        lines.append(f"- **经营范围**：{data['business_scope']}\n")

    if len(lines) == 2:
        lines.append(f"未找到股票 {ts_code} 的概况信息。\n")

    return "".join(lines)


@tool("get_irm")
def get_irm(
    ts_code: Annotated[str, "股票代码，如 000001.SZ"],
    keyword: Annotated[str, "关键词，搜索问题内容"] = "",
    start_date: Annotated[str, "开始日期，YYYYMMDD"] = "",
    end_date: Annotated[str, "结束日期，YYYYMMDD"] = "",
    page_size: Annotated[int, "返回条数，默认20"] = 20,
) -> str:
    """查询互动易 Q&A 数据，了解投资者与公司的交流内容。输入股票代码、关键词和日期范围，返回投资者提问与公司回复的列表。"""
    return run_async(_fetch_irm(ts_code, keyword, start_date, end_date, page_size))


async def _fetch_irm(
    ts_code: str, keyword: str, start_date: str, end_date: str, page_size: int
) -> str:
    """从本地数据库读取互动易数据"""
    try:
        from app.data_pipeline.services.report_service import get_report_service
        service = get_report_service()
        items = await service.search_irm(
            ts_code=ts_code or None,
            keyword=keyword or None,
            start_date=start_date or None,
            end_date=end_date or None,
            limit=min(page_size, 200),
        )
        if items:
            return _format_irm(ts_code, items)
    except Exception as e:
        logger.warning(f"[IRMTool] 本地查询失败 {ts_code}: {e}")

    return f"未找到股票 {ts_code} 的互动易数据。本地数据库可能尚未同步数据，请稍后再试。"


def _format_irm(ts_code: str, items: list[dict]) -> str:
    """格式化互动易数据"""
    lines = [f"## {ts_code} 互动易（共 {len(items)} 条）\n\n"]
    for item in items[:20]:
        question = (item.get("question") or "").strip()
        answer = (item.get("answer") or "").strip()
        qt = (item.get("ann_date") or "")[:10]
        exchange = item.get("exchange") or ""
        header = f"**[{qt}]**"
        if exchange:
            header += f" ({exchange})"
        lines.append(header + f" {question[:200]}\n")
        if answer:
            lines.append(f"→ 回复：{answer[:300]}\n")
        lines.append("\n")
    return "".join(lines)
