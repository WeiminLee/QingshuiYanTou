"""
冲突检测模块

检测多源语义冲突，并写入 Neo4j。
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# 正面语义关键词（量产、规模化等 → 产业化进度）
POSITIVE_MARKERS = [
    "量产",
    "规模化",
    "大规模",
    "已突破",
    "已实现",
    "量产爬坡",
    "正式投产",
    "产能释放",
    "商业化",
    "规模交付",
    "批量供货",
]
# 负面语义关键词（中试，小批量等 → 早期阶段）
NEGATIVE_MARKERS = [
    "中试",
    "小批量",
    "研发中",
    "仍处",
    "未实现",
    "暂未",
    "试产",
    "样品阶段",
    "送样验证",
    "认证中",
    "未量产",
    "仍处于",
    "仍属",
    "尚未",
    "还未",
    "还在",
]


def semantic_polarity(text: str) -> str:
    """
    判断文本语义极性。
    返回: "positive" | "negative" | "neutral"
    """
    pos_count = sum(1 for m in POSITIVE_MARKERS if m in text)
    neg_count = sum(1 for m in NEGATIVE_MARKERS if m in text)
    if pos_count > 0 and neg_count == 0:
        return "positive"
    if neg_count > 0 and pos_count == 0:
        return "negative"
    if pos_count > 0 and neg_count > 0:
        return "conflict"
    return "neutral"


def detect_contradiction(
    from_entity: str,
    to_entity: str,
    relationship_type: str,
    new_properties: dict,
    new_source_name: str = "",
    existing_relations: list[dict] | None = None,
) -> dict | None:
    """
    检测多源冲突。

    检测逻辑：
    - 新描述含正面关键词 AND 同 pair 历史描述含负面关键词 → 冲突
    - 新描述含负面关键词 AND 同 pair 历史描述含正面关键词 → 冲突

    Returns:
        None：无冲突
        dict：冲突详情 {source_a, source_b, desc_a, desc_b, type}
    """
    from app.knowledge.relation_service import query_relations

    rel_desc = new_properties.get("relation_description", "")
    if not rel_desc:
        return None

    new_polarity = semantic_polarity(rel_desc)
    if new_polarity == "neutral":
        return None

    # 从 Neo4j 查询同 pair 的历史关系
    if existing_relations is None:
        existing_relations = query_relations(
            from_entity=from_entity,
            to_entity=to_entity,
            relationship_type=relationship_type,
            active_only=False,  # 包含历史
            limit=20,
        )

    for hist in existing_relations:
        # B5 fix: query_relations 直接返回属性在根字典，无嵌套 properties 键
        hist_desc = hist.get("relation_description", "")
        if not hist_desc:
            continue
        # 跳过自身（valid_from 相同）
        if hist.get("valid_from") == new_properties.get("valid_from") and hist.get("source_name") == new_source_name:
            continue

        hist_polarity = semantic_polarity(hist_desc)
        if hist_polarity == "neutral":
            continue

        # 检测极性冲突
        if (new_polarity == "positive" and hist_polarity == "negative") or (
            new_polarity == "negative" and hist_polarity == "positive"
        ):
            return {
                "source_a": hist.get("source_name") or "unknown",
                "source_b": new_source_name or "unknown",
                "desc_a": hist_desc[:100],
                "desc_b": rel_desc[:100],
                "type": "polarity_conflict",
            }
        # 同对同一关系内的"内容矛盾"（同一对有完全相反描述）
        if (new_polarity == "conflict" or hist_polarity == "conflict") and hist.get("source_name") != new_source_name:
            return {
                "source_a": hist.get("source_name") or "unknown",
                "source_b": new_source_name or "unknown",
                "desc_a": hist_desc[:100],
                "desc_b": rel_desc[:100],
                "type": "mixed_content_conflict",
            }

    return None


def write_contradiction(
    from_entity: str,
    to_entity: str,
    contradiction_info: dict,
) -> bool:
    """
    将冲突写入 Neo4j，建立 CONTRADICTS 对称关系边。

    Returns:
        True：成功写入
        False：已有冲突边，跳过
    """
    from app.knowledge.relation_service import upsert_relation

    source_a = contradiction_info.get("source_a", "unknown")
    source_b = contradiction_info.get("source_b", "unknown")
    desc_a = contradiction_info.get("desc_a", "")
    desc_b = contradiction_info.get("desc_b", "")
    conflict_type = contradiction_info.get("type", "polarity_conflict")

    properties = {
        "description": f"多源冲突：{source_a} 称「{desc_a}」，{source_b} 称「{desc_b}」",
        "source_a": source_a,
        "source_b": source_b,
        "desc_a": desc_a,
        "desc_b": desc_b,
        "conflict_type": conflict_type,
        "resolved": False,
    }

    try:
        _, is_new = upsert_relation(
            from_entity=from_entity,
            to_entity=to_entity,
            relationship_type="CONTRADICTS",
            properties=properties,
            confidence=0.5,  # 冲突关系置信度降级
            source_type="contradiction_detector",
            source_name="system",
        )
        return is_new
    except Exception as e:
        logger.warning("写入 CONTRADICTS 边失败: %s", e)
        return False
