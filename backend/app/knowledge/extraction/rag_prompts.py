"""
RAG 抽取提示词模板

包含投资研究场景的实体关系抽取 prompt。
"""
from __future__ import annotations

# ── 分隔符常量（与 RAGFlow 一致）────────────────────────────────────────────

TUPLE_DELIMITER = "<|>"
RECORD_DELIMITER = "##"
COMPLETION_DELIMITER = "<|COMPLETE|>"
GRAPH_FIELD_SEP = "<SEP>"

# ── Prompt 模板（V2 — 增强 Few-shot + 禁止抽取规则）──────────────────────────

EXTRACTION_PROMPT = """你是一名专业的投资研究分析师。从以下文本中抽取实体（及其属性）和实体之间的关系。

【第一步：判断文本来源】
在抽取之前，先判断文本属于哪一类：
- A. 研报正文（分析师写的投资分析）→ 可以抽取
- B. 封面声明/免责声明/风险提示 → 【禁止抽取】
- C. 文件路径/URL/Email/联系方式 → 【禁止抽取】
- D. 表格行（含"|"的多列对齐内容）→ 【禁止抽取】
- E. 页眉页脚/累计合计行/章节标题 → 【禁止抽取】

只有 A 类内容才参与实体和关系的抽取。

【实体类型白名单】只抽取以下3类，禁止生成白名单外的类型：
- Company（公司）：只抽取【上市公司及其主要产品品牌/竞争对手】
  禁止：券商研究所，投资公司、基金、监管机构（如"中邮证券研究所"、"东吴证券研究所"）
- Product（产品）：上市公司生产或销售的具体产品
- Metric（量化指标）：必须同时含【数字+单位】（如"2025年营收120亿元"、"毛利率32%"）
  禁止：无数值的泛化指标、指数名称（如"沪深300"、"恒生指数"）、股票代码

【禁止抽取】（7类噪声，无论如何都不抽取）：
1. 研报封面声明/免责声明/机构介绍
   示例："本报告由中邮证券研究所发布"、"本报告仅供机构投资者参考"
2. 文件路径/URL/Email/社交媒体ID
   示例："请联系 analyst@cns.com"、"详见 /api/v1/download/report.pdf"
3. 风险提示/法律声明/合规提示
   示例："◼ 风险提示：下游扩产不及预期"、"郑重声明：本报告..."
4. 表格行内容（包含"|"的多列数据）
   示例："| 归母净利润 | 2025A | 2026E |"、" |  |  |  |  |"
5. 重复累计行、空白单元格内容
   示例："合计"、"总计"、"流动资产合计31282332747..."
6. 指数名称/股票代码/非公司名称
   示例："沪深300"、"恒生指数"、"三板做市指数"（这些都是指数，不是公司）
7. 超长碎片（长度超过50字的实体名称）或纯符号内容

【显式陈述原则】只抽取文本中明确陈述的内容，不要推断未写明的事实。

输出格式：
1. 实体列表：
(name)<|>(type)<|>(description)<|>(source)
2. 关系列表：
(source)<|>(relation)<|>(target)<|>(weight)<|>(description)<|>(source)

#####
{input_text}
#####
"""

ANNOUNCEMENT_EXTRACTION_PROMPT = """你是一名专业的投资研究知识图谱抽取专家。从以下官方披露文本中抽取 Schema V4 实体和 RELATES 关系。

【文本类型】公告/互动易问答（公司官方披露）

【实体类型白名单】只允许以下7类：
- Company（公司）：公告主体上市公司、重要客户、供应商、竞争公司
- Product（产品）：具体产品、材料、设备、服务
- Category（分类）：行业、板块、产业链环节、产品类别
- Application（应用）：应用场景、下游领域、终端市场
- Technology（技术）：工艺、技术路线、平台、算法、专利技术
- Metric（指标）：营收、净利润、毛利率、产能、销量、订单金额等量化或趋势指标
- Project（项目）：扩产、募投、产线、基地、合作项目

【必须抽取】
- 公告主体公司，通常来自公告抬头、落款、证券简称或正文中的公司全称。
- 业绩预告、年报、半年报、季报中的关键财务指标，例如营业收入、归母净利润、扣非净利润、毛利率、同比变化、预计区间。
- 原文明确出现的产品、项目、客户、供应商、应用领域。

【关系格式】统一使用 RELATES 自然语言关系，不输出旧的 BELONGS_TO/PRODUCES 等类型。
RELATES: 实体A → 实体B
  关系描述: "100字以内，保留时间、方向、状态变化"
  置信度: 1.0
  来源: "原文相关句"

Metric 输出格式：
METRIC: 指标名称
  name: 指标名称
  value: 数值或 null
  unit: 标准单位，如 万元、亿元、%、GWh；无明确单位时为 null
  period: 2025A / 2025Q3 / 2025H1 / 2025E 等
  period_type: actual / forecast / quarterly / half-year
  sentiment: positive / negative / neutral

【禁止抽取】文件路径、URL、联系方式、表格行、页眉页脚。

【显式陈述原则】只抽取文本中明确陈述的内容。

示例：
Entity: 北京新雷能科技股份有限公司(Company)
METRIC: 归属于上市公司股东的净利润
  name: 归属于上市公司股东的净利润
  value: null
  unit: 万元
  period: 2025E
  period_type: forecast
  sentiment: negative
RELATES: 北京新雷能科技股份有限公司 → 归属于上市公司股东的净利润
  关系描述: "公司预计2025年度归属于上市公司股东的净利润发生变动"
  置信度: 1.0
  来源: "原文业绩预告相关句"

#####
{input_text}
#####
"""

ANNOUNCEMENT_SOURCE_TYPES = [
    "annual_report",
    "announcement",
    "prospectus",
    "招股书",
]

CONTINUE_PROMPT = f"""继续抽取遗漏的实体和关系，只输出遗漏内容，不要重复已完成的部分。
完成后输出 {COMPLETION_DELIMITER}"""

SUMMARIZE_PROMPT = """你是一个投资研究知识整理助手。
给定一个实体（或关系）的多条描述，请将它们合并为一条完整描述。

要求：
1. 保留所有数字、阶段、趋势等具体信息
2. 如描述间存在矛盾（如"已量产"vs"还在中试"），请**保留分歧**，不要消解，用"|"分隔各方说法
3. 用与输入相同语言输出

#######
Data:
名称: {entity_name}
描述列表:
{description_list}
#######
Output:"""

# ── Schema V4 抽取提示词 ───────────────────────────────────────────────

ENTITY_TYPES_V4 = [
    "Company",
    "Product",
    "Category",
    "Application",
    "Technology",
    "Metric",
    "Project",
]

EXTRACTION_PROMPT_V4 = """你是一名专业的投资研究知识图谱抽取专家。从以下文本中抽取 Schema V4 实体和 RELATES 关系。

【实体类型白名单】只允许以下7类：
- Company（公司）：上市公司、重要客户、供应商、竞争公司
- Product（产品）：具体产品、材料、设备、服务
- Category（分类）：行业、板块、产业链环节、产品类别
- Application（应用）：应用场景、下游领域、终端市场
- Technology（技术）：工艺、技术路线、平台、算法、专利技术
- Metric（指标）：营收、毛利率、产能、销量、价格等量化/趋势指标
- Project（项目）：扩产、募投、产线、基地、合作项目

【关系格式】统一使用 RELATES 自然语言关系，不输出旧的 BELONGS_TO/PRODUCES 等类型。
RELATES: 实体A → 实体B
  关系描述: "100字以内，保留时间、方向、状态变化"
  置信度: 1.0
  陈述类型: Fact / Claim / Estimate
  来源: "原文相关句"

陈述类型规则：
- Fact: 原文明确陈述的客观事实（如"2024年营收120亿元"、"公司已实现800G光模块量产"）
- Claim: 公司/管理层的主张或声明（如"公司认为技术领先行业"、"管理层表示订单饱满"）
- Estimate: 预测、推测、目标（如"预计2025年产能翻倍"、"券商预测营收增长30%")

置信度规则：
- 1.0 = 原文直接陈述
- 0.7 = LLM 基于上下文轻度推断，必须有来源句支撑

Metric 输出格式：
METRIC: 指标名称
  name: 指标名称
  value: 数值或 null
  unit: 标准单位或 null
  period: 2024A / 2025E / 2024Q1 / 2024H1 等
  period_type: actual / forecast / quarterly / half-year
  sentiment: positive / negative / neutral

【禁止抽取】免责声明、联系方式、URL、文件路径、表格分隔噪声、无业务含义的章节标题、超过50字的实体名。

示例：
输入：宁德时代在储能领域生产销售三元锂电池，预计2025年产能增长。
输出：
Entity: 宁德时代(Company)
Entity: 三元锂电池(Product)
Entity: 储能(Application)
Entity: 产能(Metric)
RELATES: 宁德时代 → 三元锂电池
  关系描述: "在储能领域生产销售三元锂电池产品"
  置信度: 1.0
  陈述类型: Fact
  来源: "宁德时代在储能领域生产销售三元锂电池"
METRIC: 产能
  name: 产能
  value: null
  unit: null
  period: 2025E
  period_type: forecast
  sentiment: positive

#####
{input_text}
#####
"""

RELATES_EXTRACTION_PROMPT = """抽取文本中的 Schema V4 RELATES 关系。

只输出以下格式：
RELATES: 实体A → 实体B
  关系描述: "自然语言描述，100字以内"
  置信度: 1.0 或 0.7
  陈述类型: Fact / Claim / Estimate
  来源: "原文相关句"

陈述类型: Fact=客观事实, Claim=管理层主张, Estimate=预测推测

实体类型范围：Company、Product、Category、Application、Technology、Metric、Project。
置信度：1.0=直接陈述，0.7=LLM推断。禁止从免责声明、URL、联系方式、表格噪声中抽取。

示例：
RELATES: 宁德时代 → 三元锂电池
  关系描述: "在储能领域生产销售三元锂电池产品"
  置信度: 1.0
  陈述类型: Fact
  来源: "宁德时代在储能领域生产销售三元锂电池"
"""

METRIC_EXTRACTION_PROMPT = """抽取投资研究文本中的 Metric 指标。

输出字段：
- name: 指标名，必填
- value: 数值；无明确数值时为 null
- unit: 标准单位，如 GWh、亿元、%、万吨；无明确单位时为 null
- period: 必填，actual 用 2024A，forecast 用 2025E，季度用 2024Q1，半年度用 2024H1
- period_type: actual / forecast / quarterly / half-year
- sentiment: positive / negative / neutral；模糊表述无数值时必须填写

示例：
"2024年营收120亿元" → name="营收", value=120, unit="亿元", period="2024A", period_type="actual", sentiment="neutral"
"预计2025年产能增长" → name="产能", value=null, unit=null, period="2025E", period_type="forecast", sentiment="positive"
"""

# ── 投资研究专用实体类型（3类，2026-04-14 Schema 重构）─────────────────────

ENTITY_TYPES = ["Company", "Product", "Metric"]
DEFAULT_ENTITY_TYPES = ENTITY_TYPES_V4


def get_extraction_prompt(source_type: str, section_title: str = "文档概述") -> str:
    """根据 source_type 返回对应的抽取 prompt。"""
    def _with_section_title(template: str) -> str:
        return template.replace("{section_title}", section_title)

    if source_type in ("cninfo", "irm", "cninfo_announcement", "announcement_v4"):
        return _with_section_title(EXTRACTION_PROMPT_V4)
    if source_type in ANNOUNCEMENT_SOURCE_TYPES:
        return _with_section_title(ANNOUNCEMENT_EXTRACTION_PROMPT)
    return _with_section_title(EXTRACTION_PROMPT)
