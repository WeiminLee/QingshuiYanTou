"""
KGSearchEngine — 统一知识图谱搜索引擎

RAGFlow 风格的搜索管线：
    query -> QueryClassifier.classify() -> SearchStrategy.select_strategy()
    -> execute_cypher() -> RelevanceScorer.rank_results() -> format_for_context()

设计参考 RAGFlow search.py KGSearch.retrieval()，
适配 Neo4j Cypher 查询模型。
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Annotated, Any

import tiktoken
from langchain_core.tools import tool

from app.reasoning.tools.knowledge.neo4j.query_classify import QueryClassifier, QueryIntent
from app.reasoning.tools.knowledge.neo4j.relevance import RelevanceScorer
from app.reasoning.tools.knowledge.neo4j.search_strategy import SearchStrategy, SearchStrategyEnum

logger = logging.getLogger(__name__)


_TS_CODE_PATTERN = re.compile(r"^\d{6}\.(SH|SZ|BJ)$", re.IGNORECASE)


def _looks_like_ts_code(s: str) -> bool:
    """判断字符串是否符合 ts_code 格式（6 位数字.交易所）。"""
    return bool(s) and bool(_TS_CODE_PATTERN.match(s))


# ── 数据模型 ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class KGSearchResult:
    """KG 搜索结果。"""

    results: list[dict[str, Any]] = field(default_factory=list)
    strategy: str = "unknown"
    query_analysis: QueryIntent = field(default_factory=QueryIntent)
    total: int = 0


# ── TTL 缓存 ────────────────────────────────────────────────────────


class _TTLCache:
    """简单的 TTL 缓存（线程安全）。"""

    def __init__(self, maxsize: int = 128, ttl_seconds: float = 300.0) -> None:
        self._maxsize = maxsize
        self._ttl = ttl_seconds
        self._store: dict[str, tuple[Any, float]] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Any | None:
        async with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            value, ts = entry
            if time.monotonic() - ts > self._ttl:
                del self._store[key]
                return None
            return value

    async def set(self, key: str, value: Any) -> None:
        async with self._lock:
            if len(self._store) >= self._maxsize:
                # 淘汰最旧的
                oldest_key = min(self._store, key=lambda k: self._store[k][1])
                del self._store[oldest_key]
            self._store[key] = (value, time.monotonic())


# 全局缓存实例
_search_cache = _TTLCache(maxsize=128, ttl_seconds=300.0)


# ── KGSearchEngine ──────────────────────────────────────────────────


class KGSearchEngine:
    """
    统一知识图谱搜索引擎。

    管线：query -> 分析 -> 策略选择 -> Cypher 执行 -> 评分排序 -> 格式化

    所有 Cypher 查询使用参数化语法（$param），防止注入。
    """

    def __init__(self, neo4j_client: Any) -> None:
        """
        初始化搜索引擎。

        Args:
            neo4j_client: Neo4jClient 实例（注入现有单例）
        """
        self._neo4j_client = neo4j_client
        self._classifier = QueryClassifier()
        self._scorer = RelevanceScorer()
        self._strategy = SearchStrategy()
        self._indexes_ensured = False

    async def _ensure_indexes(self) -> None:
        """
        创建 Neo4j 全文索引（如果不存在）。

        使用 CREATE FULLTEXT INDEX ... IF NOT EXISTS 语法。
        索引创建失败不阻断，仅记录警告。
        """
        if self._indexes_ensured:
            return

        try:
            index_query = """
            CREATE FULLTEXT INDEX entity_name_idx IF NOT EXISTS
            FOR (n:Entity|Company|Product|Sector)
            ON EACH [n.name, n.aliases]
            """
            await self._neo4j_client.execute_query(index_query)
            self._indexes_ensured = True
            logger.info("[KGSearchEngine] Full-text index 'entity_name_idx' ensured")
        except Exception as e:
            logger.warning(
                f"[KGSearchEngine] Failed to create full-text index: {e}. Search will fall back to CONTAINS queries."
            )
            # 标记为已尝试，避免重复尝试
            self._indexes_ensured = True

    async def search(
        self,
        query: str,
        max_results: int = 10,
        strategy_override: str | None = None,
    ) -> KGSearchResult:
        """
        执行知识图谱搜索。

        管线：query -> 分析 -> 策略选择 -> Cypher 执行 -> 评分排序

        Args:
            query: 自然语言查询
            max_results: 最大返回结果数
            strategy_override: 强制使用的搜索策略（跳过缓存）

        Returns:
            KGSearchResult 包含排序后的结果
        """
        # 确保索引已创建
        await self._ensure_indexes()

        # 查询分析
        query_analysis = self._classifier.extract_entities(query)

        # 策略选择
        if strategy_override:
            strategy_enum = self._resolve_strategy_override(strategy_override)
        else:
            strategy_enum = self._strategy.select_strategy(query_analysis.query_type)

        # 如果策略为 None（社区搜索暂不可用），回退到实体搜索
        if strategy_enum is None:
            strategy_enum = SearchStrategyEnum.ENTITY_SEARCH

        strategy_name = strategy_enum.value

        # 缓存检查（strategy_override 时跳过缓存）
        if strategy_override is None:
            cache_key = self._cache_key(query, strategy_name, max_results)
            cached = await _search_cache.get(cache_key)
            if cached is not None:
                logger.debug(f"[KGSearchEngine] Cache hit for query: {query}")
                return cached

        # 执行搜索
        try:
            raw_results = await self._execute_cypher(strategy_enum, query_analysis, max_results)
        except Exception as e:
            logger.warning(f"[KGSearchEngine] Search failed: {e}")
            raw_results = []

        # 评分排序
        ranked_results = self._scorer.rank_results(raw_results, query_analysis.entities)

        # 截断到 max_results
        final_results = ranked_results[:max_results]

        # 构建结果
        result = KGSearchResult(
            results=final_results,
            strategy=strategy_name,
            query_analysis=query_analysis,
            total=len(final_results),
        )

        # 写入缓存（strategy_override 时跳过缓存）
        if strategy_override is None:
            cache_key = self._cache_key(query, strategy_name, max_results)
            await _search_cache.set(cache_key, result)

        return result

    def format_for_context(
        self,
        results: KGSearchResult,
        max_tokens: int = 2000,
    ) -> str:
        """
        Token 感知的结果格式化。

        参考 RAGFlow kb_prompt() 的 token 预算模式。

        Args:
            results: 搜索结果
            max_tokens: 最大 token 数

        Returns:
            格式化的文本（不超过 max_tokens）
        """
        if not results.results:
            return ""

        enc = tiktoken.get_encoding("cl100k_base")
        parts: list[str] = []
        remaining = max_tokens

        for r in results.results:
            text = self._format_single_result(r)
            tokens = len(enc.encode(text))

            if tokens > remaining:
                # 截断到剩余预算
                truncated_tokens = enc.encode(text)[:remaining]
                truncated = enc.decode(truncated_tokens)
                parts.append(truncated)
                break

            parts.append(text)
            remaining -= tokens

        if not parts:
            return ""

        header = f"[知识图谱搜索 | 策略: {results.strategy} | 结果: {results.total}]"
        full_text = header + "\n\n" + "\n\n".join(parts)

        # 最终 token 检查
        total_tokens = len(enc.encode(full_text))
        if total_tokens > max_tokens:
            # 截断到预算
            all_tokens = enc.encode(full_text)[:max_tokens]
            full_text = enc.decode(all_tokens)

        return full_text

    # ── 私有方法 ──────────────────────────────────────────────────

    def _cache_key(self, query: str, strategy: str, max_results: int) -> str:
        """生成缓存键。"""
        raw = f"{query}:{strategy}:{max_results}"
        return hashlib.md5(raw.encode()).hexdigest()

    def _resolve_strategy_override(self, strategy_override: str) -> SearchStrategyEnum:
        """解析策略覆盖字符串。"""
        mapping = {
            "entity": SearchStrategyEnum.ENTITY_SEARCH,
            "relation": SearchStrategyEnum.RELATION_SEARCH,
            "path": SearchStrategyEnum.PATH_SEARCH,
            "community": SearchStrategyEnum.COMMUNITY_SEARCH,
        }
        return mapping.get(strategy_override, SearchStrategyEnum.ENTITY_SEARCH)

    async def _execute_cypher(
        self,
        strategy: SearchStrategyEnum,
        query_analysis: QueryIntent,
        max_results: int,
    ) -> list[dict[str, Any]]:
        """根据策略执行 Cypher 查询。"""
        if strategy == SearchStrategyEnum.ENTITY_SEARCH:
            return await self._search_entities(query_analysis.entities, max_results)
        elif strategy == SearchStrategyEnum.RELATION_SEARCH:
            return await self._search_relations(query_analysis.entities, max_results)
        elif strategy == SearchStrategyEnum.PATH_SEARCH:
            entities = query_analysis.entities
            from_entity = entities[0] if len(entities) >= 1 else ""
            to_entity = entities[1] if len(entities) >= 2 else ""
            return await self._search_path(from_entity, to_entity)
        elif strategy == SearchStrategyEnum.COMMUNITY_SEARCH:
            return await self._search_community(query_analysis.entities)
        else:
            return await self._search_entities(query_analysis.entities, max_results)

    async def _search_entities(
        self,
        entities: list[str],
        max_results: int,
    ) -> list[dict[str, Any]]:
        """
        实体搜索：优先尝试 entity_id/ts_code 直接匹配，再全文索引，回退 CONTAINS。

        所有 Cypher 使用参数化查询。
        """
        if not entities:
            return []

        # 快路径：尝试用 ts_code/entity_id 直接匹配（QueryClassifier 已解析）
        direct_results = await self._search_entities_by_id(entities, max_results)
        if direct_results:
            return direct_results

        # 构建搜索文本
        search_text = " OR ".join(entities)

        # 尝试全文索引搜索
        try:
            query = """
            CALL db.index.fulltext.queryNodes('entity_name_idx', $search_text)
            YIELD node, score
            RETURN node.name AS name,
                   labels(node) AS types,
                   COALESCE(node.rank, 0) AS rank,
                   node.description AS description,
                   score AS sim
            ORDER BY score DESC
            LIMIT $max_results
            """
            results = await self._neo4j_client.execute_query(
                query,
                search_text=search_text,
                max_results=max_results * 2,  # 多取一些用于重排
            )

            if results:
                # 用 rapidfuzz 重排
                return self._rerank_with_fuzz(results, entities, max_results)

        except Exception as e:
            logger.warning(f"[KGSearchEngine] Full-text index search failed: {e}. Falling back to CONTAINS query.")

        # 回退到 CONTAINS 查询
        return await self._search_entities_contains(entities, max_results)

    async def _search_entities_by_id(
        self,
        entities: list[str],
        max_results: int,
    ) -> list[dict[str, Any]]:
        """
        通过 ts_code 或 entity_id 直接匹配。
        当 QueryClassifier 已将名称解析为 ts_code 时（如 "688981.SH"），
        可以走这条快路径，避免全文索引/CONTAINS 的模糊匹配。
        """
        # 构建 ts_code 候选 + entity_id 候选
        ts_codes = [e for e in entities if _looks_like_ts_code(e)]
        entity_ids = [e for e in entities if e.startswith("C:") or e.startswith("CO:")]
        # 由 ts_code 派生的 entity_id（C:{ts_code}）
        entity_ids.extend(f"C:{ts}" for ts in ts_codes)

        if not ts_codes and not entity_ids:
            return []

        try:
            query = """
            MATCH (n)
            WHERE n.ts_code IN $ts_codes
               OR n.entity_id IN $entity_ids
            RETURN n.name AS name,
                   labels(n) AS types,
                   COALESCE(n.rank, 0) AS rank,
                   n.description AS description
            LIMIT $max_results
            """
            results = await self._neo4j_client.execute_query(
                query,
                ts_codes=ts_codes,
                entity_ids=entity_ids,
                max_results=max_results,
            )
            return list(results) if results else []
        except Exception as e:
            logger.warning(f"[KGSearchEngine] entity_id direct match failed: {e}")
            return []

    async def _search_entities_contains(
        self,
        entities: list[str],
        max_results: int,
    ) -> list[dict[str, Any]]:
        """CONTAINS 回退查询（全文索引不可用时）。"""
        if not entities:
            return []

        # 对每个实体执行 CONTAINS 查询（含 ts_code/entity_id 直接匹配）
        all_results: list[dict[str, Any]] = []

        for entity in entities:
            entity_id = f"C:{entity}" if _looks_like_ts_code(entity) else entity
            try:
                query = """
                MATCH (n)
                WHERE toLower(n.name) CONTAINS toLower($entity)
                   OR ANY(alias IN n.aliases WHERE toLower(alias) CONTAINS toLower($entity))
                   OR n.ts_code = $entity
                   OR n.entity_id = $entity_id
                RETURN n.name AS name,
                       labels(n) AS types,
                       COALESCE(n.rank, 0) AS rank,
                       n.description AS description
                LIMIT $max_results
                """
                results = await self._neo4j_client.execute_query(
                    query,
                    entity=entity,
                    entity_id=entity_id,
                    max_results=max_results,
                )
                all_results.extend(results)
            except Exception as e:
                logger.warning(f"[KGSearchEngine] CONTAINS search failed for '{entity}': {e}")

        # 去重
        seen_names: set[str] = set()
        unique_results: list[dict[str, Any]] = []
        for r in all_results:
            name = r.get("name", "")
            if name not in seen_names:
                seen_names.add(name)
                unique_results.append(r)

        return unique_results[:max_results]

    async def _search_relations(
        self,
        entities: list[str],
        max_results: int,
    ) -> list[dict[str, Any]]:
        """
        关系搜索：查找匹配实体的关系三元组。

        返回 (source, relation, target) 三元组，带权重。
        """
        if not entities:
            return []

        try:
            query = """
            MATCH (a)-[r:RELATES]->(b)
            WHERE a.name IN $entities
              AND r.weight >= $min_weight
            RETURN a.name AS from_entity,
                   r.text AS rel_text,
                   r.weight AS weight,
                   b.name AS to_entity,
                   COALESCE(b.rank, 1) AS to_rank
            ORDER BY r.weight DESC
            LIMIT $max_results
            """
            results = await self._neo4j_client.execute_query(
                query,
                entities=entities,
                min_weight=0.0,
                max_results=max_results,
            )
            return results or []
        except Exception as e:
            logger.warning(f"[KGSearchEngine] Relation search failed: {e}")
            return []

    async def _search_path(
        self,
        from_entity: str,
        to_entity: str,
        max_depth: int = 3,
    ) -> list[dict[str, Any]]:
        """
        路径搜索：查找两个实体之间的最短路径。

        使用参数化 Cypher 查询。
        """
        if not from_entity or not to_entity:
            return []

        try:
            safe_max = min(max_depth, 6)  # 上限 6 跳
            query = f"""
            MATCH (a), (b)
            WHERE toLower(a.name) CONTAINS toLower($from_entity)
              AND toLower(b.name) CONTAINS toLower($to_entity)
            MATCH p = shortestPath((a)-[*..{safe_max}]-(b))
            RETURN [node IN nodes(p) | node.name] AS path,
                   [rel IN relationships(p) | {{
                       type: type(rel),
                       text: COALESCE(rel.text, ''),
                       weight: COALESCE(rel.weight, 0)
                   }}] AS edges
            LIMIT 3
            """
            results = await self._neo4j_client.execute_query(
                query,
                from_entity=from_entity,
                to_entity=to_entity,
            )
            return results or []
        except Exception as e:
            logger.warning(f"[KGSearchEngine] Path search failed: {e}")
            return []

    async def _search_community(
        self,
        entities: list[str],
    ) -> list[dict[str, Any]]:
        """
        社区搜索：暂不可用，返回空列表并记录警告。

        社区数据需要 P3（Leiden 社区检测）完成后才可用。
        """
        logger.warning(
            "[KGSearchEngine] Community search not available. "
            "Community data requires P3 (Leiden community detection) to be completed."
        )
        return []

    def _rerank_with_fuzz(
        self,
        results: list[dict[str, Any]],
        query_entities: list[str],
        max_results: int,
    ) -> list[dict[str, Any]]:
        """使用 rapidfuzz 对全文索引结果进行重排。"""
        try:
            from rapidfuzz import fuzz

            scored = []
            for r in results:
                name = r.get("name", "")
                # 计算与查询实体的最佳相似度
                best_sim = 0.0
                for qe in query_entities:
                    sim = fuzz.token_sort_ratio(qe, name) / 100.0
                    best_sim = max(best_sim, sim)

                # 更新 sim 字段
                new_r = dict(r)
                new_r["sim"] = best_sim
                scored.append(new_r)

            # 按 sim * rank 排序
            scored.sort(
                key=lambda x: x.get("sim", 0) * x.get("rank", 1),
                reverse=True,
            )
            return scored[:max_results]

        except ImportError:
            logger.warning("[KGSearchEngine] rapidfuzz not available, skipping reranking")
            return results[:max_results]

    def _format_single_result(self, result: dict[str, Any]) -> str:
        """格式化单个搜索结果。"""
        name = result.get("name", "Unknown")
        score = result.get("_relevance_score", 0)
        score_str = f" [相关性: {score:.3f}]" if score else ""

        lines = [f"**{name}**{score_str}"]

        # 类型
        types = result.get("types", [])
        if types:
            type_str = "/".join(str(t) for t in types if t and t != "Entity")
            if type_str:
                lines.append(f"  类型: {type_str}")

        # 描述
        description = result.get("description", "")
        if description:
            lines.append(f"  描述: {description[:200]}")

        # 关系信息
        from_entity = result.get("from_entity", "")
        to_entity = result.get("to_entity", "")
        rel_text = result.get("rel_text", "")
        weight = result.get("weight", 0)

        if from_entity and to_entity:
            weight_str = f" [权重: {weight:.2f}]" if weight else ""
            lines.append(f"  关系: {from_entity} -> {to_entity}{weight_str}")
            if rel_text:
                lines.append(f"  {rel_text[:150]}")

        # 路径信息
        path = result.get("path", [])
        if path:
            path_str = " -> ".join(str(n) for n in path)
            lines.append(f"  路径: {path_str}")

        return "\n".join(lines)


# ── @tool 包装函数 ──────────────────────────────────────────────────


@tool("neo4j_kg_search")
def neo4j_kg_search(
    query: Annotated[str, "自然语言搜索查询"],
    max_results: Annotated[int, "最大返回结果数"] = 10,
) -> str:
    """知识图谱智能搜索：自动选择实体/关系/路径搜索策略，返回相关性排序的结果"""
    try:
        asyncio.get_running_loop()
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor() as pool:
            fut = pool.submit(asyncio.run, _akg_search_impl(query, max_results))
            return fut.result()
    except RuntimeError:
        return asyncio.run(_akg_search_impl(query, max_results))


async def _akg_search_impl(query: str, max_results: int) -> str:
    """KG 搜索异步实现。"""
    try:
        from app.core.neo4j_client import get_neo4j_client

        neo4j_client = get_neo4j_client()
        engine = KGSearchEngine(neo4j_client)
        result = await engine.search(query, max_results=max_results)

        if not result.results:
            return f"知识图谱搜索「{query}」暂无结果。"

        # 格式化输出
        lines = ["## 知识图谱搜索结果\n"]
        lines.append(f"查询: {query}")
        lines.append(f"策略: {result.strategy}")
        lines.append(f"结果数: {result.total}\n")

        for i, r in enumerate(result.results, 1):
            name = r.get("name", "Unknown")
            score = r.get("_relevance_score", 0)
            score_str = f" [相关性: {score:.3f}]" if score else ""

            lines.append(f"**{i}. {name}**{score_str}")

            # 类型
            types = r.get("types", [])
            if types:
                type_str = "/".join(str(t) for t in types if t and t != "Entity")
                if type_str:
                    lines.append(f"  类型: {type_str}")

            # 描述
            description = r.get("description", "")
            if description:
                lines.append(f"  描述: {description[:200]}")

            # 关系
            from_entity = r.get("from_entity", "")
            to_entity = r.get("to_entity", "")
            if from_entity and to_entity:
                rel_text = r.get("rel_text", "")
                weight = r.get("weight", 0)
                weight_str = f" [权重: {weight:.2f}]" if weight else ""
                lines.append(f"  关系: {from_entity} -> {to_entity}{weight_str}")
                if rel_text:
                    lines.append(f"  {rel_text[:150]}")

            # 路径
            path = r.get("path", [])
            if path:
                path_str = " -> ".join(str(n) for n in path)
                lines.append(f"  路径: {path_str}")

            lines.append("")

        return "\n".join(lines)

    except Exception as e:
        logger.warning(f"[neo4j_kg_search] failed: {e}")
        return f"知识图谱搜索失败：{e}"
