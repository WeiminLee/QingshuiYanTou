# System Memory and Agent Context Design

**日期**：2026-07-22  
**范围**：清水投研系统第一阶段系统记忆底座，聚焦 Signal 主链路的记忆路由、上下文组装、DTO 契约和 Agent 注入。  
**性质**：设计规格，供 implementation plan -> TDD 实现。  
**相关设计**：
- `2026-07-13-用户记忆系统设计.md`：用户画像、偏好、笔记、持仓读取。
- `2026-07-15-signal-model-redesign.md`：信号本体、生命周期、观察聚合方向。
- `2026-07-21-data-readiness-freshness-gate-design.md`：数据新鲜度约束。

---

## 1. 背景与问题

当前记忆系统已经能支撑 Agent 的用户级上下文：

- 按 `user_id` 读取用户画像、偏好、笔记和持仓。
- 在 Agent turn 开始前注入 `<memory-context>`。
- 通过 `manage_memory` 工具写入少量用户记忆。
- 在 shutdown 时 drain 异步记忆同步任务。

但这仍然只是 **User Memory**，无法承担整个投研系统对记忆的完整需求。清水投研的核心场景不是简单聊天记忆，而是：

```text
外部信息 -> Evidence -> Signal -> KG 2-hop propagation -> 用户命中 -> Agent 分析 -> 用户处理/后续验证
```

这条链路需要记住的不只是“用户喜欢什么”，还包括：

| 需求 | 当前状态 | 缺口 |
|------|----------|------|
| 信号是否出现过 | `signals` 有当前记录 | 缺少系统级生命周期记忆视角 |
| 信号是否命中用户 | `metadata.portfolio_hits` 可展示 | 缺少按当前 `user_id` 动态匹配 |
| 二阶路径是否可解释 | `SignalPath` DTO 已有雏形 | 缺少统一上下文包给 Agent/前端复用 |
| Agent 应该读取哪些记忆 | 当前直接 prefetch user memory | 缺少 MemoryRouter 分流 |
| 长历史综合 | 目前只有 trace/journal | 第一阶段不做重型合成，但需要预留边界 |

核心判断：**不要把所有记忆都塞进一个 MemoryProvider，也不要让 Agent 在 prompt 中自行决定查什么。** 系统应在 Agent 调用前根据请求类型组装稳定的 `AgentContext`。

---

## 2. 设计目标与非目标

### 2.1 目标

第一阶段只解决 Signal 主链路的系统记忆和上下文组装：

1. 定义 `MemoryRouter`，把请求分成三类记忆负载：
   - `factual_lookup`
   - `relation_reasoning`
   - `broad_synthesis`
2. 定义 `AgentContextBuilder`，统一组装 Agent 可消费上下文。
3. 定义稳定 DTO：
   - `UserSnapshotDTO`
   - `SignalMemoryDTO`
   - `SignalContextDTO`
   - `AgentContextDTO`
4. 让 Agent 的 `signal_id` 注入改为读取 `AgentContext`，而不是散落读取 signal metadata。
5. 保留现有 `UserMemoryProvider`，将其定位为 `User Memory`，不推翻重写。

### 2.2 非目标

第一阶段明确不做：

- 不做全局长期记忆重构。
- 不做所有历史对话向量化。
- 不做 LLM 驱动的 MemoryRouter。
- 不做复杂自进化或自动反思系统。
- 不把 Signal 生命周期完整重建为新表；第一阶段优先基于现有 `signals.status` 和 metadata 扩展。
- 不要求外部 API key；需要能用 fixture 跑通最小闭环。

---

## 3. 记忆分层

系统记忆分为五层，但第一阶段只实现 L0-L3 的 Signal 主链路部分。

```text
L0 Runtime Context
  本轮 question、thread_id、signal_id、页面入口、readiness。

L1 User Memory
  用户画像、偏好、持仓、关注列表、笔记。
  权威实现继续使用 UserMemoryProvider 和 account portfolio。

L2 Signal Memory
  信号状态、生命周期摘要、用户处理状态、强化/反证计数。

L3 KG Path Memory
  SignalPropagation、SignalPath、2-hop path、路径置信度。

L4 Research Memory
  Agent 历史判断、研究假设、复盘结果、长周期用户风格。
  第一阶段只预留，不实现。
```

这对应三类记忆负载：

| 负载类型 | 典型问题 | 应读取层级 | 第一阶段策略 |
|----------|----------|------------|--------------|
| `factual_lookup` | “我是否持有中际旭创？” | L1 | 结构化查询，不走 RAG |
| `relation_reasoning` | “这个信号如何影响我的持仓？” | L0+L1+L2+L3 | 组装 Signal AgentContext |
| `broad_synthesis` | “过去一个月我关注方向有什么变化？” | L1+L2+L4 | 第一阶段降级为轻量摘要/明确能力边界 |

---

## 4. 架构

### 4.1 总体流向

```text
Agent API
  question + user_id + thread_id + optional signal_id
        |
        v
MemoryRouter
  classify route: factual_lookup / relation_reasoning / broad_synthesis
        |
        v
AgentContextBuilder
  + UserSnapshotProvider
  + SignalContextProvider
  + ReadinessProvider
  + Future ResearchMemoryProvider
        |
        v
AgentContextDTO
  structured fields + prompt_context
        |
        v
run_lead_agent
  inject prompt_context into system prompt
  store context metadata into AgentTurnContext / trace
```

### 4.2 与现有模块关系

| 模块 | 保留/新增 | 责任 |
|------|-----------|------|
| `reasoning/langchain_agent/memory/user_memory_provider.py` | 保留 | User Memory 的读写和 prompt 片段 |
| `signals/service.py` | 扩展 | 输出稳定 Signal DTO，不泄漏内部 metadata |
| `signals/context_provider.py` | 重构 | 从 AgentContextBuilder 获取上下文 |
| `reasoning/runtime/turn_context.py` | 扩展 | 保存 `agent_context` 结构化摘要 |
| `reasoning/context/` 或 `reasoning/memory_context/` | 新增 | MemoryRouter 和 AgentContextBuilder |

第一阶段建议新增包：

```text
backend/app/reasoning/context/
  __init__.py
  router.py
  builder.py
  schemas.py
```

命名使用 `context` 而不是 `memory`，避免和现有 UserMemoryProvider 混淆。它负责“运行前上下文组装”，不是直接管理用户长期记忆。

---

## 5. DTO 设计

### 5.1 通用原则

1. DTO 是外部契约，不等同 ORM/Mongo 模型。
2. 前端和 Agent 只读 DTO 字段，不读取 `metadata.path_nodes` 等内部结构。
3. 列表轻、详情重、AgentContext 可裁剪。
4. 用户相关字段统一为 `user_hits`，旧字段 `portfolio_hits` 保留兼容。
5. DTO 带 `schema_version`，便于未来升级。

### 5.2 `UserSnapshotDTO`

```json
{
  "schema_version": "user.snapshot.v1",
  "user_id": "lwm",
  "portfolio": [
    {"ts_code": "300308.SZ", "name": "中际旭创"}
  ],
  "watchlist": [
    {"ts_code": "300502.SZ", "name": "新易盛", "note": "关注800G"}
  ],
  "preferences": [
    {
      "subject": "光模块",
      "subject_type": "concept",
      "stance": "关注",
      "reason": "AI算力需求拉动"
    }
  ]
}
```

第一阶段 `portfolio` 读取 account portfolio；`watchlist` 可先为空或接现有 stocks watchlist；`preferences` 读取 UserMemoryProvider 的 Mongo preferences。

### 5.3 `SignalMemoryDTO`

```json
{
  "schema_version": "signal.memory.v1",
  "signal_id": "SIG:abc",
  "lifecycle_status": "active",
  "user_status": "new",
  "first_seen_at": "2026-07-22T20:30:00Z",
  "last_seen_at": "2026-07-22T20:30:00Z",
  "reinforced_count": 0,
  "contradicted_count": 0,
  "source_count": 1
}
```

第一阶段映射规则：

- `lifecycle_status`：优先取 `signal.metadata.lifecycle`，无则默认 `active`。
- `user_status`：取 `signals.status`。
- `first_seen_at`：取 `created_at` 或 `detected_at`。
- `last_seen_at`：取 `updated_at` 或 `detected_at`。
- `reinforced_count` / `contradicted_count` / `source_count`：优先取 metadata，无则 0/1。

这避免第一阶段新建生命周期表，同时为后续 Signal Memory 表预留契约。

### 5.4 `SignalContextDTO`

```json
{
  "schema_version": "signal.context.v1",
  "signal": {
    "signal_id": "SIG:abc",
    "title": "某公司业绩预增",
    "summary": "可能验证光模块景气度延续",
    "source_type": "announcement",
    "published_at": "2026-07-22T20:30:00Z",
    "subject_name": "中际旭创",
    "subject_type": "company",
    "signal_type": "earnings",
    "polarity": "positive",
    "value_score": 86,
    "confidence": 0.78
  },
  "source": {
    "type": "announcement",
    "id": "ann_001",
    "title": "2026 半年度业绩预告",
    "url": "https://example.com/ann_001",
    "published_at": "2026-07-22T20:30:00Z"
  },
  "primary_signal": {
    "subject_name": "中际旭创",
    "subject_type": "company",
    "signal_type": "earnings",
    "polarity": "positive",
    "strength": 85,
    "confidence": 0.78,
    "evidence_excerpt": "预计净利润同比增长..."
  },
  "memory": {
    "lifecycle_status": "active",
    "user_status": "new",
    "reinforced_count": 0,
    "contradicted_count": 0
  },
  "user_hits": {
    "portfolio": ["中际旭创"],
    "watchlist": ["新易盛"],
    "preferences": ["光模块"]
  },
  "propagations": [
    {
      "target_name": "光芯片",
      "target_type": "product",
      "secondary_type": "supply_chain_validation",
      "direction": "beneficiary",
      "impact_horizon": "short",
      "confidence": 0.72,
      "reasoning": "业绩信号沿上游路径传导，可能验证光芯片需求弹性。",
      "signal_path": {
        "nodes": ["中际旭创", "光模块", "光芯片"],
        "edges": [
          {
            "source": "中际旭创",
            "target": "光模块",
            "relation_type": "PRODUCES",
            "label": "生产"
          }
        ],
        "hops": 2,
        "confidence": 0.72
      }
    }
  ]
}
```

兼容要求：

- 后端可以继续返回 `portfolio_hits` 给旧前端。
- 新前端和 Agent 优先读取 `user_hits.portfolio`。
- `signal_path` 必须稳定输出 `nodes`、`edges`、`hops`、`confidence`。

### 5.5 `AgentContextDTO`

```json
{
  "schema_version": "agent.context.v1",
  "context_type": "signal_research",
  "route": "relation_reasoning",
  "user_id": "lwm",
  "thread_id": "thread-001",
  "question": "请结合我的持仓分析这个信号",
  "user_snapshot": {},
  "signal_context": {},
  "readiness_context": {
    "overall_status": "fresh",
    "answer_boundary": "数据源当前可用于日级分析"
  },
  "prompt_context": "<agent-context>...</agent-context>",
  "warnings": []
}
```

`prompt_context` 是 Agent system prompt 注入文本，结构化字段用于前端、trace、测试和后续任务模块复用。

---

## 6. MemoryRouter

### 6.1 输入

```text
question: str
user_id: str
thread_id: str
signal_id: str | None
page_context: dict | None
```

### 6.2 输出

```json
{
  "route": "relation_reasoning",
  "reason": "signal_id provided",
  "required_context": ["user_snapshot", "signal_context", "readiness_context"]
}
```

### 6.3 第一版规则

| 条件 | route |
|------|-------|
| 有 `signal_id` | `relation_reasoning` |
| question 包含 “这个信号/传导/影响我的持仓/产业链/二阶” | `relation_reasoning` |
| question 包含 “我是否/我有没有/我的持仓/我的关注” 且无 signal_id | `factual_lookup` |
| question 包含 “过去/最近一个月/总结/复盘/长期/变化趋势” | `broad_synthesis` |
| 默认 | `relation_reasoning` |

第一阶段 `broad_synthesis` 不做重型长历史检索。Builder 应返回轻量 UserSnapshot + 明确 warning：

```text
long_history_synthesis_not_enabled
```

---

## 7. AgentContextBuilder

### 7.1 责任

`AgentContextBuilder` 负责把多个系统来源组装成一个稳定上下文包：

```text
build(user_id, thread_id, question, signal_id=None, page_context=None) -> AgentContextDTO
```

### 7.2 构建步骤

1. 调用 `MemoryRouter.classify(...)` 得到 route。
2. 构建 `UserSnapshotDTO`：
   - portfolio：account portfolio。
   - preferences：agent_preferences。
   - watchlist：可选接入现有 watchlist；失败时为空并加 warning。
3. 若有 `signal_id` 或 route 为 `relation_reasoning`：
   - 有 `signal_id` 时查询 `SignalDetail`。
   - 有 Signal detail 时构建 `SignalMemoryDTO`。
   - 有 Signal detail 时动态匹配 `user_hits`。
   - 有 Signal detail 时保留 `SignalPath`。
   - 无 `signal_id` 的 `relation_reasoning` 请求只返回 UserSnapshot + Readiness，并追加 `signal_context_missing` warning。
4. 读取 readiness context。
5. 生成 `prompt_context`。

### 7.3 动态 user_hits 匹配

第一版使用规则匹配，不调用 LLM：

```text
candidate names =
  signal.subject_name
  propagation.target_name
  signal_path.nodes
  metadata.primary_subject
```

匹配目标：

- portfolio.name / portfolio.ts_code
- watchlist.name / watchlist.ts_code
- preferences.subject

规则：

- 精确命中优先。
- 中文包含匹配作为兜底，最小长度 >= 2。
- 去重后输出名称，不输出内部 id。
- 不修改原始 signal metadata；这是请求时动态视图。

### 7.4 prompt_context 格式

第一阶段 prompt 使用单一外层 fence：

```text
<agent-context>
route: relation_reasoning

<user-snapshot>
- 持仓: 中际旭创(300308.SZ)
- 偏好: [关注] 光模块
</user-snapshot>

<signal-context>
- 信号: 某公司业绩预增
  signal_id: SIG:abc
  value_score: 86, confidence: 0.78
  原文锚点: 预计净利润同比增长...
  生命周期: active, 用户状态: new
  用户命中: portfolio=中际旭创; preferences=光模块
  传导: 中际旭创 -> 光模块 -> 光芯片
  二阶类型: supply_chain_validation
  理由: ...
</signal-context>

<data-readiness-summary>
overall_status: fresh
answer_boundary: ...
</data-readiness-summary>
</agent-context>
```

现有 `<memory-context>` 和 `<data_readiness>` 可以继续存在。第一阶段为了降低风险，`AgentContextBuilder` 先替代现有 `signal_context` 生成逻辑，不替代 UserMemoryProvider 的 `<memory-context>`。

---

## 8. API 与前端契约

### 8.1 后端 API

第一阶段新增或扩展：

```text
GET /api/v1/signals/{signal_id}
  返回 SignalContextDTO 兼容字段：
  - 原有 SignalDetail 字段保留
  - 新增 schema_version
  - 新增 source
  - 新增 primary_signal
  - 新增 memory
  - 新增 user_hits
  用户态字段 user_hits 需要从认证上下文或可选 user_id 查询参数解析；无法解析用户时返回空 user_hits。

GET /api/v1/signals/{signal_id}/context
  返回 AgentContextDTO
  参数: user_id, thread_id, question 可选；user_id 缺省时走现有 resolve_user_id 兼容逻辑。
```

`/context` 第一版可以先作为内部服务函数，不一定立刻开放前端 API。若开放，应保持只读。

### 8.2 前端

第一阶段前端只需要逐步消费：

- `user_hits.portfolio` 替代直接读 `portfolio_hits`。
- Signal detail 展示：
  - 原始证据。
  - 一阶信号。
  - 二阶 KG path。
  - 用户命中。
  - 生命周期/用户处理状态。

前端不负责组装 Agent prompt。点击“围绕此信号问 Agent”时仍只传 `signalId` 和问题。

---

## 9. 错误处理与降级

所有上下文构建必须 fail-soft：

| 失败点 | 降级 |
|--------|------|
| User memory 读取失败 | `user_snapshot` 为空，追加 warning |
| portfolio 读取失败 | portfolio 为空，追加 warning |
| watchlist 读取失败 | watchlist 为空，追加 warning |
| Signal 不存在 | 若 API 调用返回 404；AgentContext 返回 warning 并不注入 signal_context |
| KG propagation 为空 | 返回空 propagations，不阻塞 Agent |
| readiness 失败 | 使用现有 unavailable freshness context |
| broad_synthesis 请求 | 返回轻量上下文和 `long_history_synthesis_not_enabled` warning |

错误不能让 Agent API 整体不可用，除非核心请求对象不存在，例如用户明确请求的 `signal_id` 不存在。

---

## 10. 测试策略

### 10.1 单元测试

- `MemoryRouter`
  - 有 signal_id -> `relation_reasoning`
  - 持仓事实问题 -> `factual_lookup`
  - 长历史总结问题 -> `broad_synthesis`
  - 默认 route 稳定

- `UserSnapshotDTO`
  - portfolio/preferences/watchlist 正常组装
  - 任一来源失败时 fail-soft

- `SignalContextDTO`
  - 输出 `signal_path.nodes/edges/hops/confidence`
  - 输出 `user_hits`
  - 兼容旧 `portfolio_hits`

- `AgentContextBuilder`
  - signal_id 场景包含 user_snapshot、signal_context、readiness_context
  - broad_synthesis 返回 warning
  - prompt_context 包含 `<agent-context>` 且不丢失 `<signal-context>`

### 10.2 集成测试

使用现有 fixture：

```text
POST /api/v1/signals/fixtures/concept-board?concept=optical_module
GET /api/v1/signals
GET /api/v1/signals/{signal_id}
AgentContextBuilder.build(signal_id=...)
```

验证：

- 无外部 API key 也能构建完整 signal context。
- 2-hop `SignalPath` 保留。
- user_hits 根据模拟 portfolio/preference 动态命中。

### 10.3 回归测试

- 现有 memory 测试继续通过。
- 现有 signals API 测试继续通过。
- 现有 freshness gate 测试继续通过。
- Agent signal_id 注入测试改为验证 AgentContextBuilder 输出。

---

## 11. 分阶段实施

### Phase 1: Contract and Builder

1. 新增 `reasoning/context/schemas.py`。
2. 新增 `MemoryRouter` 规则版。
3. 新增 `AgentContextBuilder`。
4. 从现有 signal service 组装 `SignalContextDTO`。
5. 保留旧字段兼容。

### Phase 2: Agent Integration

1. `run_lead_agent` 中 signal_id 上下文改由 builder 生成。
2. `AgentTurnContext` 增加 `agent_context` 元数据。
3. trace/report 保存 route、warnings、signal_id、user_hits。

### Phase 3: User Hit Matching

1. portfolio 动态命中。
2. watchlist 动态命中。
3. preferences 动态命中。
4. 前端 Signal detail 消费 `user_hits`。

### Phase 4: Signal Memory Lifecycle

1. 基于 metadata 补 `reinforced_count`、`contradicted_count`、`source_count`。
2. 增加状态更新服务，记录 viewed/tracked/reviewed/dismissed。
3. 后续再决定是否拆出独立 `signal_memory` 表。

---

## 12. 成功标准

第一阶段完成后，应满足：

1. 给定 `signal_id`，后端能构建一个完整 `AgentContextDTO`。
2. Agent 不再直接依赖 signal metadata 细节。
3. 前端和 Agent 都能读取同一套 `SignalPath`、`user_hits`、`SignalMemory`。
4. 无 API key 时可用 fixture 验证 Signal 主链路上下文闭环。
5. UserMemoryProvider 保持原职责，不被系统级 Signal Memory 污染。
6. 长历史合成请求不会误装作已支持，而是明确降级。

---

## 13. 未来扩展

后续可在不破坏第一阶段契约的基础上增加：

- `ResearchMemory`：Agent 历史判断、证据引用、后续验证结果。
- `KGPathMemory`：路径有效性统计、低质量路径降权。
- `SignalLifecycle` 独立表：强化、反证、过期、用户处理历史。
- LLM Router：在规则路由不足时辅助判断记忆负载。
- Memory evaluation：衡量回答质量、延迟和上下文 token 成本。
