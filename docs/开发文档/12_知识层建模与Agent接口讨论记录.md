# 知识层建模与 Agent 接口讨论记录

> 日期：2026-05-20
> 状态：讨论结论记录，尚未进入实施
> 主题：基于预期差的投研分析平台，知识构建层与 Agent harness 的职责边界

## 一、产品定位

清水投研是一个基于预期差的投研分析平台。

差异性主要来自两部分：

1. 适合投研系统的知识构建体系。
2. 能够调用知识体系并进行推理的 Agent / harness 系统。

知识体系需要覆盖公告、财报、互动易、研报、行情、产业链资料等信息中隐含的实时事实和状态变化，为 Agent 提供可信、可溯源、可组合的上下文。

## 二、核心边界

本次讨论确认了一个重要边界：

```text
知识构建层 = 结构化实时事实表达
Agent 系统 = 基于事实、状态、关系进行推理、组合、解释和提出假设
用户 = 最终判断和决策制定者
```

知识构建层不负责直接输出：

- 这是预期差机会
- 这是错杀
- 这是补涨
- 建议上调或下调推荐
- 应该买入或卖出

知识构建层只负责记录：

- 发生了什么事实
- 来自什么证据
- 影响了哪个实体、产品、项目、客户、指标或产业链环节
- 对应事实里包含哪些结构化状态表达
- 事实和状态在什么时间发生、生效、失效
- 证据可信度和来源

预期差、错杀、补涨、修复、传导等结论，应由 Agent 在用户问题上下文中临时推理，由用户最终判断。

## 三、状态的定义

“状态”不应被理解为单独的产品功能或一组硬编码状态机工具。

本次讨论确认的定义是：

```text
状态 = 事实的结构化实时表达
```

例如：

- 一季报业绩不及预期
- 股价在业绩披露后下跌
- 二次侧电源开始量产
- 产品导入谷歌数据中心
- 储能电芯订单排产到 2027 年
- 某项目进入试产、爬坡、满产或延期

这些状态不是推理结论，而是从公告、财报、互动易、研报、行情等证据中抽取出来的结构化事实。

## 四、案例抽象

### 4.1 储能案例

用户示例：

```text
阳光电源一季报业绩表现
→ 判断储能出货没有预期那么好
→ 用户/Agent 在后续分析中降低储能板块预期
→ 推荐时避开储能相关个股
→ 中报前，储能电芯企业在互动易中表述订单排产到 2027 年
→ 说明二季报可能对储能形成利好
→ 这种变化会影响披露公司，也会影响产业链其他公司
```

知识层应记录：

- 阳光电源一季报中的业绩、出货、毛利率等事实
- 相关事实对应的结构化状态
- 储能电芯企业互动易中的订单排产事实
- 订单排产对应的结构化状态
- 储能电芯与储能产业链上下游、同环节公司之间的关系
- 所有事实的来源、时间和证据文本

知识层不应直接记录：

- 储能板块应该被下调
- 某公司存在预期差机会
- 某产业链应该推荐或规避

### 4.2 新雷能案例

用户示例：

```text
新雷能一季报业绩不及预期
→ 股价走低一段时间
→ 4 月公告称“二次侧电源”开始量产并导入谷歌数据中心
→ 有理由对二季报/中报产生更好预期
→ 当前股价可能是错杀
```

知识层应记录：

- 新雷能一季报业绩不及预期这一事实
- 一季报披露后的股价表现事实
- 二次侧电源开始量产的事实
- 二次侧电源导入谷歌数据中心的事实
- 新雷能、二次侧电源、谷歌数据中心、相关产业链环节之间的关系
- 对应公告、财报、行情数据的证据来源

“错杀”“修复”“二季报可能利好”等判断由 Agent 和用户完成，不进入知识层事实库。

## 五、知识层对象

第一版知识层应重点围绕以下对象构建：

### 5.1 Evidence

原始证据。

来源包括：

- 公告
- 财报
- 互动易
- 研报
- 新闻或行业资料
- 行情数据

关键字段：

- source_type
- source_name
- publish_date
- observed_at
- evidence_text
- source_url / file_ref
- confidence

### 5.2 Entity

投研对象。

当前 Schema V4 的七类实体仍可作为基础：

- Company
- Product
- Category
- Application
- Technology
- Metric
- Project

后续可继续讨论是否需要显式增加 Customer、Supplier、Segment 等实体类型，或先通过 Category / Company / RELATES 表达。

### 5.3 Relation

实体之间的客观关系。

关系不应过早承载机会判断。它只表达：

- 谁和谁相关
- 关系文本是什么
- 关系来源是什么
- 关系何时有效
- 关系可信度多少

当前统一 RELATES + 自然语言 text + weight + state_history 的方向是合理的，但实现中仍存在结构化关系类型和 RELATES 混用的问题，后续实施前需要进一步收敛。

### 5.4 Structured Fact / State Fact

从证据中抽取出的结构化事实状态。

示例字段：

```text
subject_id
subject_type
dimension
state_value
observed_at
valid_from
valid_to
evidence_id
evidence_text
confidence
```

状态只是事实表达，不是机会结论。

### 5.5 Market Fact

行情也是事实的一部分，不用于知识层直接判断错杀，但需要提供给 Agent。

示例：

- 某公告前后股价涨跌幅
- 相对板块涨跌幅
- 成交量变化
- 估值区间变化

这些可以作为 ResearchContext 的一部分提供给 Agent。

## 六、Agent 接口原则

本次讨论确认：Agent 不应面对大量具象化的状态机查询接口。

不优先设计如下过度具象工具：

- get_entity_state_timeline
- get_recent_state_changes
- get_state_evidence
- get_related_entities_by_state

这些底层能力可以在系统内部存在，但不应成为 Agent 第一版主要心智负担。

Agent 更需要的是少量高层研究上下文接口：

```text
我要研究一个公司
我要研究一个产业链或产品链
我要研究一个主题或行业
我要用自然语言搜索相关研究上下文
```

知识层负责在这些上下文包中聚合事实、关系、证据、状态、指标和行情。

Agent 拿到上下文后自行推理。

## 七、MVP Agent 接口

第一版 MVP 暴露四类高层接口即可。

### 7.1 get_company_context

用途：给 Agent 一个个股研究上下文包。

输入：

```text
company: 股票代码或公司名称
```

输出应包含：

- 公司基础信息
- 最新公告、财报、互动易、研报摘要
- 产品、客户、供应商、项目、指标
- 最近结构化事实状态
- 相关原文证据
- 产业链位置
- 行情和板块表现快照
- 相关实体

### 7.2 get_chain_context

用途：给 Agent 一个产业链、产品链或关键产品环节上下文包。

输入：

```text
chain_or_product: 产业链、产品、环节或技术关键词
```

输出应包含：

- 产业链结构
- 上中下游环节
- 相关公司
- 各环节最近事实变化
- 订单、产能、价格、技术、客户等结构化状态
- 证据来源

### 7.3 get_theme_context

用途：给 Agent 一个主题或行业上下文包。

输入：

```text
theme_or_industry: 主题、概念、行业名称
```

输出应包含：

- 主题内相关公司
- 板块近期表现
- 关键事实变化
- 产业链映射
- 近期公告、互动易、研报中的共振点
- 证据来源

### 7.4 search_research_context

用途：开放式自然语言研究检索入口。

输入：

```text
query: 自然语言问题
```

输出应包含：

- 相关实体
- 相关关系
- 相关结构化事实状态
- 原文 chunk
- 来源证据

该接口用于 Agent 不确定应该按公司、产业链还是主题查询时的兜底入口。

## 八、ResearchContext 返回原则

每个接口返回一个 ResearchContext。

第一版建议同时包含：

1. 结构化 JSON：给 Agent 稳定推理。
2. markdown_summary：给前端和用户快速阅读。

示例结构：

```text
ResearchContext
- subject
- snapshot_time
- facts
- entities
- relations
- structured_states
- metrics
- market_snapshot
- evidence
- related_context
- markdown_summary
```

其中 structured_states 只表达事实状态，例如：

```text
dimension: production
state_value: mass_production_started
evidence_text: 公告称二次侧电源开始量产
observed_at: 2026-04-xx
```

不得表达：

```text
这是错杀
这是预期差
建议买入
建议上调推荐
```

## 九、MVP 验收样例

第一版实现前，建议以两个样例作为验收闭环。

### 9.1 新雷能样例

Agent 通过 get_company_context 应能拿到：

- 一季报业绩不及预期
- 一季报披露后股价下跌
- 二次侧电源开始量产
- 导入谷歌数据中心
- 对应公告、财报、行情证据
- 新雷能与产品、客户、产业链环节的关系

Agent 可基于这些事实自行判断是否存在错杀修复或中报预期变化。

### 9.2 储能样例

Agent 通过 get_theme_context / get_chain_context 应能拿到：

- 阳光电源一季报中与储能出货、业绩相关的事实
- 储能电芯企业互动易订单排产信息
- 储能电芯及上下游相关公司
- 对应公告、互动易、财报证据
- 相关产业链结构

Agent 可基于这些事实自行判断储能板块预期是否需要修正。

## 十、后续待讨论问题

进入实施前还需要继续讨论：

1. ResearchContext 的字段是否需要进一步精简。
2. structured_states 的 dimension / state_value 第一版枚举如何定义。
3. Customer、Supplier、Segment 是否需要成为显式实体类型。
4. 当前 RELATES 与结构化关系类型混用问题如何收敛。
5. 行情事实 market_snapshot 的最小可用范围。
6. Agent 工具返回时，JSON 与 markdown_summary 的权重和格式。
7. 这四个接口内部如何复用现有 Neo4j、Qdrant、Mongo、SQL 数据。

## 十一、Evidence-first 知识构建管线

后续讨论确认：知识构建层应采用 Evidence-first 管线。

也就是先把原始材料解析、分块并保存为 Evidence，再由异步并发抽取任务从 Evidence 中抽取实体、关系和结构化状态事实。

核心链路：

```text
Raw Source
→ Parser
→ Chunker
→ Evidence 入库
→ Extraction Jobs 并发消费 Evidence
→ Entity / Relation / StructuredFact 入库
→ 向量索引更新
→ ResearchContext 可查询
```

### 11.1 Evidence 的生成职责

Evidence 不由 LLM 推理生成，而由数据接入和解析层机械生成。

不同来源对应不同生成器：

- 公告、财报 PDF：PDF parser + chunker + evidence builder
- 互动易问答：IRM ingestion + evidence builder
- 研报：report parser + chunker + evidence builder
- 新闻、网页：web fetch parser + evidence builder
- 行情：market snapshot builder
- 用户上传文件：upload parser + chunker + evidence builder

原则：

```text
谁接入原始数据，谁负责生成 Evidence。
```

### 11.2 Evidence 的最小字段

MVP 中 Evidence 可以先保持轻量，不需要复杂建模。

建议字段：

```text
evidence_id
source_type
source_name
subject_hint
publish_date
observed_at
text_excerpt
source_ref
checksum
confidence
```

字段含义：

- `evidence_id`：稳定 ID，用于去重和回溯。
- `source_type`：announcement / report / irm / market / news / upload。
- `source_name`：公告标题、互动易编号、研报名、网页标题等。
- `subject_hint`：可能关联的股票代码、公司名、主题或行业。
- `publish_date`：材料发布时间。
- `observed_at`：系统观测或入库时间。
- `text_excerpt`：原文片段或行情窗口描述。
- `source_ref`：PDF 文件、页码、chunk_id、Mongo 原始记录 ID、URL、行情窗口等。
- `checksum`：内容 hash，用于幂等入库。
- `confidence`：来源可信度基础分。

### 11.3 Evidence 生成策略

Evidence 生成应遵守以下策略：

1. **机械生成，避免推理**

   Evidence 只保存原文片段和来源元数据，不写入“利好”“错杀”“预期差”等判断。

2. **稳定 ID**

   ID 由来源类型、来源 ID、chunk 编号或内容 hash 生成。

   示例：

   ```text
   evidence_id = hash(source_type + source_id + chunk_index + text_checksum)
   ```

3. **按源头分置信度**

   默认可信度可由来源类型决定：

   ```text
   公告/财报：0.95 - 1.0
   行情：1.0
   互动易：0.80 - 0.90
   研报：0.70 - 0.85
   新闻：0.50 - 0.75
   用户上传：按来源标注
   ```

4. **保留 source_ref**

   Evidence 必须能回到原始材料，包括 PDF 页码、chunk、Mongo 原始记录、URL 或行情窗口。

5. **切块服务抽取**

   公告和研报不应整篇作为一个 Evidence。切块应考虑章节、页码、语义段落和 token 上限。

6. **Evidence 只追加，不随意覆盖**

   原始证据是审计记录。重复导入可去重，但不因后续状态变化删除旧 Evidence。

7. **Evidence 与抽取结果解耦**

   一个 Evidence 可以产生多个实体、关系、结构化状态事实。一个结构化事实也可以由多个 Evidence 支撑。

### 11.4 Evidence 入库后的并发抽取

Evidence 入库后，后续抽取应作为异步任务执行。

设计原则：

```text
Evidence 入库是主链路；
实体、关系、状态事实抽取是异步并发知识构建任务。
```

这样可以避免公告下载、互动易同步、研报导入被 LLM 抽取阻塞。

MVP 任务模型：

```text
extraction_job
- job_id
- evidence_id
- job_type
- status
- retry_count
- error
- extractor_version
- created_at
- updated_at
```

`job_type` 第一版可以包括：

- entity_relation
- structured_fact
- vector

MVP 可以先用 combined extractor：

```text
Evidence -> entities + relations + structured_facts
```

后续再拆成：

- entity extractor
- relation extractor
- structured fact extractor
- metric extractor
- vector indexer

### 11.5 并发抽取的写入原则

多个 Evidence 可能抽到同一个实体、关系或状态事实，因此所有知识写入必须幂等。

建议幂等键：

```text
Entity:
  deterministic entity_id

Relation:
  from_entity + to_entity + valid_from + text_hash

StructuredFact:
  subject_id + dimension + state_value + observed_at + evidence_id
```

抽取失败不得影响 Evidence 本身。

Evidence 是原始事实锚点，抽取失败只是 job failed，可重试、可重跑。

### 11.6 抽取状态与版本

每个 Evidence 应能追踪不同抽取阶段的状态。

示例：

```text
extraction_status:
  entity_relation: done
  structured_fact: pending
  vector: done
  last_extracted_at: 2026-05-20T...
  extractor_version: v1
```

当 prompt、parser 或 extractor 升级时，可以按版本重抽：

```text
where extractor_version < current_version
```

这对后续修复抽取质量、升级状态词表、重建向量索引很重要。

### 11.7 推荐存储分工

MVP 推荐分工：

```text
MongoDB:
  Evidence 原文片段、source_ref、抽取 job 状态

Neo4j:
  Entity / Relation / StructuredFact，引用 evidence_id 或 evidence_ids

Qdrant:
  Evidence chunk、实体描述、关系描述、结构化事实的向量索引
```

这个分工可以保持：

- Evidence 可审计
- 图谱可遍历
- 向量可检索
- 抽取任务可重跑

## 十二、当前结论

第一版方向：

```text
少量高层上下文接口 + 内部结构化事实
不暴露过多底层状态机接口
不把预期差、错杀、补涨作为知识层对象
不让知识层替用户做投资判断
```

知识层提供事实、实时、状态、关系和证据。

Agent 负责推理。

用户负责决策。
