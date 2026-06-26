"""
市场宽度 Tool — 本地数据库版

数据来源：PostgreSQL（MarketService）→ 定时任务写入
"""

import logging
from typing import Annotated

from langchain_core.tools import tool

from app.reasoning.tools._async_runner import run_async

logger = logging.getLogger(__name__)


@tool("get_market_breadth")
def get_market_breadth(
    market: Annotated[str, "市场：A股=全市场/SZ=深圳/SH=上海，默认A股"] = "A股",
) -> str:
    """获取市场宽度指标，包括上涨下跌家数、涨停炸板数量、市场情绪等。输入市场（A股/深圳/上海），返回市场整体情绪和资金分布数据。"""
    return run_async(_fetch_breadth(market))


async def _fetch_breadth(market: str) -> str:
    """从本地数据库读取市场宽度数据"""
    try:
        from app.data_pipeline.services.market_service import get_market_service

        service = get_market_service()
        data = await service.get_market_breadth(market)
        if data and data.get("total", 0) > 0:
            return _format_breadth(data)
    except Exception as e:
        logger.warning(f"[MarketBreadthTool] 本地查询失败: {e}")

    return "未获取到市场宽度数据。本地数据库可能尚未同步数据，请稍后再试。"


def _format_breadth(data: dict) -> str:
    """格式化市场宽度数据"""
    advance = data.get("advance_count", 0)
    decline = data.get("decline_count", 0)
    limit_up = data.get("limit_up_count", 0)
    limit_down = data.get("limit_down_count", 0)
    unchanged = data.get("unchanged_count", 0)
    data.get("total", 0)
    breadth_pct = data.get("breadth_pct", 0)

    lines = [
        f"## 市场宽度指标（{data.get('trade_date', '今日')}）\n\n",
        "**整体格局**：\n",
        f"- 上涨：{advance} 家（{breadth_pct:.1f}%）\n",
        f"- 下跌：{decline} 家\n",
        f"- 平盘：{unchanged} 家\n",
        f"- 涨停：{limit_up} 家\n",
        f"- 跌停：{limit_down} 家\n\n",
        f"**市场情绪**：{'偏多' if advance > decline else '偏空' if advance < decline else '中性'}\n\n",
    ]

    if breadth_pct > 60:
        lines.append("→ 市场情绪：**强势**，资金活跃\n")
    elif breadth_pct > 50:
        lines.append("→ 市场情绪：**偏强**，上涨家数占优\n")
    elif breadth_pct > 40:
        lines.append("→ 市场情绪：**偏弱**，下跌家数较多\n")
    else:
        lines.append("→ 市场情绪：**弱势**，市场信心不足\n")

    return "".join(lines)
