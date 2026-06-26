"""
概念板块热度 Tool — 本地数据库版

数据来源：PostgreSQL（ConceptService）→ 定时任务写入
"""

import logging
from typing import Annotated

from langchain_core.tools import tool

from app.reasoning.tools._async_runner import run_async

logger = logging.getLogger(__name__)


@tool("get_concept_hot")
def get_concept_hot(
    top_n: Annotated[int, "返回排名数，默认20"] = 20,
    sort_by: Annotated[str, "排序方式：change_pct=涨跌幅/turnover=换手率/limit_up=涨停家数"] = "change_pct",
) -> str:
    """获取概念板块热度排名，包括涨跌幅度、成交量、换手率、涨停家数等。输入排名数量和排序方式，返回热点概念板块列表。"""
    return run_async(_fetch_concept_hot(top_n, sort_by))


async def _fetch_concept_hot(top_n: int, sort_by: str) -> str:
    """从本地数据库读取概念热度数据"""
    try:
        from app.data_pipeline.services.concept_service import get_concept_service

        service = get_concept_service()
        items = await service.get_concept_ranking(
            top_n=min(top_n, 50),
            sort_by=sort_by,
            days=1,
        )
        if items:
            return _format_concepts(items, sort_by)
    except Exception as e:
        logger.warning(f"[ConceptHotTool] 本地查询失败: {e}")

    return "未获取到概念板块热度数据。本地数据库可能尚未同步数据，请稍后再试。"


def _format_concepts(items: list[dict], sort_by: str) -> str:
    """格式化概念数据"""
    sort_label = {"change_pct": "涨跌幅", "turnover": "换手率", "limit_up": "涨停家数"}.get(sort_by, sort_by)
    lines = [f"## 概念板块热度排名（按{sort_label}，共 {len(items)} 条）\n\n"]
    lines.append("| 排名 | 板块名称 | 涨跌幅 | 涨停家数 | 综合得分 |\n")
    lines.append("|------|----------|--------|----------|----------|\n")

    for item in items:
        name = item.get("name", "未知")
        pct_chg = item.get("pct_chg", 0)
        up_nums = item.get("up_nums", 0)
        score = item.get("score", 0)
        arrow = "↑" if pct_chg >= 0 else "↓"
        lines.append(f"| {item.get('rank', '?')} | {name} | {arrow}{abs(pct_chg):.2f}% | {up_nums} | {score:.2f} |\n")

    return "".join(lines)
