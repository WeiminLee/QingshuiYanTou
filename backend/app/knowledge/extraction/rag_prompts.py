"""
KG 抽取提示词模板 — JSON 输出版 (V4)
"""

from __future__ import annotations

EXTRACTION_PROMPT = """你是一名 A 股买方研究员，从上市公司公告/问答中提取结构化知识，写入数据库。

数据库有三个表，请按 schema 填充：

【entities 表】
{{
  "entities": [
    {{"name": "具体名称", "type": "Company|Product|Metric"}}
  ]
}}
- Company：公司全称或简称。绝对禁止使用"公司""本集团""本公司"等泛称。若文本中未出现公司名，使用【公司信息】中指定的名称。
- Product：产品、材料、技术、业务线、品牌（如"碳酸锶""己二腈""智能座舱""垃圾焚烧发电""百联繁花里"）
- Metric：量化指标，命名格式为"指标含义+数值+单位"。示例："营收120亿元""毛利率32%""产能20万吨/年""股东户数31104户""深加工收入占比41%"。没有数值的定性描述不算 Metric。

【relations 表】
{{
  "relations": [
    {{
      "entity1": "主体名",
      "entity2": "客体名",
      "description": "一句话关系描述",
      "confidence": 1.0,
      "stmt_type": "Fact|Claim|Estimate",
      "source": "原文依据句",
      "metric_value": null,
      "metric_unit": null,
      "metric_period": null,
      "metric_period_type": null,
      "metric_sentiment": null
    }}
  ]
}}
- entity1/entity2 必须是 entities 中已声明的 name
- 关系方向：Company→Product（生产/研发/销售/提供）、Company→Metric（实现/达到/为）、Product→Metric（具有/达到）
- description：一句话描述关系，包含关键信息
- confidence：1.0=原文直接陈述，0.7=基于上下文推断
- stmt_type：Fact=客观事实，Claim=管理层表述，Estimate=预测
- source：原文中支撑该关系的句子
- 仅当 entity2 为 Metric 时填写 metric_* 字段。metric_value 填数字，不可填日期或文本。
- metric_period 格式：2024A(实际年)、2025Q1(季度)、2025H1(半年度)

【signals 表】
{{
  "signals": [
    {{
      "signal_type": "mass_production|capacity|policy|capex|earnings|order|risk",
      "polarity": "positive|negative|risk",
      "strength": 65,
      "subject_name": "主体名",
      "subject_type": "company|product|sector|policy",
      "summary": "60字摘要",
      "evidence_excerpt": "原文依据120字"
    }}
  ]
}}
信号类型：
- mass_production：产品量产/交付（"已批量交付""达产""试生产"）
- capacity：产能扩张/投产（"新增产能""投产""扩产""产能储备""产能利用率"）
- policy：政策利好（"补贴""国产替代""纳入规划""绿色电力证书"）
- capex：资本开支（"设备采购""研发投入""资本开支"）
- earnings：业绩变化（"业绩预增""扭亏""收入增长""营收下降""亏损"）
- order：订单/合同（"中标""重大合同""大额订单"）
- risk：风险事件（"处罚""诉讼""减值""停产""客户流失""估值折价"）

信号规则：
- strength：0-30轻微提及、31-60明确陈述、61-80有量化数据、81-100重大节点
- 否定句不输出信号。风险提示标准话术不输出（"研发存在不确定性"）
- 每条文本最多 3 条信号，只保留最明确的
- 只要有明确陈述就应该输出信号，不要太保守
- subject_name 必须是 entities 中已声明的 Company 或 Product 的 name，不可用"公司""2025年年报"等非实体名称

【输出】只输出 JSON，不要任何解释文字。

【输入文本】
{input_text}
"""

GENERIC_NAME_RETRY_PROMPT = """【重要】你之前的输出中使用了"公司""本行"等模糊指代。
请重新抽取，必须从文本中提取确切的公司全称或简称。

禁止使用"公司""本行""本公司""本集团""本企业""该企业"等模糊指代。
若文本中未出现公司名，使用【公司信息】中指定的名称。

{{
  "entities": [{{"name": "具体名称", "type": "Company|Product|Metric"}}],
  "relations": [{{"entity1": "...", "entity2": "...", "description": "...", "confidence": 1.0, "stmt_type": "Fact|Claim|Estimate", "source": "...", "metric_value": null, "metric_unit": null, "metric_period": null, "metric_period_type": null, "metric_sentiment": null}}],
  "signals": [{{"signal_type": "...", "polarity": "...", "strength": 0, "subject_name": "...", "subject_type": "...", "summary": "...", "evidence_excerpt": "..."}}]
}}

{input_text}
"""

ENTITY_TYPES = ["Company", "Product", "Metric"]
DEFAULT_ENTITY_TYPES = ENTITY_TYPES


def get_extraction_prompt(source_type: str, section_title: str = "文档概述") -> str:
    return EXTRACTION_PROMPT