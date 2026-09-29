# backend/app/reasoning/tools/knowledge/graph_walk.py
"""LangChain @tool thin wrappers over app.knowledge.agent_graph_ops."""
from __future__ import annotations

from typing import Annotated

from langchain_core.tools import tool

from app.knowledge import agent_graph_ops
from app.reasoning.tools.knowledge.link_queries import run_async


def _run_sync(coro):
    return run_async(coro)


@tool
def related_nodes(
    keyword: Annotated[str, "起点节点：公司名/ts_code、产品或指标名"],
    layer: Annotated[str | None, "限定邻居层：subject|scope|dimension|stage；不填则全部"] = None,
    top_k: Annotated[int, "返回邻居数上限"] = 20,
) -> dict:
    """图传递（一跳）：某节点在图上的直接邻居及其共现广度。"""
    return _run_sync(
        agent_graph_ops.related_nodes(keyword=keyword, layer=layer, top_k=top_k)
    )


@tool
def propagate_along(
    start: Annotated[str, "起点：公司名/ts_code 或产品名"],
    max_hops: Annotated[int, "最大跳数（1-3；越大越容易引入噪音）"] = 2,
    min_cooccur: Annotated[int, "边的最小共现证据数（过滤弱关联）"] = 2,
    top_k: Annotated[int, "每返回节点数上限"] = 15,
) -> dict:
    """图传递（多跳）：沿共现链寻找间接关联节点。"""
    return _run_sync(
        agent_graph_ops.propagate_along(
            start=start, max_hops=max_hops, min_cooccur=min_cooccur, top_k=top_k
        )
    )
