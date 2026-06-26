"""
RelevanceScorer — 多维度相关性评分

使用 RAGFlow 的乘法公式计算复合相关性分数：
    score = sim * pagerank * type_boost * recency

参考 RAGFlow search.py lines 194-222 的 P(E|Q) 公式。
"""

from __future__ import annotations

import logging
import math
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

# 时间衰减系数（RAGFlow 默认值）
_DEFAULT_LAMBDA = 0.005


class RelevanceScorer:
    """
    多维度相关性评分器。

    使用 RAGFlow 的乘法公式：
        score = sim * pagerank * type_boost * recency

    其中：
        - sim: 语义/文本相似度 [0, 1]
        - pagerank: 节点度或权重 [0, inf)
        - type_boost: 类型匹配加成（匹配=2.0，不匹配=1.0）
        - recency: 时间衰减因子 [0, 1]
    """

    def __init__(self, time_decay: bool = False, lambda_decay: float = _DEFAULT_LAMBDA) -> None:
        """
        初始化评分器。

        Args:
            time_decay: 是否启用时间衰减
            lambda_decay: 时间衰减系数（默认 0.005）
        """
        self._time_decay = time_decay
        self._lambda = lambda_decay

    def composite_score(
        self,
        sim: float,
        pagerank: float,
        type_boost: float = 1.0,
        recency: float = 1.0,
    ) -> float:
        """
        计算复合相关性分数（RAGFlow 乘法公式）。

        Args:
            sim: 语义/文本相似度 [0, 1]
            pagerank: 节点度或权重 [0, inf)
            type_boost: 类型匹配加成（默认 1.0，匹配时 2.0）
            recency: 时间衰减因子 [0, 1]（默认 1.0）

        Returns:
            复合相关性分数
        """
        # RAGFlow multiplicative formula
        return sim * pagerank * type_boost * recency

    def compute_recency(self, update_time: datetime | None) -> float:
        """
        计算时间衰减因子。

        使用指数衰减：recency = exp(-lambda * days_since_update)

        Args:
            update_time: 实体更新时间

        Returns:
            时间衰减因子 [0, 1]
        """
        if update_time is None:
            return 1.0

        now = datetime.now()
        if update_time > now:
            return 1.0

        days_since_update = (now - update_time).days
        return math.exp(-self._lambda * days_since_update)

    def score_nhop_paths(
        self,
        entity_results: dict[str, Any],
    ) -> dict[tuple[str, str], float]:
        """
        对 n-hop 路径进行距离衰减评分。

        参考 RAGFlow search.py lines 172-187。

        对于路径中位置 i 的边 (A, B)：
            score += entity_sim / (2 + i)

        Args:
            entity_results: 实体结果字典，每个实体包含 n_hop_ents 路径列表

        Returns:
            边元组 (from_entity, to_entity) -> 累积分数
        """
        nhop_scores: dict[tuple[str, str], float] = {}

        for ent_name, ent in entity_results.items():
            # 获取实体相似度
            sim = getattr(ent, "sim", 1.0)
            if isinstance(ent, dict):
                sim = ent.get("sim", 1.0)

            # 获取 n-hop 路径
            n_hop_ents = getattr(ent, "n_hop_ents", [])
            if isinstance(ent, dict):
                n_hop_ents = ent.get("n_hop_ents", [])

            for path_entry in n_hop_ents:
                path = path_entry.get("path", [])
                if len(path) < 2:
                    continue

                # 对路径中的每条边计算距离衰减分数
                for i in range(len(path) - 1):
                    f, t = path[i], path[i + 1]
                    # 使用排序后的元组作为键（无向边）
                    key = tuple(sorted([f, t]))
                    decay = sim / (2 + i)  # 距离衰减
                    nhop_scores[key] = nhop_scores.get(key, 0.0) + decay

        return nhop_scores

    def rank_results(
        self,
        results: list[dict[str, Any]],
        query_entities: list[str],
    ) -> list[dict[str, Any]]:
        """
        对结果按复合分数排序。

        为每个结果添加 _relevance_score 字段。

        Args:
            results: 结果列表，每个结果包含 sim、pagerank 等字段
            query_entities: 查询实体列表（用于类型加成）

        Returns:
            按 _relevance_score 降序排序的结果列表
        """
        scored_results = []

        for r in results:
            # 提取字段
            sim = r.get("sim", 1.0)
            pagerank = r.get("pagerank", r.get("rank", 1.0))
            type_boost = 1.0
            recency = r.get("recency", 1.0)

            # 计算类型加成
            name = r.get("name", "")
            for qe in query_entities:
                if qe in name or name in qe:
                    type_boost = 2.0
                    break

            # 计算复合分数
            score = self.composite_score(sim, pagerank, type_boost, recency)

            # 创建新字典（不可变更新）
            scored = dict(r)
            scored["_relevance_score"] = score
            scored_results.append(scored)

        # 按分数降序排序
        return sorted(scored_results, key=lambda x: x.get("_relevance_score", 0), reverse=True)

    def type_boost_for_match(self, entity_type: str, query_type: str) -> float:
        """
        计算类型匹配加成。

        参考 RAGFlow search.py lines 194-199。

        Args:
            entity_type: 实体类型
            query_type: 查询类型

        Returns:
            类型加成（匹配=2.0，不匹配=1.0）
        """
        if not entity_type or not query_type:
            return 1.0

        # 简化匹配：类型名称包含关系
        if entity_type.lower() in query_type.lower() or query_type.lower() in entity_type.lower():
            return 2.0

        return 1.0
