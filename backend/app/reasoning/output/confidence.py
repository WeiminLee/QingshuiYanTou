"""
Layer 4 — 置信度标注模块

负责：
1. 从 source_type 反推置信度等级（TIER0-4）
2. 多源结论汇聚时的置信度融合
3. 冲突检测时的置信度降级
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ── source_type → TIER 映射表 ────────────────────────────

SOURCE_TO_TIER: dict[str, str] = {
    # Tier 0：法律强制披露
    "prospectus": "TIER0_LEGAL",
    "annual_report": "TIER0_LEGAL",
    "quarterly_report": "TIER0_LEGAL",
    # Tier 1：监管背书平台
    "cninfo_announcement": "TIER1_OFFICIAL",
    "regulatory_inquiry": "TIER1_OFFICIAL",
    "interactive_qa": "TIER1_OFFICIAL",
    # Tier 2：第三方客观数据
    "customs_data": "TIER2_THIRD_PARTY",
    "patent_data": "TIER2_THIRD_PARTY",
    "bid_data": "TIER2_THIRD_PARTY",
    "business_registration": "TIER2_THIRD_PARTY",
    # Tier 3：公司主动披露
    "company_website": "TIER3_SELF_DISCLOSED",
    "company_wechat": "TIER3_SELF_DISCLOSED",
    # Tier 4：研究机构分析
    "research_report": "TIER4_ANALYSIS",
    "cls_news": "TIER4_ANALYSIS",
    # 内部生成
    "neo4j_graph": "TIER2_THIRD_PARTY",   # 图谱节点，取决于原始 source
    "vector_db": "TIER4_ANALYSIS",          # 向量库，语义相似性
    "postgres": "TIER2_THIRD_PARTY",         # PostgreSQL 评分数据
    "mongodb": "TIER4_ANALYSIS",            # MongoDB 情报，置信度不等
    "deliberation": "TIER4_ANALYSIS",      # LLM deliberation 结论
}

# ── TIER → 分值映射 ────────────────────────────────────

TIER_TO_SCORE_RANGE: dict[str, tuple[float, float]] = {
    "TIER0_LEGAL": (0.85, 1.0),
    "TIER1_OFFICIAL": (0.75, 0.90),
    "TIER2_THIRD_PARTY": (0.65, 0.85),
    "TIER3_SELF_DISCLOSED": (0.50, 0.75),
    "TIER4_ANALYSIS": (0.40, 0.70),
}

# ── TIER → 描述 ─────────────────────────────────────────

TIER_DESCRIPTIONS: dict[str, str] = {
    "TIER0_LEGAL": "高置信度（≥85%）：法律强制性披露，多源一致",
    "TIER1_OFFICIAL": "高置信度（75-90%）：监管认可平台，数据可靠",
    "TIER2_THIRD_PARTY": "中置信度（65-85%）：第三方客观数据，硬数据",
    "TIER3_SELF_DISCLOSED": "中置信度（50-75%）：公司主动披露，可能存在选择性",
    "TIER4_ANALYSIS": "低置信度（40-70%）：研究机构分析，存在利益冲突",
}


def source_type_to_tier(source_type: str) -> str:
    """从 source_type 推断置信度等级"""
    return SOURCE_TO_TIER.get(source_type, "TIER4_ANALYSIS")


def tier_to_score(tier: str) -> tuple[float, float]:
    """从 TIER 获取置信度分值范围"""
    return TIER_TO_SCORE_RANGE.get(tier, (0.40, 0.70))


def merge_confidence(tiers: list[str]) -> tuple[str, float]:
    """
    多源置信度融合（悲观原则：取最低）。

    Args:
        tiers: 各来源的 TIER 列表

    Returns:
        (merged_tier, merged_score)
    """
    if not tiers:
        return "TIER4_ANALYSIS", 0.55

    # TIER 优先级（数字越小优先级越高）
    tier_order = {
        "TIER0_LEGAL": 0,
        "TIER1_OFFICIAL": 1,
        "TIER2_THIRD_PARTY": 2,
        "TIER3_SELF_DISCLOSED": 3,
        "TIER4_ANALYSIS": 4,
    }

    # 取最低置信度（保守）
    worst_tier = min(tiers, key=lambda t: tier_order.get(t, 99))
    score_range = tier_to_score(worst_tier)
    # 取范围下限
    score = (score_range[0] + score_range[1]) / 2

    logger.debug(f"[Confidence] Merged tiers={tiers} → {worst_tier} ({score:.2f})")
    return worst_tier, score


def merge_conclusion_confidence(conclusions: list) -> tuple[str, float]:
    """
    从 Conclusion 列表提取所有 EvidenceRef 的 source_type，
    转 TIER，取最低（悲观原则），返回 (merged_tier, merged_score)。
    """
    tiers = []
    for c in conclusions:
        for e in getattr(c, "evidence", []):
            tier = source_type_to_tier(getattr(e, "source_type", ""))
            tiers.append(tier)
    if not tiers:
        return "TIER4_ANALYSIS", 0.55
    return merge_confidence(tiers)


def downgrade_for_conflict(
    current_tier: str,
    conflict_count: int = 1,
) -> tuple[str, float]:
    """
    发现多源冲突时，置信度降级。

    规则：
    - 1 个冲突：降 1 级
    - 2 个冲突：降 2 级
    - 3 个及以上：降至 TIER4_ANALYSIS
    """
    tier_order = {
        "TIER0_LEGAL": 0,
        "TIER1_OFFICIAL": 1,
        "TIER2_THIRD_PARTY": 2,
        "TIER3_SELF_DISCLOSED": 3,
        "TIER4_ANALYSIS": 4,
    }
    reverse_order = {v: k for k, v in tier_order.items()}

    current_level = tier_order.get(current_tier, 4)
    downgrade_steps = min(conflict_count, current_level)
    new_level = current_level + downgrade_steps
    new_tier = reverse_order.get(new_level, "TIER4_ANALYSIS")

    score_range = tier_to_score(new_tier)
    new_score = (score_range[0] + score_range[1]) / 2

    logger.info(
        f"[Confidence] Downgraded: {current_tier} → {new_tier} "
        f"(conflicts={conflict_count}, score={new_score:.2f})"
    )
    return new_tier, new_score


def label_for_score(score: float) -> str:
    """从分值推断标签"""
    if score >= 0.85:
        return "🟢 高置信度"
    elif score >= 0.60:
        return "🟡 中置信度"
    else:
        return "🔴 低置信度"


def format_confidence_block(
    overall_tier: str,
    overall_score: float,
    evidence_tiers: list[str] | None = None,
) -> str:
    """
    格式化置信度块（Markdown 格式）。
    """
    desc = TIER_DESCRIPTIONS.get(overall_tier, "未知置信度")
    icon = "🟢" if overall_score >= 0.75 else ("🟡" if overall_score >= 0.60 else "🔴")

    lines = [
        f"## 置信度标注 {icon}",
        "",
        f"**整体置信度**：{overall_tier}",
        f"**置信度分值**：{overall_score:.0%}",
        f"**说明**：{desc}",
        "",
    ]

    if evidence_tiers:
        tier_counts = {}
        for t in evidence_tiers:
            tier_counts[t] = tier_counts.get(t, 0) + 1

        lines.append("**证据来源分布**：")
        for tier, count in sorted(tier_counts.items(), key=lambda x: x[0]):
            icon_e = "🟢" if tier in ("TIER0_LEGAL", "TIER1_OFFICIAL") else "🟡"
            lines.append(f"- {icon_e} {tier}: {count} 条")
        lines.append("")

    return "\n".join(lines)
