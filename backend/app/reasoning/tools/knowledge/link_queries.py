"""
链接层检索工具 — 时间线/横截面/单跳聚合/双向引用。

包装 app.knowledge.linklayer.queries 的 5 个检索原语为 agent 工具：
- pull_history: (主体×维度) 时间序证据时间线，判断递进/变化/矛盾的正门
- scan_dimension: 横截面查询，某维度下各主体证据聚合
- lookup_products / lookup_players: 单跳聚合（公司↔产品）
- backlinks: 双向引用导航（evidence → keywords → related evidence）

底层 queries 为 async，通过 run_async 桥接（与 announcement/kline 等工具一致）。
"""

from __future__ import annotations

from typing import Annotated

from langchain_core.tools import tool

from app.reasoning.tools._async_runner import run_async


@tool("pull_history")
def pull_history_tool(
    subject: Annotated[str, "主体（公司名或 ts_code）"],
    dimension: Annotated[str | None, "维度名，如 产线进展/客户认证/毛利率；None=不限"] = None,
    scope: Annotated[str | None, "产品/技术范围，如 8英寸抛光硅片；None=不限"] = None,
    before: Annotated[str | None, "只看该时间点（ISO 格式）之前的，用于向前翻页"] = None,
    limit: Annotated[int, "最多返回条数，默认 100"] = 100,
) -> dict:
    """按时间序拉取 (主体×维度) 的完整证据时间线。判断递进/变化/矛盾必用此工具（不是语义搜索）。"""
    from app.knowledge.linklayer.queries import pull_history

    return run_async(pull_history(subject, dimension=dimension, scope=scope, before=before, limit=limit))


@tool("scan_dimension")
def scan_dimension_tool(
    dimension: Annotated[str, "维度名，如 毛利率/产线进展/客户认证"],
    scope: Annotated[str | None, "产品/技术范围过滤，如 8英寸抛光硅片；None=不限"] = None,
    as_of: Annotated[str | None, "时间截面（ISO 格式），只统计该时点之前；None=不限"] = None,
    limit: Annotated[int, "最多返回条数，默认 50"] = 50,
) -> dict:
    """横截面查询：某维度（如毛利率）下各主体的证据聚合，用于跨公司对比。"""
    from app.knowledge.linklayer.queries import scan_dimension

    return run_async(scan_dimension(dimension, scope=scope, as_of=as_of, limit=limit))


@tool("lookup_products")
def lookup_products_tool(
    company: Annotated[str, "公司名或 ts_code，如 300750.SZ"],
    top_k: Annotated[int, "最多返回条数，默认 20"] = 20,
) -> list[dict]:
    """单跳聚合：某公司关联的产品/技术列表（带提及频次与最近提及时间）。"""
    from app.knowledge.linklayer.queries import lookup_products

    return run_async(lookup_products(company, top_k=top_k))


@tool("lookup_players")
def lookup_players_tool(
    keyword_norm_text: Annotated[str, "产品/技术关键字，如 8英寸抛光硅片"],
    top_k: Annotated[int, "最多返回条数，默认 20"] = 20,
) -> list[dict]:
    """单跳聚合：某产品/关键字下的公司列表（传导挖掘入口）。"""
    from app.knowledge.linklayer.queries import lookup_players

    return run_async(lookup_players(keyword_norm_text, top_k=top_k))


@tool("backlinks")
def backlinks_tool(
    evidence_id: Annotated[str, "证据 ID（如 pull_history 返回的 evidence_id）"],
) -> dict:
    """查看某条证据的全部关键字及同关键字关联证据（双向引用导航）。"""
    from app.knowledge.linklayer.queries import backlinks

    return run_async(backlinks(evidence_id))
