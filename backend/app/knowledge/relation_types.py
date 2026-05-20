"""
关系类型常量定义

定义投资研究场景的核心关系类型。
"""

# ── 关系类型常量 ──────────────────────────────────────

RELATIONSHIP_TYPES = frozenset({
    "BELONGS_TO",
    "PRODUCES",
    "DIRECTLY_SUPPLIES_TO",
    "SUPPLIES_TO",
    "USES",
    "APPLIES_TO",
    "COMPETES_WITH",
    "STATE_TRANSITION",
    "DISCLOSES",
    "CATALYZES",
    "CONSTRAINS",
    "CONTRADICTS",
    "SUBSTITUTES",
    "INVESTS_IN",
    "PARTNERS_WITH",
    "ACQUIRES",
    "SUPPLIES",
})

# 关系描述
RELATIONSHIP_DESCRIPTIONS = {
    "BELONGS_TO": "公司 → 行业（所属板块）",
    "PRODUCES": "公司/产能 → 产品（生产什么）",
    "DIRECTLY_SUPPLIES_TO": "供应商 → 客户（直接供货关系，最具体）",
    "SUPPLIES_TO": "公司 → 公司（供应链关系）",
    "USES": "产品 → 技术（产品使用的技术路线）",
    "APPLIES_TO": "技术 → 应用场景（技术应用方向）",
    "COMPETES_WITH": "公司 ↔ 公司（竞争关系，对称）",
    "STATE_TRANSITION": "状态A → 状态B（产业阶段跃迁，最重要！）",
    "DISCLOSES": "事件 → 披露内容（信息披露）",
    "CATALYZES": "技术A → 技术B（技术催化关系）",
    "CONSTRAINS": "指标 → 约束（产能约束/良率约束）",
    "CONTRADICTS": "冲突标记（多源语义冲突时写入，confidence=0.5）",
    "SUBSTITUTES": "替代关系（技术替代/产品替代）",
    "INVESTS_IN": "投资关系",
    "PARTNERS_WITH": "合作关系",
    "ACQUIRES": "收购关系",
    "SUPPLIES": "供应关系",
}
