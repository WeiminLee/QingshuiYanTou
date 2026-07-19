# 预期差信号层设计规格（Spec）

**日期**：2026-07-13  
**范围**：清水投研系统的独立信号层，统一承接公告、新闻、互动易、研报等来源触发的高价值投研线索，并服务于 Agent 上下文注入与前端发现入口。  
**方案**：B 方案，独立 Signal Layer + 轻量传导。  
**性质**：设计规格，供 implementation plan → TDD 实现。  

---

## 1. 背景与目标

清水投研的知识构建层负责把公告、研报、互动易、行情、资讯等材料转化为可追溯事实和知识体系，服务 Agent 推理。但投研系统的核心不只是离线知识问答，还需要每天从增量信息中发现可能存在预期差的高价值线索。

这些线索暂称为**信号**。信号来自两类入口：

- **公告/知识构建触发**：公告、年报、互动易、研报等材料进入 Evidence/知识构建后，发现量产、订单、业绩、风险、产能、客户、政策等高价值变化。
- **外部新闻触发**：财联社/新闻/政策文件/产业动态/大公司资本开支变化等外部事件进入 events 后，发现可能影响行业、板块、公司或供应链的变化。

信号层的目标不是替代 Agent 做投资判断，而是在 Agent 运行前准备好“可能值得下钻的投研线索”，并让用户在前端直接看到这些线索，从而触发进一步研究。

### 1.1 核心目标

- 新增独立信号模块，统一承接公告和新闻触发的信号。
- 每条信号可追溯到原始来源、原文片段或 Evidence。
- 对信号进行去重、评分、状态管理和时效衰减。
- 对高价值信号生成 1-2 跳轻量传导候选。
- Agent 运行时按用户问题、持仓和偏好召回相关信号并注入上下文。
- 前端在主对话页左侧栏展示“预期差信号流”，支持 hover 暂停、点击下钻、围绕信号问 Agent。

### 1.2 非目标

- 不在信号层写入买入、卖出、补涨、错杀等交易结论。
- 不把信号第一版直接写入 Neo4j 作为长期知识图谱节点。
- 不第一版构建完整因子引擎或自动判断“确定预期差”。
- 不把普通新闻资讯包装成信号；只有经过抽取、评分、传导后的内容进入信号层。
- 不替代现有资讯信息流。普通资讯仍在资讯入口，信号入口只展示高价值线索。

---

## 2. 系统边界

信号层位于数据/知识构建之后、Agent 推理之前：

```text
公告 / 新闻 / 互动易 / 研报
  -> 原始入库 events / Evidence / source tables
  -> Signal Extractor 抽取信号
  -> Signal Store 保存可追溯线索
  -> Propagation Engine 生成轻量传导候选
  -> Signal Context Provider 按任务召回
  -> Agent 结合知识、记忆、持仓、工具做最终分析
```

边界规则：

- `Signal` 表达“值得关注的新信息线索”。
- `SignalPropagation` 表达“可能影响哪些对象，以及为什么可能影响”。
- `Signal` 和 `SignalPropagation` 都是线索，不是投资结论。
- 预期差判断保留在 Agent 运行期完成，由 Agent 结合用户持仓、用户偏好、知识库、行情、研报和工具结果综合分析。

---

## 3. 后端模块结构

新增独立后端包：

```text
backend/app/signals/
├── __init__.py
├── models.py              # Signal / SignalPropagation ORM
├── schemas.py             # API schema
├── extractor.py           # 规则抽取 + LLM 抽取接口
├── service.py             # 入库、去重、评分、状态
├── propagation.py         # 轻量传导
├── context_provider.py    # Agent 运行前召回注入
└── api.py                 # 前端查询接口
```

保留现有 `backend/app/knowledge/extraction/signal_extractor.py` 的规则关键词思路，但不继续让它作为孤立临时返回结构使用。实现时应将其规则迁移或适配进 `app/signals/extractor.py`，输出统一 `SignalCandidate`。

---

## 4. 数据模型

### 4.1 `signals`

PostgreSQL 表，用于保存信号主对象。

```text
signals
- id BIGSERIAL PK
- signal_id VARCHAR(40) UNIQUE NOT NULL
- source_type VARCHAR(32) NOT NULL
- source_id VARCHAR(128) NOT NULL
- source_title TEXT
- source_url TEXT
- published_at TIMESTAMPTZ
- detected_at TIMESTAMPTZ NOT NULL
- subject_name TEXT NOT NULL
- subject_type VARCHAR(32) NOT NULL
- signal_type VARCHAR(64) NOT NULL
- polarity VARCHAR(16) NOT NULL
- strength INTEGER NOT NULL
- confidence NUMERIC(4,3) NOT NULL
- freshness_score INTEGER NOT NULL
- value_score INTEGER NOT NULL
- summary TEXT NOT NULL
- evidence_excerpt TEXT
- status VARCHAR(24) NOT NULL DEFAULT 'new'
- metadata JSONB NOT NULL DEFAULT '{}'
- created_at TIMESTAMPTZ NOT NULL DEFAULT now()
- updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
```

字段说明：

| 字段 | 说明 |
|------|------|
| `signal_id` | 稳定 ID，建议 `SIG:` + source_id + subject + signal_type + excerpt hash |
| `source_type` | `announcement` / `news` / `irm` / `research_report` / `evidence` |
| `source_id` | `event_id` / `evidence_id` / 公告 ID / 研报 ID |
| `subject_name` | 直接触发对象，如公司、产品、行业、政策主题 |
| `subject_type` | `company` / `product` / `sector` / `concept` / `policy` / `macro` |
| `signal_type` | `mass_production` / `capacity` / `policy` / `capex` / `earnings` / `order` / `risk` 等 |
| `polarity` | `positive` / `negative` / `neutral` / `risk` |
| `strength` | 信号强度，0-100 |
| `confidence` | 抽取置信度，0-1 |
| `freshness_score` | 新鲜度，0-100 |
| `value_score` | 综合价值分，0-100 |
| `status` | `new` / `viewed` / `reviewed` / `dismissed` / `archived` |

索引：

```text
idx_signals_value_score        (value_score DESC, published_at DESC)
idx_signals_source             (source_type, source_id)
idx_signals_subject            (subject_type, subject_name)
idx_signals_status             (status)
idx_signals_metadata_gin       GIN(metadata)
```

### 4.2 `signal_propagations`

PostgreSQL 表，用于保存信号的轻量传导候选。

```text
signal_propagations
- id BIGSERIAL PK
- propagation_id VARCHAR(48) UNIQUE NOT NULL
- signal_id VARCHAR(40) NOT NULL REFERENCES signals(signal_id)
- target_name TEXT NOT NULL
- target_type VARCHAR(32) NOT NULL
- relation_path TEXT NOT NULL
- direction VARCHAR(24) NOT NULL
- impact_horizon VARCHAR(24) NOT NULL
- confidence NUMERIC(4,3) NOT NULL
- reasoning TEXT NOT NULL
- evidence_refs JSONB NOT NULL DEFAULT '[]'
- metadata JSONB NOT NULL DEFAULT '{}'
- created_at TIMESTAMPTZ NOT NULL DEFAULT now()
```

字段说明：

| 字段 | 说明 |
|------|------|
| `target_name` | 可能受影响对象，如公司、产品、行业、概念 |
| `target_type` | `company` / `product` / `sector` / `concept` |
| `relation_path` | 简短链路，如 `政策 -> 算力基础设施 -> 光通信需求` |
| `direction` | `beneficiary` / `pressure` / `risk` / `uncertain` |
| `impact_horizon` | `immediate` / `short` / `medium` / `long` |
| `reasoning` | 传导思想，前端展示给用户 |
| `evidence_refs` | KG、Evidence、event 等引用 |

索引：

```text
idx_signal_propagations_signal_id  (signal_id)
idx_signal_propagations_target     (target_type, target_name)
idx_signal_propagations_direction  (direction)
```

---

## 5. 抽取流程

### 5.1 统一输入

信号抽取器统一接收 `SourcePayload`：

```text
source_type
source_id
title
content
summary
published_at
url
metadata
```

来源适配：

- `events` 表：新闻标题、摘要、正文、发布时间。
- Evidence：`evidence_id`、`text_excerpt`、`source_ref`、`publish_date`。
- 公告/研报/互动易源表：可先通过现有 Evidence 管线间接触发，避免多套抽取入口。

### 5.2 抽取器分层

第一版采用规则抽取 + 可插拔 LLM 抽取接口：

- `RuleSignalExtractor`：关键词、句子截取、来源类型规则，稳定低成本。
- `LLMSignalExtractor`：接口预留，第一版可以只在高价值来源或低置信场景启用。
- `SignalExtractorPipeline`：整合多个 extractor，输出统一 `SignalCandidate`。

### 5.3 信号类型第一版

| 类型 | 触发示例 |
|------|----------|
| `mass_production` | 大规模量产、批量交付、产线达产 |
| `capacity` | 扩产、新增产能、项目投产、产能爬坡 |
| `policy` | 规划、补贴、监管变化、国产替代、十五五 |
| `capex` | 大公司资本开支增加、算力投入、设备采购 |
| `earnings` | 业绩预增、超预期、扭亏、毛利率变化 |
| `order` | 大额订单、长期合同、客户导入 |
| `risk` | 诉讼、处罚、减值、停产、订单延期 |

### 5.4 去重

同一来源、同一主体、同一信号类型、相近摘要视为重复。

稳定 ID：

```text
signal_id = "SIG:" + sha256(source_type + source_id + normalized_subject + signal_type + normalized_excerpt)[:20]
```

入库使用 upsert：

- 已存在：更新 `detected_at`、`freshness_score`、`value_score`、`metadata`。
- 不存在：新增信号，并触发传导。

---

## 6. 评分规则

`value_score` 是前端排序和 Agent 注入的重要依据。

第一版使用可解释规则评分：

```text
value_score =
  source_weight
  + signal_type_weight
  + strength_weight
  + confidence_weight
  + freshness_weight
  + portfolio_boost
  + propagation_boost
  - noise_penalty
```

默认方向：

| 因子 | 说明 |
|------|------|
| 来源权重 | 公告/Evidence 高于普通新闻；新闻政策类可单独加权 |
| 信号类型权重 | 量产、订单、业绩、政策、CapEx 权重高 |
| 强度 | “显著、大规模、首次、超预期”等提高强度 |
| 置信度 | 来源可信度和抽取置信度 |
| 新鲜度 | 越新越高，随时间衰减 |
| 持仓命中 | 命中当前用户持仓或关注概念时加权 |
| 传导覆盖 | 能传导到多个明确对象时加权 |

风险信号不降低价值分。风险信号对持仓用户很重要，应通过 `polarity = risk` 和 `direction = risk` 区分展示。

---

## 7. 轻量传导

### 7.1 传导原则

第一版只做 1-2 跳轻量传导，避免把离线层做成复杂投资判断引擎。

传导输出是候选：

- “可能受益”
- “可能承压”
- “需要关注风险”
- “方向不确定”

不输出：

- “应该买入”
- “确定补涨”
- “确定错杀”
- “市场必然重估”

### 7.2 传导来源

传导可以利用：

- Neo4j 知识图谱的公司、产品、上下游、竞争关系。
- 现有股票/概念/行业表。
- events.metadata.tags 中的概念标签。
- 用户持仓和偏好，用于召回加权，不用于改变全局传导事实。

### 7.3 传导例子

公告信号：

```text
信号：某公司公告 800G 光模块规模量产
传导：
  量产确认 -> 订单兑现概率提升 -> 高速光模块供应链需求增强
候选对象：
  中际旭创、新易盛、光芯片、高速连接器
```

新闻信号：

```text
信号：十五五规划强调算力基础设施
传导：
  政策主题 -> AI 服务器资本开支 -> 光通信/电源/散热链条
候选对象：
  AI服务器、光模块、液冷、数据中心电源
```

风险信号：

```text
信号：核心客户订单交付延期
传导：
  交付节奏后移 -> 短期收入确认承压 -> 高估值标的波动风险
候选对象：
  相关供应商、持仓命中公司
```

---

## 8. Agent 注入

新增 `SignalContextProvider`，在 `run_lead_agent` 预处理阶段与 memory、background、graph context 并列执行。

输入：

```text
question
user_id
portfolio
user_preferences
optional signal_id
```

召回规则：

- 如果请求带 `signal_id`，优先注入该信号及其传导。
- 否则按问题实体、用户持仓、用户偏好、信号新鲜度和价值分召回。
- 默认注入 Top 5，最多 Top 10。
- 风险信号命中持仓时优先注入。

注入格式：

```text
<signal-context>
[高价值信号]
- 800G 光模块规模量产
  value_score: 92, confidence: 0.92, source: announcement
  原文锚点: 公司公告提到相关产品已进入规模量产阶段...
  传导: 量产确认 -> 订单兑现概率提升 -> 上游光芯片/连接器需求增强
  相关持仓: 中际旭创、新易盛
</signal-context>
```

Prompt 约束：

- Agent 可以使用信号作为研究线索。
- Agent 必须区分“信号线索”和“已验证事实”。
- 涉及定量结论时仍需回到 Evidence、公告、研报或工具验证。
- 输出投资分析时保留“不构成投资建议”合规边界。

---

## 9. 前端集成

### 9.1 正确页面位置

当前主页面是 `frontend/src/views/Home.vue`：

- 左侧：Logo、新建账目、最近对话、过去 7 天、快速分类、用户/系统状态。
- 右侧：完整 Agent 问答渲染窗口和输入框。

信号不应该替换右侧 Agent 问答窗口，也不应第一版放到独立 Dashboard 页。信号应作为左侧栏的**预期差雷达**，负责发现和触发；右侧 Agent 负责下钻分析和决策支持。

### 9.2 左侧栏信号流

在 `Home.vue` 左侧栏新增 `SignalRadar` 组件，放在“新建账目”下方、“最近对话”上方：

```text
Logo
新建账目
预期差信号  <-- 新增
最近对话
过去 7 天
快速分类
用户/系统状态
```

组件行为：

- 展示高价值信号 Top N。
- 列表自动缓慢滚动。
- 鼠标 hover 后暂停滚动。
- 每条信号展示价值分、标题、极短信号摘要、来源、持仓命中标记。
- hover 某条信号时露出“问”按钮。
- 点击信号卡片可展开左侧轻量详情/抽屉。
- 点击“问”后在右侧 Agent 主窗口发起带 `signal_id` 的分析问题。

默认问题模板：

```text
请结合我的持仓，分析这个信号的预期差、传导逻辑、可能受益/受损对象和主要风险。
```

### 9.3 左侧轻量详情

轻量详情只在左侧出现，不占用右侧主画布。

内容：

- 信号标题和价值分。
- 来源类型、发布时间、置信度。
- 原文锚点。
- 传导思想。
- 可能影响对象。
- 持仓命中。
- 操作：`围绕此信号问 Agent`、`查看原始来源`、`忽略`。

### 9.4 右侧 Agent 窗口

右侧仍然保持 `ChatList` + `ChatSender` 的主交互。

用户点击信号的“问”：

1. 前端调用现有 `handleSend` 或扩展 `sendMessage`，传入问题文本。
2. 同时携带 `signal_id` 到后端 Agent 请求。
3. 后端 `SignalContextProvider` 注入该信号上下文。
4. Agent 输出围绕该信号的完整投研分析。

### 9.5 与普通资讯的关系

普通资讯入口继续展示新闻/公告流。信号入口只展示经过抽取、评分、传导后的高价值内容。

设计文案应避免“新闻资讯”表述，统一使用：

- 预期差信号
- 高价值信号
- 信号传导
- 原文锚点
- 围绕此信号问 Agent

---

## 10. API 设计

### 10.1 前端查询

```text
GET /api/v1/signals
```

参数：

```text
scope: all | portfolio | preferences | risk
source_type: announcement | news | irm | research_report
signal_type: string
status: new | viewed | reviewed | dismissed | archived
limit: int = 20
offset: int = 0
```

返回：

```json
{
  "items": [
    {
      "signal_id": "SIG:...",
      "title": "800G 光模块规模量产",
      "summary": "产品量产 -> 订单兑现 -> 供应链需求增强",
      "source_type": "announcement",
      "published_at": "2026-07-13T09:12:00Z",
      "subject_name": "光模块",
      "signal_type": "mass_production",
      "polarity": "positive",
      "value_score": 92,
      "confidence": 0.92,
      "portfolio_hits": ["中际旭创", "新易盛"]
    }
  ],
  "total": 18
}
```

### 10.2 详情查询

```text
GET /api/v1/signals/{signal_id}
```

返回信号详情和传导列表。

### 10.3 状态更新

```text
POST /api/v1/signals/{signal_id}/status
```

请求：

```json
{"status": "viewed"}
```

### 10.4 Agent 带信号提问

扩展 Agent 请求模型，新增可选字段：

```text
signal_id: str | None
```

如果已有请求模型正在引入 `user_id`，则同时保留：

```text
user_id: str | None
signal_id: str | None
```

---

## 11. 测试策略

后端单元测试：

- `stable_signal_id` 对同一输入稳定。
- 规则抽取器能识别量产、政策、CapEx、业绩、订单、风险。
- 去重 upsert 不重复写入。
- 评分规则对公告、持仓命中、风险信号、新鲜度产生预期排序。
- 传导引擎在 mock 图谱/概念数据下生成 1-2 跳候选。
- `SignalContextProvider` 能按 `signal_id` 和问题召回并格式化上下文。
- API 列表、详情、状态更新可用 mock DB 测试。

前端测试：

- `SignalRadar` 渲染空态、加载态、错误态、信号列表。
- hover 暂停滚动。
- hover 展示“问”按钮。
- 点击信号展开轻量详情。
- 点击“问 Agent”调用发送函数并携带 `signal_id`。
- 文本在 260px 左侧栏内不溢出。

集成测试：

- 从 `events` 表新闻生成信号。
- 从 Evidence/公告生成信号。
- 前端列表能显示两个来源的统一信号。
- 点击信号后 Agent 请求包含 `signal_id`，后端注入 `<signal-context>`。

---

## 12. 成功标准

1. 公告和新闻都能进入同一个信号层。
2. 前端左侧栏能看到高价值预期差信号流。
3. 信号列表不是普通新闻列表，每条都包含价值分和传导摘要。
4. 用户 hover 信号流时暂停滚动。
5. 用户点击信号能看到原文锚点和传导思想。
6. 用户点击“问 Agent”后，右侧 Agent 自动围绕该信号分析。
7. Agent 分析上下文包含该信号、传导、持仓命中和来源锚点。
8. 风险信号能对持仓用户优先展示。
9. 信号层不写入买卖结论，不污染知识图谱长期事实层。

---

## 13. 分阶段实施建议

### Phase 1：信号层后端骨架

- Alembic 新增 `signals` 和 `signal_propagations`。
- 新增 `app/signals` 包。
- 实现稳定 ID、规则抽取、去重、评分、API 列表和详情。
- 先接 `events` 新闻来源。

### Phase 2：公告/Evidence 接入与传导

- 从 Evidence/公告抽取信号。
- 实现轻量传导。
- 保存 `signal_propagations`。
- 增加持仓命中计算。

### Phase 3：Agent 注入

- 新增 `SignalContextProvider`。
- Agent 请求支持 `signal_id`。
- `run_lead_agent` 预处理阶段注入 signal context。

### Phase 4：前端 SignalRadar

- `Home.vue` 左侧栏新增 `SignalRadar`。
- 实现自动滚动、hover 暂停、轻量详情、问 Agent。
- 保持右侧 Agent 主窗口不变。

---

*Spec 结束。下一步：用户复审本 spec 后，进入 implementation plan。*
