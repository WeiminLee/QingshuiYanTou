# backend/app/reasoning/tools/knowledge/metric_ops.py
"""LangChain @tool thin wrappers over app.knowledge.agent_metric_ops.

HTTP / dsh path must NOT import this module — use agent_metric_ops directly.
"""
from __future__ import annotations

from typing import Annotated

from langchain_core.tools import tool

from app.knowledge import agent_metric_ops
from app.reasoning.tools.knowledge.link_queries import run_async


def _run_sync(coro):
    return run_async(coro)


@tool
def compare_metric(
    dimension: Annotated[str, "对比标尺：任意指标名，如 '毛利率'、'营业收入'、'高速通信线营业收入'"],
    scope: Annotated[str | None, "限定范围（产品/主题），如 '硅片'；不填则不限"] = None,
    as_of: Annotated[str | None, "时点（ISO 日期），只看该日之前的证据"] = None,
    top_k: Annotated[int, "返回主体数上限"] = 30,
) -> dict:
    """横向预期差：同一标尺下，不同公司的数值对比与排名。"""
    return _run_sync(
        agent_metric_ops.compare_metric(
            dimension=dimension, scope=scope, as_of=as_of, top_k=top_k
        )
    )


@tool
def rollup_metric(
    parent: Annotated[str, "上卷目标（粗粒度标尺），如 '营收'、'毛利率'"],
    scope: Annotated[str | None, "限定范围（产品/主题）"] = None,
    top_k: Annotated[int, "返回子指标数上限"] = 30,
) -> dict:
    """层次上卷：把细粒度指标聚合到粗粒度标尺下。"""
    return _run_sync(
        agent_metric_ops.rollup_metric(parent=parent, scope=scope, top_k=top_k)
    )


@tool
def metric_trend(
    subject: Annotated[str, "主体：公司 ts_code 或名称"],
    dimension: Annotated[str | None, "标尺：指标名；不填则取该主体全部指标"] = None,
    limit: Annotated[int, "返回记录数上限"] = 50,
) -> dict:
    """纵向预期差：同一主体在时间轴上的数值/表述变化。"""
    return _run_sync(
        agent_metric_ops.metric_trend(subject=subject, dimension=dimension, limit=limit)
    )
