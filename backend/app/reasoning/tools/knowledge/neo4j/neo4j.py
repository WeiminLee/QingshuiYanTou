"""
Neo4j Graph Tools — 云端 API 版

知识图谱查询工具集，数据来源：Neo4j 图数据库。
包含：neo4j_traverse / neo4j_entity_info / neo4j_path / neo4j_industry_state
"""
import asyncio
import logging
from typing import Annotated

from langchain_core.tools import tool

logger = logging.getLogger(__name__)


# ── neo4j_traverse ─────────────────────────────────────────────────


@tool("neo4j_traverse")
def neo4j_traverse(
    entity: Annotated[str, "实体名称（公司名、产品名等）"],
    hops: Annotated[int, "遍历跳数：1=直接关系，2=传导链。默认1。"] = 1,
    rel_type: Annotated[str, "关系类型过滤（如 RELATES / SUPPLIES_TO）。不填则返回所有关系。"] = "",
    query_mode: Annotated[
        str,
        "查询模式：auto=自动检测，typed=仅查类型边，relates=仅查RELATES边。默认auto。"
    ] = "auto",
    min_weight: Annotated[float, "RELATES边最小权重（0-1）。默认0。"] = 0.0,
) -> str:
    """
    查询知识图谱中实体间的关系（1-hop 或 2-hop 传导链）。
    用于了解公司供应商、客户、竞争对手、产业链上下游等关系网络。

    query_mode 说明：
    - auto：先查 typed 边，无结果则 fallback 到 RELATES 边
    - typed：仅查询类型化边（type(r) = 'XXX'）
    - relates：仅查询统一 RELATES 边（带 weight + text 属性）

    BUG-3 修复：使用 asyncio.get_event_loop() + run_until_complete() 替代 asyncio.run()，
    避免嵌套事件循环问题。
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # 无运行中的事件循环，创建新的
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(
            _atraverse_impl(entity, hops, rel_type, query_mode, min_weight)
        )
        loop.close()
        return result

    # 在已有事件循环中，使用 run_in_executor 避免阻塞
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor() as pool:
        future = pool.submit(
            lambda: loop.run_until_complete(
                _atraverse_impl(entity, hops, rel_type, query_mode, min_weight)
            )
        )
        return future.result()


async def _atraverse_impl(
    entity: str,
    hops: int,
    rel_type: str,
    query_mode: str = "auto",
    min_weight: float = 0.0,
) -> str:
    """V2 Schema 兼容的关系遍历实现。"""
    try:
        from app.core.neo4j_client import get_async_driver
        driver = await get_async_driver()
        async with driver.session() as session:
            if hops >= 2:
                # 2-hop 查询
                query = """
                MATCH (a)-[r1]->(mid)-[r2]->(b)
                WHERE toLower(a.name) CONTAINS toLower($entity)
                """
                if rel_type:
                    query += " AND type(r1) = $rel_type AND type(r2) = $rel_type"
                query += """
                RETURN a.name AS src, type(r1) AS rel1,
                       mid.name AS mid_node,
                       type(r2) AS rel2,
                       b.name AS tgt,
                       r1.description AS desc1,
                       r2.description AS desc2
                LIMIT 10
                """
                records = await session.run(query, entity=entity, rel_type=rel_type)
            else:
                # 1-hop 查询 — V2 Schema 支持
                if query_mode == "relates" or (query_mode == "auto" and not rel_type):
                    # V2 Schema: RELATES 边
                    query = """
                    MATCH (a)-[r:RELATES]->(b)
                    WHERE toLower(a.name) CONTAINS toLower($entity)
                      AND ($min_weight <= 0.0 OR r.weight >= $min_weight)
                    RETURN a.name AS src, 'RELATES' AS rel_type,
                           r.text AS rel_text,
                           r.weight AS weight,
                           b.name AS tgt, labels(b) AS target_labels
                    ORDER BY r.weight DESC
                    LIMIT 15
                    """
                    records = await session.run(query, entity=entity, min_weight=min_weight)
                elif query_mode == "typed" or (query_mode == "auto" and rel_type):
                    # 旧版 typed 边
                    query = """
                    MATCH (a)-[r]->(b)
                    WHERE toLower(a.name) CONTAINS toLower($entity)
                    """
                    if rel_type:
                        query += " AND type(r) = $rel_type"
                    query += """
                    RETURN a.name AS src, type(r) AS rel_type,
                           r.description AS description,
                           b.name AS tgt, r.weight AS weight
                    LIMIT 15
                    """
                    records = await session.run(query, entity=entity, rel_type=rel_type)
                else:
                    # auto 模式：先 typed，无结果则 relates
                    typed_query = """
                    MATCH (a)-[r]->(b)
                    WHERE toLower(a.name) CONTAINS toLower($entity)
                    """
                    if rel_type:
                        typed_query += " AND type(r) = $rel_type"
                    typed_query += """
                    RETURN a.name AS src, type(r) AS rel_type,
                           r.description AS description,
                           b.name AS tgt, r.weight AS weight
                    LIMIT 15
                    """
                    typed_records = await session.run(typed_query, entity=entity, rel_type=rel_type)
                    typed_data = await typed_records.data()

                    if typed_data:
                        records = typed_records
                    else:
                        # Fallback to RELATES
                        relates_query = """
                        MATCH (a)-[r:RELATES]->(b)
                        WHERE toLower(a.name) CONTAINS toLower($entity)
                          AND ($min_weight <= 0.0 OR r.weight >= $min_weight)
                        RETURN a.name AS src, 'RELATES' AS rel_type,
                               r.text AS rel_text,
                               r.weight AS weight,
                               b.name AS tgt, labels(b) AS target_labels
                        ORDER BY r.weight DESC
                        LIMIT 15
                        """
                        records = await session.run(relates_query, entity=entity, min_weight=min_weight)

            data = await records.data()
            return _format(entity, hops, data)
    except Exception as e:
        logger.warning(f"[Neo4jTraverseTool] failed: {e}")
        return f"图谱查询失败：{e}"


# ── neo4j_entity_info ──────────────────────────────────────────────


@tool("neo4j_entity_info")
def neo4j_entity_info(
    entity: Annotated[str, "实体名称（公司名、产品名等）"],
) -> str:
    """查询实体的详细属性（行业状态、信号、置信度、别名等）。用于了解某个公司或产品的完整画像。"""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(_aentity_info_impl(entity))
        loop.close()
        return result

    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor() as pool:
        future = pool.submit(
            lambda: loop.run_until_complete(_aentity_info_impl(entity))
        )
        return future.result()


async def _aentity_info_impl(entity: str) -> str:
    """查询实体详细属性。"""
    try:
        from app.core.neo4j_client import get_async_driver
        driver = await get_async_driver()
        async with driver.session() as session:
            query = """
            MATCH (n)
            WHERE toLower(n.name) CONTAINS toLower($entity)
               OR ANY(alias IN coalesce(n.aliases, []) WHERE toLower(alias) CONTAINS toLower($entity))
            RETURN n.name AS name,
                   labels(n) AS labels,
                   n.industry_state AS industry_state,
                   n.signals AS signals,
                   n.aliases AS aliases,
                   n.confidence AS confidence,
                   n.description AS description
            LIMIT 5
            """
            records = await session.run(query, entity=entity)
            data = await records.data()
            return _format_entity_info(data)
    except Exception as e:
        logger.warning(f"[Neo4jEntityInfoTool] failed: {e}")
        return f"实体信息查询失败：{e}"


# ── neo4j_path ───────────────────────────────────────────────────


@tool("neo4j_path")
def neo4j_path(
    start: Annotated[str, "起点实体名称"],
    end: Annotated[str, "终点实体名称"],
    max_hops: Annotated[int, "最大跳数。默认3。"] = 3,
) -> str:
    """查询两个实体之间的传导路径（最多 N 跳）。用于分析产业链上下游传导关系。"""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(_apath_impl(start, end, max_hops))
        loop.close()
        return result

    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor() as pool:
        future = pool.submit(
            lambda: loop.run_until_complete(_apath_impl(start, end, max_hops))
        )
        return future.result()


async def _apath_impl(start: str, end: str, max_hops: int) -> str:
    """查询实体间传导路径。"""
    try:
        from app.core.neo4j_client import get_async_driver
        driver = await get_async_driver()
        async with driver.session() as session:
            # 使用 shortestPath 查找最短路径
            query = """
            MATCH p = shortestPath(
              (a)-[*..$max_hops]-(b)
            )
            WHERE toLower(a.name) CONTAINS toLower($start)
              AND toLower(b.name) CONTAINS toLower($end)
            RETURN [node IN nodes(p) | node.name] AS path_nodes,
                   [rel IN relationships(p) | {
                     type: type(rel),
                     text: coalesce(rel.text, rel.description, type(rel)),
                     weight: coalesce(rel.weight, 1.0)
                   }] AS edges,
                   length(p) AS hops
            LIMIT 3
            """
            records = await session.run(query, start=start, end=end, max_hops=max_hops)
            data = await records.data()
            return _format_path(data)
    except Exception as e:
        logger.warning(f"[Neo4jPathTool] failed: {e}")
        return f"路径查询失败：{e}"


# ── neo4j_industry_state ─────────────────────────────────────────


@tool("neo4j_industry_state")
def neo4j_industry_state(
    industry: Annotated[str, "行业名称（如光通信、光伏、锂电等）"],
) -> str:
    """查询行业内各公司的状态分布和信号。用于了解行业景气度和竞争格局。"""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(_aindustry_state_impl(industry))
        loop.close()
        return result

    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor() as pool:
        future = pool.submit(
            lambda: loop.run_until_complete(_aindustry_state_impl(industry))
        )
        return future.result()


async def _aindustry_state_impl(industry: str) -> str:
    """查询行业状态分布。"""
    try:
        from app.core.neo4j_client import get_async_driver
        driver = await get_async_driver()
        async with driver.session() as session:
            query = """
            MATCH (c:Company)-[:BELONGS_TO]->(i:Industry)
            WHERE toLower(i.name) CONTAINS toLower($industry)
            RETURN c.name AS company,
                   c.industry_state AS state,
                   c.signals AS signals,
                   c.confidence AS confidence
            ORDER BY c.name
            """
            records = await session.run(query, industry=industry)
            data = await records.data()
            return _format_industry_state(industry, data)
    except Exception as e:
        logger.warning(f"[Neo4jIndustryStateTool] failed: {e}")
        return f"行业状态查询失败：{e}"


# ── 格式化 ───────────────────────────────────────────────────────


def _format(entity: str, hops: int, data: list) -> str:
    if not data:
        return f"实体「{entity}」在知识图谱中暂无记录。"
    lines = [f"## 知识图谱查询结果\n"]
    if hops == 1:
        lines.append(f"实体「{entity}」的直接关系（{len(data)} 条）：\n")
        for r in data:
            rel_type = r.get("rel_type", "RELATES")
            weight = r.get("weight")
            weight_str = f" (权重:{weight:.2f})" if weight is not None else ""

            if rel_type == "RELATES":
                # V2 schema RELATES 边
                rel_text = r.get("rel_text", "")
                lines.append(
                    f"- **{r.get('src', '')}** --[RELATES{weight_str}]--> "
                    f"**{r.get('tgt', '')}**"
                )
                if rel_text:
                    lines.append(f"  {rel_text[:100]}")
            else:
                # Typed 边
                description = r.get("description", "")
                lines.append(
                    f"- **{r.get('src', '')}** --[{rel_type}]--> "
                    f"**{r.get('tgt', '')}**"
                )
                if description:
                    lines.append(f"  {description[:100]}")
    else:
        lines.append(f"实体「{entity}」的2-hop传导链（{len(data)} 条）：\n")
        for r in data:
            lines.append(
                f"- {r.get('src', '')} → {r.get('mid_node', '')} → {r.get('tgt', '')}"
                f"（{r.get('rel1', '')} / {r.get('rel2', '')}）"
            )
            if r.get("desc1"):
                lines.append(f"  {r.get('desc1', '')[:80]}")
    return "\n".join(lines)


def _format_entity_info(data: list) -> str:
    if not data:
        return "未找到匹配的实体信息。"
    lines = ["## 实体详细信息\n"]
    for r in data:
        lines.append(f"### {r.get('name', '未知')}")
        lines.append(f"- 类型: {', '.join(r.get('labels', [])) or '未知'}")
        if r.get("industry_state"):
            lines.append(f"- 行业状态: {r.get('industry_state')}")
        if r.get("signals"):
            signals = r.get("signals", [])
            if isinstance(signals, list):
                lines.append(f"- 信号: {', '.join(str(s) for s in signals)}")
            else:
                lines.append(f"- 信号: {signals}")
        if r.get("aliases"):
            aliases = r.get("aliases", [])
            if isinstance(aliases, list):
                lines.append(f"- 别名: {', '.join(str(a) for a in aliases)}")
        if r.get("confidence"):
            lines.append(f"- 置信度: {r.get('confidence')}")
        if r.get("description"):
            lines.append(f"- 描述: {r.get('description')[:200]}")
        lines.append("")
    return "\n".join(lines).strip()


def _format_path(data: list) -> str:
    if not data:
        return "未找到连接路径。"
    lines = ["## 传导路径查询结果\n"]
    for r in data:
        path_nodes = r.get("path_nodes", [])
        edges = r.get("edges", [])
        hops = r.get("hops", 0)
        lines.append(f"路径（{hops} 跳）：")
        for i, node in enumerate(path_nodes):
            lines.append(f"  {i+1}. {node}")
            if i < len(edges):
                edge = edges[i]
                weight = edge.get("weight", 1.0)
                lines.append(
                    f"     ─[{edge.get('type', 'RELATES')}]─ "
                    f"{edge.get('text', '')} "
                    f"(w={weight:.2f})"
                )
        lines.append("")
    return "\n".join(lines).strip()


def _format_industry_state(industry: str, data: list) -> str:
    if not data:
        return f"行业「{industry}」暂无状态数据。"
    lines = [f"## 行业状态 — {industry}\n"]
    state_summary = {}
    for r in data:
        company = r.get("company", "未知")
        state = r.get("state") or "未知"
        signals = r.get("signals", [])
        confidence = r.get("confidence")

        # 统计状态分布
        state_summary[state] = state_summary.get(state, 0) + 1

        lines.append(f"### {company}")
        lines.append(f"- 状态: {state}")
        if signals:
            if isinstance(signals, list):
                lines.append(f"- 信号: {', '.join(str(s) for s in signals)}")
            else:
                lines.append(f"- 信号: {signals}")
        if confidence:
            lines.append(f"- 置信度: {confidence}")
        lines.append("")

    # 状态分布摘要
    if state_summary:
        summary_parts = [f"{k}({v}家)" for k, v in sorted(state_summary.items())]
        lines.append(f"**状态分布**: {', '.join(summary_parts)}")

    return "\n".join(lines).strip()
