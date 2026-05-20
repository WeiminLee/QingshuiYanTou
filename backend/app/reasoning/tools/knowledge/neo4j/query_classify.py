"""
QueryClassifier — 规则驱动的查询分类与实体提取

从自然语言查询中提取实体并分类查询意图。
不依赖 LLM，使用确定性规则匹配（正则 + 关键词映射）。

设计参考 RAGFlow query_analyze_prompt.py，但 P0 版本不使用 LLM。
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class QueryIntent:
    """查询意图分析结果。"""
    entities: list[str] = field(default_factory=list)
    query_type: str = "entity_search"
    intent: str = "find_entity"


# ── 实体识别 patterns ──────────────────────────────────────────────

# 股票代码：6位数字.交易所（不用 \b，中文语境下不生效）
_STOCK_CODE_PATTERN = re.compile(r"(\d{6})\.(SH|SZ|BJ)")

# 公司名称模式：X+常见后缀
_COMPANY_SUFFIXES = re.compile(
    r"([一-鿿]{2,6})"
    r"(?:股份|集团|科技|电子|医药|能源|材料|智能|信息|通信|生物|电气|机械|汽车|化工|钢铁|矿业|建设|发展|投资|控股)"
)

# 行业关键词
_INDUSTRY_KEYWORDS = [
    "新能源", "半导体", "医药", "光伏", "锂电", "储能", "碳化硅",
    "人工智能", "AI", "芯片", "光通信", "光模块", "激光雷达", "CPO", "硅光",
    "功率半导体", "HBM", "先进封装", "机器人", "减速器", "传感器",
    "消费电子", "白酒", "食品饮料", "银行", "保险", "证券", "房地产",
    "军工", "航空航天", "新能源汽车", "充电桩", "风电", "核电",
    "5G", "物联网", "云计算", "大数据", "区块链", "数字货币",
    "稀土", "有色金属", "钢铁", "煤炭", "石油", "化工",
]

# 关系查询关键词
_RELATION_KEYWORDS = [
    "关系", "关联", "联系", "影响", "供应商", "客户", "合作伙伴",
    "竞争对手", "上下游", "产业链", "供应链", "传导",
]

# 路径查询关键词
_PATH_KEYWORDS = [
    "路径", "连接", "从.*到", "之间", "和.*的关系", "与.*的关系",
]

# 行业状态查询关键词
_STATE_KEYWORDS = [
    "行业", "现状", "趋势", "概况", "动态", "发展", "前景", "展望",
    "板块", "领域", "赛道", "景气度",
]


class QueryClassifier:
    """
    规则驱动的查询分类器。

    从自然语言查询中提取实体并分类查询意图。
    不依赖 LLM，使用确定性规则匹配。
    """

    def __init__(self) -> None:
        # 编译行业关键词为正则
        self._industry_pattern = re.compile(
            "|".join(re.escape(kw) for kw in _INDUSTRY_KEYWORDS)
        )
        # 编译关系关键词
        self._relation_pattern = re.compile(
            "|".join(re.escape(kw) for kw in _RELATION_KEYWORDS)
        )
        # 编译路径关键词
        self._path_pattern = re.compile(
            "|".join(_PATH_KEYWORDS)
        )
        # 编译状态关键词
        self._state_pattern = re.compile(
            "|".join(re.escape(kw) for kw in _STATE_KEYWORDS)
        )

    def extract_entities(self, query: str) -> QueryIntent:
        """
        从查询中提取实体并分类意图。

        Args:
            query: 自然语言查询

        Returns:
            QueryIntent 包含提取的实体、查询类型和意图
        """
        entities = self._extract_entity_list(query)
        # 解析名称到 ts_code（PostgreSQL 主源），便于 Neo4j 直接匹配
        entities = self._resolve_to_ts_codes(entities)
        query_type, intent = self._classify_intent(query, entities)

        return QueryIntent(
            entities=entities,
            query_type=query_type,
            intent=intent,
        )

    @staticmethod
    def _resolve_to_ts_codes(entities: list[str]) -> list[str]:
        """
        把可解析的名称替换为 ts_code（如"中芯" → "688981.SH"），
        无法解析的保留原值。
        """
        if not entities:
            return entities
        try:
            from app.knowledge.stock_name_resolver import get_stock_name_resolver
            resolver = get_stock_name_resolver()
        except Exception as e:
            logger.warning("StockNameResolver 不可用，跳过 ts_code 解析: %s", e)
            return entities

        resolved: list[str] = []
        for entity in entities:
            ts_code = resolver.resolve(entity)
            resolved.append(ts_code if ts_code else entity)
        return resolved

    def _extract_entity_list(self, query: str) -> list[str]:
        """从查询中提取实体列表。"""
        entities: list[str] = []
        seen: set[str] = set()
        # 跟踪已匹配的字符位置，避免重复提取
        matched_spans: list[tuple[int, int]] = []

        # 1. 股票代码
        for match in _STOCK_CODE_PATTERN.finditer(query):
            entity = f"{match.group(1)}.{match.group(2)}"
            if entity not in seen:
                seen.add(entity)
                entities.append(entity)
                matched_spans.append((match.start(), match.end()))

        # 2. 公司名称
        for match in _COMPANY_SUFFIXES.finditer(query):
            entity = match.group(0)
            if entity not in seen:
                seen.add(entity)
                entities.append(entity)
                matched_spans.append((match.start(), match.end()))

        # 3. 行业关键词
        for match in self._industry_pattern.finditer(query):
            entity = match.group(0)
            if entity not in seen:
                seen.add(entity)
                entities.append(entity)
                matched_spans.append((match.start(), match.end()))

        # 4. 通用实体提取：提取"和"/"与"/"跟"连接的实体对
        # 例如 "茅台和五粮液" -> ["茅台", "五粮液"]
        # 策略：先按连接词分割，然后从两侧提取实体名
        # 实体名由 CJK 字符组成，但不包含虚词（的了是在等）
        # 右侧实体在遇到虚词边界时停止
        connector_pattern = re.compile(r"\s*(?:和|与|跟)\s*")
        connector_match = connector_pattern.search(query)
        if connector_match:
            # 左侧实体：从连接词向左提取 CJK 字符
            left_text = query[:connector_match.start()]
            left_cjk = re.search(r"([一-鿿]{2,6})$", left_text)
            # 右侧实体：从连接词向右提取，遇到虚词边界停止
            right_text = query[connector_match.end():]
            # 提取连续 CJK 字符，直到遇到虚词或非 CJK 字符
            right_cjk = re.match(r"([一-鿿]+?)(?:的|了|是|在|有|等|及|与|和|跟|[a-zA-Z0\d]|[，。！？：；]|$)", right_text)

            if left_cjk and right_cjk and len(right_cjk.group(1)) >= 2:
                left_entity = left_cjk.group(1)
                right_entity = right_cjk.group(1)
                for group in [left_entity, right_entity]:
                    if group not in seen:
                        seen.add(group)
                        entities.append(group)
                # 标记整个匹配区域
                matched_spans.append((left_cjk.start(), connector_match.end() + right_cjk.end()))

        # 5. 提取"的"前面的实体
        # 例如 "贵州茅台的供应商" -> ["贵州茅台"]
        # 排除与已匹配区域重叠的实体
        de_pattern = re.compile(r"([一-鿿]{2,6})的")
        for match in de_pattern.finditer(query):
            entity = match.group(1)
            # 跳过包含连接词的实体
            if "和" in entity or "与" in entity or "跟" in entity:
                continue
            # 跳过与已匹配区域重叠的实体
            if self._overlaps_matched(match.start(1), match.end(1), matched_spans):
                continue
            if entity not in seen:
                seen.add(entity)
                entities.append(entity)

        return entities

    @staticmethod
    def _overlaps_matched(
        start: int, end: int, spans: list[tuple[int, int]]
    ) -> bool:
        """检查位置范围是否与已匹配区域重叠。"""
        for s, e in spans:
            if start < e and end > s:
                return True
        return False

    def _classify_intent(self, query: str, entities: list[str]) -> tuple[str, str]:
        """
        分类查询意图。

        Returns:
            (query_type, intent) 元组
        """
        # 路径查询优先级最高（两个实体 + 路径关键词）
        if self._path_pattern.search(query) and len(entities) >= 2:
            return "path_finding", "find_path"

        # "和/与"连接两个实体 -> 路径查询
        pair_pattern = re.compile(r"([一-鿿]{2,6})\s*(?:和|与|跟)\s*([一-鿿]{2,6})")
        if pair_pattern.search(query) and len(entities) >= 2:
            return "path_finding", "find_path"

        # 关系查询
        if self._relation_pattern.search(query):
            return "entity_relation", "find_relations"

        # 行业状态查询
        if self._state_pattern.search(query):
            return "industry_state", "assess_state"

        # 默认：实体搜索
        return "entity_search", "find_entity"
