"""
KG 质量指标模块

存放图谱统计类指标（区别于 eval/metrics.py 的业务评估指标）。

三个核心指标：
1. node_density    — 各类型节点数量分布 {Company: N, Product: N, Metric: N}
2. relates_coverage — Company+Product 节点中有 RELATES 边的比例（0.0 ~ 1.0）
3. weight_distribution — RELATES 边 weight 值的桶分布

使用方式：
    from app.knowledge.kg_metrics import node_density, relates_coverage, weight_distribution
    print(node_density())       # {'Company': 120, 'Product': 340, 'Metric': 85}
    print(relates_coverage())   # 0.73
    print(weight_distribution()) # {'0.0-0.2': 12, '0.2-0.4': 45, ...}
"""

from __future__ import annotations

import logging

from app.core.neo4j_client import run

logger = logging.getLogger(__name__)


def node_density() -> dict:
    """
    各类型节点数量分布（V1.2 Schema）。

    统计 Company / Product / Metric 三类节点的数量。

    Returns:
        {"Company": int, "Product": int, "Metric": int}
    """
    cypher = """
    MATCH (n)
    WHERE labels(n)[0] IN ['Company', 'Product', 'Metric']
    RETURN labels(n)[0] AS label, count(n) AS cnt
    ORDER BY label
    """
    result = run(cypher)
    density = {"Company": 0, "Product": 0, "Metric": 0}
    for row in result:
        label = row.get("label", "")
        cnt = row.get("cnt", 0)
        if label in density:
            density[label] = cnt
    return density


def relates_coverage() -> float:
    """
    Company + Product 节点中，有至少一条 RELATES 边的节点比例。

    值越低表示图谱中孤立节点越多。

    Returns:
        float: 0.0 ~ 1.0
    """
    total_cypher = """
    MATCH (n)
    WHERE labels(n)[0] IN ['Company', 'Product']
    RETURN count(n) AS total
    """
    total_rows = run(total_cypher)
    total = total_rows[0].get("total", 0) if total_rows else 0

    if total == 0:
        return 0.0

    covered_cypher = """
    MATCH (n)-[r:RELATES]->()
    WHERE labels(n)[0] IN ['Company', 'Product']
    RETURN count(DISTINCT n) AS covered
    """
    covered_rows = run(covered_cypher)
    covered = covered_rows[0].get("covered", 0) if covered_rows else 0

    return round(covered / total, 4)


def weight_distribution() -> dict:
    """
    RELATES 边 weight 值的桶分布。

    桶区间：["0.0-0.2", "0.2-0.4", "0.4-0.6", "0.6-0.8", "0.8-1.0"]

    Returns:
        {"0.0-0.2": int, "0.2-0.4": int, "0.4-0.6": int, "0.6-0.8": int, "0.8-1.0": int}
    """
    buckets = ["0.0-0.2", "0.2-0.4", "0.4-0.6", "0.6-0.8", "0.8-1.0"]
    result = {b: 0 for b in buckets}

    cypher = """
    MATCH (a)-[r:RELATES]->(b)
    WHERE r.weight IS NOT NULL
    RETURN r.weight AS weight
    """
    rows = run(cypher)
    for row in rows:
        w = float(row.get("weight", 0))
        if w < 0.2:
            result["0.0-0.2"] += 1
        elif w < 0.4:
            result["0.2-0.4"] += 1
        elif w < 0.6:
            result["0.4-0.6"] += 1
        elif w < 0.8:
            result["0.6-0.8"] += 1
        else:
            result["0.8-1.0"] += 1

    return result
