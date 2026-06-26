"""
resolve + expand — 图谱导航工具。

resolve: 将自然语言查询锚定到图谱中的具体实体。
expand:  受控展开图谱子图，按需选择查询字段和过滤条件。
"""

from __future__ import annotations

import logging
import re
import unicodedata

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

# ── 常量 ───────────────────────────────────────────────────────

_SELECT_FIELDS = frozenset(
    {
        "properties",
        "relations",
        "metrics",
        "products",
        "companies",
        "upstream",
        "downstream",
        "peers",
        "divergence",
    }
)

_UPSTREAM_SUBTYPES = {"supplied_by", "provided_by", "purchased_from", "sourced_from"}
_DOWNSTREAM_SUBTYPES = {"supplies_to", "provides_to", "sells_to", "produces"}

_ENTITY_TYPE_PREFIX = {
    "Company": "C",
    "Product": "P",
    "Metric": "M",
}


# ── resolve 内部辅助 ───────────────────────────────────────────


def _normalize_query(query: str) -> str:
    """标准化查询字符串：去首尾空白、全角转半角、合并空白。"""
    # NFKC 标准化：全角→半角、兼容分解
    normalized = unicodedata.normalize("NFKC", query)
    # 合并连续空白为单个空格，并去首尾空白
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def _search_entity_by_name(query: str, entity_type: str | None = None) -> list[dict]:
    """在 Neo4j 中搜索实体。

    策略 1: 通过 entity_id 前缀精确匹配 (C_{norm}, P_{norm}, M_{norm})
    策略 2: CONTAINS 模糊匹配 name 属性

    Returns:
        [{"entity_id", "name", "type", "score"}]
    """
    from app.core.neo4j_client import run

    norm = _normalize_query(query)
    results: list[dict] = []

    # 策略 1: entity_id 精确匹配
    if entity_type:
        prefixes = [_ENTITY_TYPE_PREFIX[entity_type]]
    else:
        prefixes = list(_ENTITY_TYPE_PREFIX.values())

    for prefix in prefixes:
        eid = f"{prefix}_{norm}"
        cypher = "MATCH (n) WHERE n.entity_id = $eid RETURN n.entity_id AS entity_id, n.name AS name, labels(n) AS labels LIMIT 1"
        rows = run(cypher, {"eid": eid})
        if rows:
            row = rows[0]
            labels = row.get("labels", [])
            # 取第一个非空 label 作为 type
            etype = next((l for l in labels if l in _ENTITY_TYPE_PREFIX), labels[0] if labels else "Unknown")
            results.append(
                {
                    "entity_id": row["entity_id"],
                    "name": row.get("name", norm),
                    "type": etype,
                    "score": 1.0,
                }
            )

    if results:
        return results

    # 策略 2: CONTAINS 模糊匹配
    cypher = "MATCH (n) WHERE n.name CONTAINS $query"
    params: dict = {"query": norm}
    if entity_type:
        cypher += " AND ANY(l IN labels(n) WHERE l = $etype)"
        params["etype"] = entity_type
    cypher += " RETURN n.entity_id AS entity_id, n.name AS name, labels(n) AS labels LIMIT 10"
    rows = run(cypher, params)
    for row in rows:
        labels = row.get("labels", [])
        etype = next((l for l in labels if l in _ENTITY_TYPE_PREFIX), labels[0] if labels else "Unknown")
        # 简单评分：完全匹配 0.9，包含匹配 0.7
        score = 0.9 if row.get("name") == norm else 0.7
        results.append(
            {
                "entity_id": row["entity_id"],
                "name": row.get("name", ""),
                "type": etype,
                "score": score,
            }
        )

    return results


# ── resolve 工具 ───────────────────────────────────────────────


@tool("resolve")
def resolve(query: str, entity_type: str | None = None) -> dict | None:
    """将自然语言查询锚定到图谱中的具体实体。

    Args:
        query: 实体名称（如"宁德时代"、"电源模块"）
        entity_type: 可选实体类型过滤 ("Company"|"Product"|"Metric")

    Returns:
        锚定的实体 {entity_id, name, type, score}，未找到返回 null
    """
    norm = _normalize_query(query)
    candidates = _search_entity_by_name(norm, entity_type)
    if not candidates:
        return None
    # 返回得分最高的候选
    best = max(candidates, key=lambda c: c["score"])
    return best


# ── expand 内部辅助 ────────────────────────────────────────────


def _fetch_entity(entity_id: str) -> dict | None:
    """MATCH 实体，返回所有属性。"""
    from app.core.neo4j_client import run_single

    cypher = "MATCH (n) WHERE n.entity_id = $eid RETURN properties(n) AS props, labels(n) AS labels LIMIT 1"
    row = run_single(cypher, {"eid": entity_id})
    if not row:
        return None
    props = row.get("props", {})
    labels = row.get("labels", [])
    etype = next((l for l in labels if l in _ENTITY_TYPE_PREFIX), labels[0] if labels else "Unknown")
    return {
        "id": entity_id,
        "name": props.get("name", ""),
        "type": etype,
        **{k: v for k, v in props.items() if k not in ("name", "entity_id")},
    }


def _fetch_relations(entity_id: str, filter_: dict | None = None) -> list[dict]:
    """MATCH RELATES 边，支持 stmt_types / relation_subtypes 过滤。"""
    from app.core.neo4j_client import run

    filter_ = filter_ or {}
    cypher = "MATCH (a)-[r:RELATES]->(b) WHERE a.entity_id = $eid"
    params: dict = {"eid": entity_id}

    stmt_types = filter_.get("stmt_types")
    if stmt_types:
        cypher += " AND r.stmt_type IN $stmt_types"
        params["stmt_types"] = stmt_types

    subtypes = filter_.get("relation_subtypes")
    if subtypes:
        cypher += " AND r.relation_subtype IN $subtypes"
        params["subtypes"] = subtypes

    cypher += " RETURN a.entity_id AS `from`, b.entity_id AS `to`, r.text AS text, r.weight AS weight, r.stmt_type AS stmt_type, r.relation_subtype AS relation_subtype, r.source AS source, r.confidence AS confidence ORDER BY r.weight DESC LIMIT 50"
    rows = run(cypher, params)
    return [dict(r) for r in rows]


def _fetch_typed_neighbors(entity_id: str, neighbor_type: str, filter_: dict | None = None) -> list[dict]:
    """MATCH 指定类型的邻居节点及其 RELATES 边信息。"""
    from app.core.neo4j_client import run

    filter_ = filter_ or {}
    cypher = f"MATCH (a)-[r:RELATES]->(b:{neighbor_type}) WHERE a.entity_id = $eid"
    params: dict = {"eid": entity_id}

    stmt_types = filter_.get("stmt_types")
    if stmt_types:
        cypher += " AND r.stmt_type IN $stmt_types"
        params["stmt_types"] = stmt_types

    subtypes = filter_.get("relation_subtypes")
    if subtypes:
        cypher += " AND r.relation_subtype IN $subtypes"
        params["subtypes"] = subtypes

    cypher += " RETURN b.entity_id AS entity_id, b.name AS name, labels(b) AS labels, r.text AS text, r.weight AS weight, r.stmt_type AS stmt_type, r.relation_subtype AS relation_subtype, r.source AS source, r.confidence AS confidence ORDER BY r.weight DESC LIMIT 50"
    rows = run(cypher, params)
    result = []
    for row in rows:
        labels = row.get("labels", [])
        etype = next((l for l in labels if l in _ENTITY_TYPE_PREFIX), neighbor_type)
        result.append(
            {
                "entity_id": row["entity_id"],
                "name": row.get("name", ""),
                "type": etype,
                "stmt_type": row.get("stmt_type", ""),
                "text": row.get("text", ""),
                "weight": row.get("weight", 0),
                "relation_subtype": row.get("relation_subtype", ""),
                "source": row.get("source", ""),
                "confidence": row.get("confidence"),
            }
        )
    return result


def _fetch_peers(entity_id: str, limit: int = 10) -> list[dict]:
    """查找共享 Product 邻居的同业公司。"""
    from app.core.neo4j_client import run

    cypher = """
    MATCH (c:Company)-[:RELATES]->(p:Product)<-[:RELATES]-(peer:Company)
    WHERE c.entity_id = $eid AND peer.entity_id <> $eid
    WITH peer, collect(DISTINCT p.name) AS shared_products, count(DISTINCT p) AS shared_count
    ORDER BY shared_count DESC
    LIMIT $limit
    RETURN peer.entity_id AS entity_id, peer.name AS name, labels(peer) AS labels,
           shared_count, shared_products
    """
    rows = run(cypher, {"eid": entity_id, "limit": limit})
    result = []
    for row in rows:
        labels = row.get("labels", [])
        etype = next((l for l in labels if l in _ENTITY_TYPE_PREFIX), "Company")
        result.append(
            {
                "entity_id": row["entity_id"],
                "name": row.get("name", ""),
                "type": etype,
                "shared_count": row.get("shared_count", 0),
                "shared_products": row.get("shared_products", []),
            }
        )
    return result


def _fetch_chain(entity_id: str, direction: str, depth: int = 3, limit: int = 10) -> list[dict]:
    """沿上游/下游方向遍历产业链。"""
    from app.core.neo4j_client import run

    if direction == "upstream":
        subtypes = list(_UPSTREAM_SUBTYPES)
    elif direction == "downstream":
        subtypes = list(_DOWNSTREAM_SUBTYPES)
    else:
        # both
        subtypes = list(_UPSTREAM_SUBTYPES | _DOWNSTREAM_SUBTYPES)

    max_depth = min(depth, 5)
    cypher = (
        """
    MATCH path = (start)-[r:RELATES*1..%d]->(end)
    WHERE start.entity_id = $eid
      AND ALL(rel IN r WHERE rel.relation_subtype IN $subtypes)
    WITH path, [n IN nodes(path) | {entity_id: n.entity_id, name: n.name, labels: labels(n)}] AS node_list,
         [rel IN relationships(path) | {`from`: startNode(rel).entity_id, `to`: endNode(rel).entity_id,
          text: rel.text, subtype: rel.relation_subtype, stmt_type: rel.stmt_type, weight: rel.weight}] AS edge_list
    RETURN node_list AS nodes, edge_list AS edges
    LIMIT $limit
    """
        % max_depth
    )
    rows = run(cypher, {"eid": entity_id, "subtypes": subtypes, "limit": limit})
    return [{"nodes": r.get("nodes", []), "edges": r.get("edges", [])} for r in rows]


def _fetch_divergence(entity_id: str, metric_name: str | None = None) -> list[dict]:
    """查找连接的 Metric 节点上 Fact vs Estimate 的分歧。"""
    from app.core.neo4j_client import run

    cypher = """
    MATCH (c)-[r:RELATES]->(m:Metric)
    WHERE c.entity_id = $eid
    """
    params: dict = {"eid": entity_id}
    if metric_name:
        cypher += " AND m.name CONTAINS $metric_name"
        params["metric_name"] = metric_name

    cypher += """
    WITH m, collect(CASE WHEN r.stmt_type = 'Fact' THEN {text: r.text, weight: r.weight, source: r.source, confidence: r.confidence} END) AS facts,
           collect(CASE WHEN r.stmt_type = 'Estimate' THEN {text: r.text, weight: r.weight, source: r.source, confidence: r.confidence} END) AS estimates,
           collect(CASE WHEN r.stmt_type = 'Claim' THEN {text: r.text, weight: r.weight, source: r.source, confidence: r.confidence} END) AS claims
    WHERE size(facts) > 0 OR size(estimates) > 0
    RETURN m.entity_id AS metric_id, m.name AS metric_name, facts, estimates, claims
    """
    rows = run(cypher, params)
    result = []
    for row in rows:
        facts = [f for f in row.get("facts", []) if f is not None]
        estimates = [e for e in row.get("estimates", []) if e is not None]
        claims = [c for c in row.get("claims", []) if c is not None]
        gap = _compute_gap(facts, estimates)
        entry = {
            "metric_id": row["metric_id"],
            "metric_name": row.get("metric_name", ""),
            "facts": facts,
            "estimates": estimates,
            "claims": claims,
        }
        if gap:
            entry["gap"] = gap
        result.append(entry)
    return result


def _compute_gap(facts: list[dict], estimates: list[dict]) -> dict | None:
    """从 Fact 和 Estimate 文本中提取数值，计算分歧百分比。"""
    # 简单数值提取：匹配中文数字格式（如 120亿、150亿）或纯数字
    _num_pattern = re.compile(r"(\d+\.?\d*)\s*([万亿百]?[万亿百]?)")

    def _extract_value(items: list[dict]) -> float | None:
        for item in items:
            text = item.get("text", "")
            m = _num_pattern.search(text)
            if m:
                val = float(m.group(1))
                unit = m.group(2)
                if "万亿" in unit:
                    val *= 1_0000_0000_0000
                elif "亿" in unit:
                    val *= 1_0000_0000
                elif "万" in unit:
                    val *= 1_0000
                return val
        return None

    fact_val = _extract_value(facts)
    est_val = _extract_value(estimates)
    if fact_val is None or est_val is None or fact_val == 0:
        return None

    gap_pct = (est_val - fact_val) / abs(fact_val) * 100
    direction = "bullish" if gap_pct > 0 else "bearish" if gap_pct < 0 else "neutral"
    return {
        "fact_value": fact_val,
        "estimate_value": est_val,
        "gap_pct": f"{gap_pct:+.0f}%",
        "direction": direction,
    }


def _aggregate_metrics(raw_metrics: list[dict]) -> dict[str, dict]:
    """将 metric 邻居按 entity_id 分组，再按 stmt_type 子分组。"""
    grouped: dict[str, dict] = {}
    for m in raw_metrics:
        mid = m["entity_id"]
        if mid not in grouped:
            grouped[mid] = {
                "name": m.get("name", ""),
                "type": m.get("type", "Metric"),
                "facts": [],
                "estimates": [],
                "claims": [],
            }
        entry = {
            "text": m.get("text", ""),
            "weight": m.get("weight", 0),
            "source": m.get("source", ""),
            "confidence": m.get("confidence"),
            "relation_subtype": m.get("relation_subtype", ""),
        }
        stmt = m.get("stmt_type", "")
        if stmt == "Fact":
            grouped[mid]["facts"].append(entry)
        elif stmt == "Estimate":
            grouped[mid]["estimates"].append(entry)
        elif stmt == "Claim":
            grouped[mid]["claims"].append(entry)
        else:
            # 未知 stmt_type 放入 facts
            grouped[mid]["facts"].append(entry)
    return grouped


# ── expand 工具 ────────────────────────────────────────────────


@tool("expand")
def expand(entity_id: str, select: list[str], filter_: dict | None = None) -> dict:
    """受控展开图谱子图，按需选择查询字段和过滤条件。

    Args:
        entity_id: 已锚定的实体 ID（如 resolve 返回的 entity_id）
        select: 要获取的字段列表，可选值:
            properties, relations, metrics, products, companies,
            upstream, downstream, peers, divergence
        filter_: 可选过滤条件:
            direction: "upstream"|"downstream"|"both"
            relation_subtypes: 按关系子类型过滤
            stmt_types: 按陈述类型过滤 ["Fact","Claim","Estimate"]
            depth: 遍历深度（默认1，最大5）
            limit: 返回数量限制（默认20）

    Returns:
        按 select 字段组合的子图结果
    """
    filter_dict = filter_ or {}
    result: dict = {}

    # 验证 select 字段
    valid_selects = [s for s in select if s in _SELECT_FIELDS]
    if not valid_selects:
        return {"error": f"无效的 select 字段。可选值: {sorted(_SELECT_FIELDS)}"}

    # 构建 filter 子集，按需传递
    rel_filter = {k: v for k, v in filter_dict.items() if k in ("stmt_types", "relation_subtypes")} or None

    for field in valid_selects:
        if field == "properties":
            entity = _fetch_entity(entity_id)
            result["entity"] = entity

        elif field == "relations":
            rels = _fetch_relations(entity_id, rel_filter)
            # 如果 filter 中指定了 stmt_types，在应用层也做一次过滤
            stmt_filter = filter_dict.get("stmt_types")
            if stmt_filter:
                rels = [r for r in rels if r.get("stmt_type") in stmt_filter]
            result["relations"] = rels

        elif field == "metrics":
            raw = _fetch_typed_neighbors(entity_id, "Metric", rel_filter)
            result["metrics"] = _aggregate_metrics(raw)

        elif field == "products":
            raw = _fetch_typed_neighbors(entity_id, "Product", rel_filter)
            result["products"] = _aggregate_metrics(raw)

        elif field == "companies":
            raw = _fetch_typed_neighbors(entity_id, "Company", rel_filter)
            result["companies"] = _aggregate_metrics(raw)

        elif field == "upstream":
            depth = filter_dict.get("depth", 1)
            limit = filter_dict.get("limit", 20)
            paths = _fetch_chain(entity_id, "upstream", depth=min(depth, 5), limit=limit)
            result["paths"] = paths

        elif field == "downstream":
            depth = filter_dict.get("depth", 1)
            limit = filter_dict.get("limit", 20)
            paths = _fetch_chain(entity_id, "downstream", depth=min(depth, 5), limit=limit)
            result["paths"] = paths

        elif field == "peers":
            limit = filter_dict.get("limit", 20)
            result["peers"] = _fetch_peers(entity_id, limit=limit)

        elif field == "divergence":
            result["divergences"] = _fetch_divergence(entity_id)

    return result
