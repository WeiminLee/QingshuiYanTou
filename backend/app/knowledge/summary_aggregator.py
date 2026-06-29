"""
summary_aggregator.py — L1/L2/L3 分层摘要聚合逻辑

每层锚定在明确的实体 ID 上，聚合规则是确定性的。
"""
from __future__ import annotations

import logging
from typing import Any

from app.core.llm_client import chat_async
from app.core.neo4j_client import get_async_driver
from app.knowledge.summary_cache import get_summary, is_stale, put_summary
from app.knowledge.summary_prompts import (
    L1_COMPANY_PROFILE_PROMPT,
    L2_PRODUCT_ECOSYSTEM_PROMPT,
    L3_INDUSTRY_CHAIN_PROMPT,
)

logger = logging.getLogger(__name__)

# ── L1: 公司画像 ────────────────────────────────────────────


async def aggregate_l1(entity_id: str) -> str:
    """聚合 Company 的所有 RELATES 边，生成公司画像。

    Args:
        entity_id: Company entity_id，如 "C:300308"

    Returns:
        公司画像摘要文本
    """
    # 1. 检查缓存
    cached = await get_summary(1, entity_id)
    if cached and not await is_stale(1, entity_id):
        return cached["summary"]

    # 2. 查询 Neo4j
    driver = await get_async_driver()
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (c:Company {entity_id: $eid})-[r:RELATES]->(n)
            RETURN n.name AS name,
                   labels(n) AS labels,
                   r.text AS text,
                   r.weight AS weight,
                   r.stmt_type AS stmt_type
            ORDER BY r.weight DESC
            LIMIT 50
            """,
            eid=entity_id,
        )
        records = await result.data()

    if not records:
        return f"实体 {entity_id} 暂无关联数据。"

    # 获取公司名称
    company_name = entity_id
    for r in records:
        if "Company" in r.get("labels", []):
            company_name = r.get("name", entity_id)
            break

    # 3. 构建 relations_text
    lines = []
    for r in records:
        stmt = r.get("stmt_type", "Fact")
        weight = r.get("weight", 0)
        lines.append(
            f"- [{stmt}] {r['name']} ({', '.join(r.get('labels', []))}): "
            f"{r.get('text', '')} (权重:{weight:.1f})"
        )
    relations_text = "\n".join(lines)

    # 4. LLM 生成
    prompt = L1_COMPANY_PROFILE_PROMPT.format(
        company_name=company_name,
        relations_text=relations_text,
    )
    summary = await chat_async(prompt, temperature=0.1)

    # 5. 缓存
    await put_summary(
        level=1,
        entity_id=entity_id,
        summary=summary.strip(),
        entity_name=company_name,
        entity_count=len(records),
    )

    return summary.strip()


# ── L2: 产品生态 ────────────────────────────────────────────


async def aggregate_l2(entity_id: str) -> str:
    """聚合 Product 关联的所有 Company 画像，生成产品生态摘要。

    Args:
        entity_id: Product entity_id，如 "P:ABCD1234"

    Returns:
        产品生态摘要文本
    """
    # 1. 检查缓存
    cached = await get_summary(2, entity_id)
    if cached and not await is_stale(2, entity_id):
        return cached["summary"]

    # 2. 查询 Neo4j — 获取关联的 Company
    driver = await get_async_driver()
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (p:Product {entity_id: $eid})<-[r:RELATES]-(c:Company)
            RETURN c.entity_id AS entity_id,
                   c.name AS name,
                   r.text AS text,
                   r.weight AS weight
            ORDER BY r.weight DESC
            LIMIT 30
            """,
            eid=entity_id,
        )
        records = await result.data()

        # 获取产品名称
        name_result = await session.run(
            "MATCH (p:Product {entity_id: $eid}) RETURN p.name AS name",
            eid=entity_id,
        )
        name_row = await name_result.single()
        product_name = name_row["name"] if name_row else entity_id

        # 获取产品间关系
        rel_result = await session.run(
            """
            MATCH (p:Product {entity_id: $eid})-[r:RELATES]-(other:Product)
            RETURN other.name AS name, r.text AS text, r.weight AS weight
            LIMIT 20
            """,
            eid=entity_id,
        )
        product_rels = await rel_result.data()

    if not records:
        return f"产品 {product_name} 暂无关联公司数据。"

    # 3. 获取各 Company 的 L1 摘要
    l1_summaries = []
    seen_companies = set()
    for r in records:
        cid = r["entity_id"]
        if cid in seen_companies:
            continue
        seen_companies.add(cid)
        try:
            l1_text = await aggregate_l1(cid)  # 递归获取 L1
        except Exception as e:
            logger.warning("L1 获取失败 [%s]: %s", cid, e)
            l1_text = f"{r['name']}: {r.get('text', '')}"
        l1_summaries.append(f"**{r['name']}** ({cid}): {l1_text}")

    # 4. 构建 product_relations
    rel_lines = []
    for pr in product_rels:
        rel_lines.append(f"- {product_name} ↔ {pr['name']}: {pr.get('text', '')} (权重:{pr.get('weight', 0):.1f})")

    # 5. LLM 生成
    prompt = L2_PRODUCT_ECOSYSTEM_PROMPT.format(
        product_name=product_name,
        l1_summaries="\n\n".join(l1_summaries),
        product_relations="\n".join(rel_lines) if rel_lines else "暂无",
    )
    summary = await chat_async(prompt, temperature=0.1)

    # 6. 缓存
    await put_summary(
        level=2,
        entity_id=entity_id,
        summary=summary.strip(),
        entity_name=product_name,
        entity_count=len(records),
    )

    return summary.strip()


# ── L3: 产业链视图（逐跳剪枝版）──────────────────────────────

_TOPK_PER_HOP = 10  # 每跳最多保留的关系数（按 weight 排序）


async def _l3_expand_hop(
    session: Any,
    entity_ids: list[str],
    current_depth: int,
    max_depth: int,
    visited: set[str],
    rel_lines: list[str],
) -> list[dict]:
    """执行单跳展开，按 weight 取 Top-K。

    递归剪枝策略：每跳只保留 weight 最高的 TOPK_PER_HOP 个关系，
    防止路径爆炸。设计文档 §8 要求此机制。
    """
    if current_depth > max_depth:
        return []

    found: list[dict] = []
    for eid in entity_ids:
        result = await session.run(
            """
            MATCH (p:Product {entity_id: $eid})-[r:RELATES]-(other:Product)
            WHERE other.entity_id <> $eid
            RETURN other.entity_id AS entity_id,
                   other.name AS name,
                   r.text AS text,
                   r.weight AS weight
            ORDER BY r.weight DESC
            LIMIT $topk
            """,
            eid=eid,
            topk=_TOPK_PER_HOP,
        )
        rows = await result.data()
        for row in rows:
            pid = row["entity_id"]
            if pid in visited:
                continue
            visited.add(pid)
            found.append({"entity_id": pid, "name": row["name"]})
            rel_lines.append(
                f"- {eid} ↔ {pid}: {row.get('text', '')} (权重:{row.get('weight', 0):.1f})"
            )

    # 递归下一跳
    if current_depth < max_depth and found:
        next_ids = [f["entity_id"] for f in found]
        deeper = await _l3_expand_hop(
            session, next_ids, current_depth + 1, max_depth, visited, rel_lines
        )
        found.extend(deeper)

    return found


async def aggregate_l3(entity_id: str, depth: int = 3) -> str:
    """从锚定 Product 出发，逐跳剪枝遍历，收集 L2 摘要，LLM 组织为产业链。

    Args:
        entity_id: Product entity_id
        depth: 遍历深度（默认 3，最大 3）

    Returns:
        产业链视图摘要文本

    Notes:
        - 每跳使用 TOPK_PER_HOP=10 剪枝（按 RELATES.weight 排序），
           避免路径爆炸（设计文档 §8 风险缓解）。
        - 递归展开而非单条 Cypher 路径查询，避免指数级中间结果。
    """
    depth = min(depth, 3)

    # 1. 检查缓存
    cached = await get_summary(3, entity_id, depth)
    if cached and not await is_stale(3, entity_id, depth):
        return cached["summary"]

    # 2. 递归展开 Product 路径（逐跳剪枝）
    driver = await get_async_driver()
    async with driver.session() as session:
        # 获取锚定 Product 名称
        name_result = await session.run(
            "MATCH (p:Product {entity_id: $eid}) RETURN p.name AS name",
            eid=entity_id,
        )
        name_row = await name_result.single()
        product_name = name_row["name"] if name_row else entity_id

        # 逐跳展开，收集所有 Product 节点 + 关系描述
        visited: set[str] = {entity_id}
        rel_lines: list[str] = []
        path_products = await _l3_expand_hop(
            session,
            [entity_id],
            current_depth=1,
            max_depth=depth,
            visited=visited,
            rel_lines=rel_lines,
        )

    # 3. 收集各 Product 的 L2 摘要（已访问的去重集合）
    l2_summaries = []
    all_products = [{"entity_id": entity_id, "name": product_name}] + [
        {"entity_id": p["entity_id"], "name": p["name"]}
        for p in path_products
        if p["entity_id"] != entity_id
    ]

    for p in all_products:
        pid = p["entity_id"]
        try:
            l2_text = await aggregate_l2(pid)
        except Exception as e:
            logger.warning("L2 获取失败 [%s]: %s", pid, e)
            l2_text = f"{p['name']}: 暂无生态摘要"
        l2_summaries.append(f"**{p['name']}** ({pid}): {l2_text}")

    # 4. LLM 生成
    prompt = L3_INDUSTRY_CHAIN_PROMPT.format(
        product_name=product_name,
        depth=depth,
        l2_summaries="\n\n".join(l2_summaries),
        relation_texts="\n".join(rel_lines) if rel_lines else "暂无",
    )
    summary = await chat_async(prompt, temperature=0.1)

    # 5. 缓存
    await put_summary(
        level=3,
        entity_id=entity_id,
        summary=summary.strip(),
        entity_name=product_name,
        entity_count=len(l2_summaries),
        depth=depth,
        extra={"segments": [p["name"] for p in all_products]},
    )

    return summary.strip()
