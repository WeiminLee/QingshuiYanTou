"""
SearchStrategy — 自适应搜索策略选择

根据查询类型选择最佳搜索路径：
- ENTITY_SEARCH: 实体搜索（全文索引 + 模糊匹配）
- RELATION_SEARCH: 关系搜索（多跳遍历 + 权重排序）
- PATH_SEARCH: 路径搜索（最短路径查询）
- COMMUNITY_SEARCH: 社区搜索（暂不可用，优雅降级）
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any

from app.reasoning.tools.knowledge.neo4j.query_classify import QueryIntent

logger = logging.getLogger(__name__)


class SearchStrategyEnum(Enum):
    """搜索策略枚举。"""

    ENTITY_SEARCH = "entity"
    RELATION_SEARCH = "relation"
    PATH_SEARCH = "path"
    COMMUNITY_SEARCH = "community"


# 查询类型 -> 搜索策略映射
_STRATEGY_MAP: dict[str, SearchStrategyEnum | None] = {
    "entity_search": SearchStrategyEnum.ENTITY_SEARCH,
    "entity_relation": SearchStrategyEnum.RELATION_SEARCH,
    "path_finding": SearchStrategyEnum.PATH_SEARCH,
    "industry_state": SearchStrategyEnum.ENTITY_SEARCH,
    "community": SearchStrategyEnum.COMMUNITY_SEARCH,
}


class SearchStrategy:
    """
    自适应搜索策略选择器。

    根据查询类型选择最佳搜索路径。
    社区搜索暂不可用，返回 None 并记录警告。
    """

    def select_strategy(self, query_type: str) -> SearchStrategyEnum | None:
        """
        根据查询类型选择搜索策略。

        Args:
            query_type: 查询类型（来自 QueryClassifier）

        Returns:
            搜索策略枚举值，社区搜索返回 None
        """
        strategy = _STRATEGY_MAP.get(query_type)

        if strategy == SearchStrategyEnum.COMMUNITY_SEARCH:
            logger.warning(
                "[SearchStrategy] Community data not available. "
                "Community search requires P3 (Leiden community detection) to be completed."
            )
            return None

        if strategy is None:
            # 未知查询类型，默认实体搜索
            logger.info(f"[SearchStrategy] Unknown query type '{query_type}', falling back to ENTITY_SEARCH")
            return SearchStrategyEnum.ENTITY_SEARCH

        return strategy

    def get_search_params(
        self,
        strategy: SearchStrategyEnum,
        query_analysis: QueryIntent,
    ) -> dict[str, Any]:
        """
        获取搜索参数。

        根据策略返回 Cypher 模板名称和查询参数。

        Args:
            strategy: 搜索策略
            query_analysis: 查询分析结果

        Returns:
            包含模板名称和参数的字典
        """
        if strategy == SearchStrategyEnum.ENTITY_SEARCH:
            return {
                "template": "entity_search",
                "entities": query_analysis.entities,
                "query_type": query_analysis.query_type,
            }
        elif strategy == SearchStrategyEnum.RELATION_SEARCH:
            return {
                "template": "relation_search",
                "entities": query_analysis.entities,
                "query_type": query_analysis.query_type,
            }
        elif strategy == SearchStrategyEnum.PATH_SEARCH:
            entities = query_analysis.entities
            return {
                "template": "path_search",
                "from_entity": entities[0] if len(entities) >= 1 else "",
                "to_entity": entities[1] if len(entities) >= 2 else "",
                "query_type": query_analysis.query_type,
            }
        elif strategy == SearchStrategyEnum.COMMUNITY_SEARCH:
            return {
                "template": "community_search",
                "entities": query_analysis.entities,
                "query_type": query_analysis.query_type,
            }
        else:
            return {
                "template": "entity_search",
                "entities": query_analysis.entities,
                "query_type": query_analysis.query_type,
            }
