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
  ],
  "signals": [
    {{
      "signal_type": "mass_production|capacity|policy|capex|earnings|order|risk",
      "polarity": "positive|negative|risk",
      "strength": 85,
      "subject_name": "<信号主体名称>",
      "subject_type": "company|product|sector|policy",
      "summary": "<信号摘要，60字以内>",
      "evidence_excerpt": "<原文依据句，120字以内>"
    }}
  ]
}}

【信号类型说明】
- mass_production: 产品量产/规模交付信号（如"已实现批量交付""达产"）
- capacity: 产能扩张/投产信号（如"新增产能""投产""扩产"）
- policy: 政策利好/规划信号（如"补贴""国产替代""十五五规划"）
- capex: 资本开支/算力投入信号（如"资本开支""设备采购""研发投入"）
- earnings: 业绩/盈利信号（如"业绩预增""扭亏""超预期""净利润增长""营收下降""亏损"）
- order: 订单/中标/合同信号（如"中标""重大合同""大额订单""新订单""暂无新订单突破"）
- risk: 风险/诉讼/监管信号（如"处罚""诉讼""减值""停产""客户流失""行业竞争加剧"）

【信号规则】
- 只输出文本中明确陈述的信号，不要推断未写明的内容
- 否定句不要输出（如"没有量产计划"不输出mass_production）
- strength 取值 0-100，按以下标准校准：
  - 0-30: 轻微提及，间接相关（如"公司关注到…"）
  - 31-60: 明确陈述但无量化数据（如"订单增长"不写具体数字）
  - 61-80: 有量化数据支撑（如"中标金额5亿元"、"净利润增长30%"）
  - 81-100: 重大变化/关键节点（如"国内首条量产线投产"、"业绩翻倍"）
- subject_name 引用 entities 中已声明的实体名称
- subject_type 与 signal_type 对应：mass_production→product, capacity→sector, policy→policy, capex→sector, earnings→company, order→company, risk→company
- polarity 含义：positive=正面利好, negative=负面利空, risk=风险事件
- 如果不确定是否属于以上7种信号类型，不要输出
- 一条文本最多输出3条信号，只保留最明确的信号
- 风险提示/免责声明中的标准话术不要抽取为risk信号（如"研发成果存在不确定性""敬请投资者注意风险"）
- "暂无新订单突破"等关于订单状态的陈述属于order信号，而非risk信号

【metric 字段说明】
- 仅当 entity2 类型为 Metric 时填写 metric_* 字段
- metric_period 格式：2024A(实际年), 2025E(预测年), 2024Q1(季度), 2024H1(半年度)
- metric_period_type: actual(已实现), forecast(预测), quarterly(季度), half-year(半年度)
- metric_sentiment: positive(正面), negative(负面), neutral(中性)

【关系规则】
- entity1 和 entity2 必须引用 entities 中已声明的 name
- 同一对 (entity1, entity2) 如有多个不同事实，合并到一条关系中描述
- 只抽取文本中明确陈述的内容，不要推断未写明的事实
- 每个实体至少参与一条关系（孤立实体是浪费）
- 常见关系类型示例：
  - Company → Product: "生产""研发""销售""提供"（如"公司生产智能座舱系统"）
  - Company → Metric: "营收达""净利润为""毛利率"（如"公司2024年营收120亿元"）
  - Product → Metric: "单价""成本""产能"（如"电池成本降至0.3元/Wh"）
  - Company → Company: "投资""收购""合作""供应"（如"公司投资了A公司"）
- 对于包含量化数据的句子，必须同时抽取 Metric 实体和对应的关系

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

同时按照以下格式输出 entities、relations 和 signals：

{{
  "entities": [
    {{"name": "<实体名称>", "type": "Company|Product|Metric"}}
  ],
  "relations": [
    {{
      "entity1": "<主体实体名称>",
      "entity2": "<客体实体名称>",
      "description": "<关系描述>",
      "confidence": 1.0,
      "stmt_type": "Fact|Claim|Estimate",
      "source": "<原文相关句>",
      "metric_value": null,
      "metric_unit": null,
      "metric_period": null,
      "metric_period_type": null,
      "metric_sentiment": null
    }}
  ],
  "signals": [
    {{
      "signal_type": "mass_production|capacity|policy|capex|earnings|order|risk",
      "polarity": "positive|negative|risk",
      "strength": 85,
      "subject_name": "<信号主体名称>",
      "subject_type": "company|product|sector|policy",
      "summary": "<信号摘要，60字以内>",
      "evidence_excerpt": "<原文依据句，120字以内>"
    }}
  ]
}}

{input_text}
"""

# ── 投资研究专用实体类型（3类）────────────────────────────────────────────

ENTITY_TYPES = ["Company", "Product", "Metric"]
DEFAULT_ENTITY_TYPES = ENTITY_TYPES


def get_extraction_prompt(source_type: str, section_title: str = "文档概述") -> str:
    """返回 KG 抽取 prompt。所有数据源统一使用 V2 JSON prompt。"""
    return EXTRACTION_PROMPT
