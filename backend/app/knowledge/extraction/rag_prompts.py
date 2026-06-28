"""
KG 抽取提示词模板 — JSON 输出版 (V2 Schema)
"""

from __future__ import annotations

# ── Prompt 模板（V2 — JSON 输出）─────────────────────────────────────────────

EXTRACTION_PROMPT = """你是一名专业的投资研究知识图谱抽取专家。

【实体类型】
- Company：公司（上市公司、子公司、重要客户、供应商、竞争对手、合作伙伴）
- Product：产品、材料、设备、服务、技术系统（如智能座舱、半固态电池）
- Metric：量化指标，必须包含数字+单位（如"营收120亿元"、"毛利率32%"）

【禁止行为】
- 使用"公司""本行""本公司""本集团""本企业"等泛称代替确切实体名称
- 输出白名单以外的实体类型
- 抽取页眉页脚、免责声明、URL、表格行、无意义的单字或碎片

【输出格式】
返回严格合法的 JSON 对象，格式如下：

{{ 
  "entities": [
    {{"name": "<实体名称>", "type": "Company|Product|Metric"}}
  ],
  "relations": [
    {{
      "entity1": "<主体实体名称>",
      "entity2": "<客体实体名称>",
      "description": "<关系描述，保留时间/方向/状态，100字以内>",
      "confidence": 1.0,
      "stmt_type": "Fact|Claim|Estimate",
      "source": "<原文相关句>",
      "metric_value": null,
      "metric_unit": null,
      "metric_period": null,
      "metric_period_type": null,
      "metric_sentiment": null
    }}
  ]
}}

【metric 字段说明】
- 仅当 entity2 类型为 Metric 时填写 metric_* 字段
- metric_period 格式：2024A(实际年), 2025E(预测年), 2024Q1(季度), 2024H1(半年度)
- metric_period_type: actual(已实现), forecast(预测), quarterly(季度), half-year(半年度)
- metric_sentiment: positive(正面), negative(负面), neutral(中性)

【关系规则】
- entity1 和 entity2 必须引用 entities 中声明的 name
- 同一对 (entity1, entity2) 如有多个不同事实，合并到一条关系中描述
- 只抽取文本中明确陈述的内容，不要推断未写明的事实

【陈述类型】
- Fact: 原文明确陈述的客观事实（如"2024年营收120亿元"）
- Claim: 公司/管理层的主张（如"管理层表示订单饱满"）
- Estimate: 预测、推测（如"预计2025年产能翻倍"）

【置信度规则】
- 1.0: 原文直接陈述
- 0.7: 基于上下文轻度推断，必须有来源句支撑

#####
{input_text}
#####
"""

GENERIC_NAME_RETRY_PROMPT = """【重要】你之前的输出中使用了"公司""本行"等模糊指代。
请重新抽取，必须从文本中提取确切的公司全称或简称。

例如"公司"应替换为文本中出现的实际名称（如"华域汽车""江苏银行"），
而不是使用"公司""本行"等泛称。

再次强调——禁止使用"公司""本行""本公司""本集团""本企业""该企业"等模糊指代。

{input_text}
"""

# ── 投资研究专用实体类型（3类）────────────────────────────────────────────

ENTITY_TYPES = ["Company", "Product", "Metric"]
DEFAULT_ENTITY_TYPES = ENTITY_TYPES


def get_extraction_prompt(source_type: str, section_title: str = "文档概述") -> str:
    """返回 KG 抽取 prompt。所有数据源统一使用 V2 JSON prompt。"""
    return EXTRACTION_PROMPT
