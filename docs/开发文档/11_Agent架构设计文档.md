# Agent 架构设计文档

> 制定日期：2026-04-25
> 状态：Phase A/B/C/D/E 全部完成
> 参考：deer-flow（/home/10241671/code/OpenSourceProjects/deer-flow）、hermes-agent（/home/10241671/code/OpenSourceProjects/hermes-agent）

---

## 一、整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                         API 层                                   │
│                   POST /api/v1/agent/chat                       │
│                   POST /api/v1/agent/invoke                     │
│                   POST /api/v1/agent/report                    │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│              LangChainAgentClient.run()                          │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  1. Qdrant Pre-search（背景知识注入）                    │   │
│  │  2. ClarificationMiddleware（澄清拦截）                   │   │
│  │  3. MemoryContext（MongoDB 记忆加载）                    │   │
│  │  4. KG Anchors（Neo4j 实体锚点注入）                    │   │
│  │  5. _ensure_agent（共享 Agent 实例缓存）                 │   │
│  │  6. agent.stream()（工具调用循环）← Phase E 并发执行     │   │
│  │  7. HarnessManager（记忆持久化/实体追踪）                 │   │
│  └─────────────────────────────────────────────────────────┘   │
└───────────────────────────┬─────────────────────────────────────┘
                            │
              ┌─────────────┼──────────────────┐
              ▼             ▼                  ▼
     ┌────────────┐  ┌───────────┐  ┌──────────────────┐
     │Clarification│  │ LoopDetec │  │ SubagentLimit    │
     │Middleware  │  │ Middleware│  │ Middleware       │
     │Phase C ✅ │  │  ✅       │  │ Phase C ✅       │
     └────────────┘  └───────────┘  └──────────────────┘

     ┌──────────────────────────────────────────────────────────┐
     │           Phase E: ToolExecutor（工具并发执行）             │
     │                                                          │
     │  can_parallel(tool_calls) → asyncio.gather 并发           │
     │  ├── SAFE_TO_PARALLEL: get_kline / tavily_search /       │
     │  │   get_concept_hot / neo4j_traverse / get_stock_profile │
     │  │   ...（9个只读工具）                                   │
     │  └── NEVER_PARALLEL: clarify / present_chart / write_file │
     └──────────────────────────────────────────────────────────┘

                            │
                            ▼
     ┌─────────────────────────────────────────────────────────┐
     │              工具注册表（YAML 配置驱动）                   │
     │                                                          │
     │  ToolRegistry.get_tool_instances()                        │
     │  ├── get_kline          # K线数据                        │
     │  ├── get_concept_hot    # 概念板块热度                    │
     │  ├── get_market_breadth # 市场广度                        │
     │  ├── neo4j_traverse     # 知识图谱遍历                    │
     │  ├── tavily_search      # 联网检索（tavily-search skill）  │
     │  ├── get_stock_profile  # 公司画像                        │
     │  ├── get_irm           # 投资者关系                      │
     │  ├── get_research_report # 研报检索                      │
     │  ├── get_announcement   # 公告检索                      │
     │  ├── task              # Phase A: SubAgent 并发工具       │
     │  └── present_chart     # 图表生成                        │
     └─────────────────────────────────────────────────────────┘

                            │
                            ▼
     ┌─────────────────────────────────────────────────────────┐
     │           Phase D: ContextCompressor（上下文压缩）         │
     │                                                          │
     │  触发条件：turns > 30 或 tokens > 60000                 │
     │                                                          │
     │  压缩层级：                                              │
     │  1. _prune_tool_results（修剪中间 tool results）         │
     │  2. _protect_head（保护前3条消息）                      │
     │  3. _truncate_tail（尾部20% token保护）                  │
     │  4. _llm_summarize（LLM结构化摘要）                    │
     │  5. Anti-Thrashing（节省<10%时跳过）                    │
     └─────────────────────────────────────────────────────────┘
```

---

## 二、目录结构

```
backend/app/reasoning/langchain_agent/
├── client.py                        # 主执行入口 + ToolExecutor（Phase E）
├── lead_agent.py                    # LeadAgentConfig dataclass
├── integrations.py                   # HarnessConfig / HarnessManager
│
├── middlewares/                     # 中间件链（Phase B/C/D）
│   ├── __init__.py
│   ├── clarification.py             # Phase C: 澄清拦截
│   ├── loop_detection.py            # 循环检测
│   ├── subagent_limit.py            # Phase C: SubAgent 并发限制
│   ├── summarization.py             # Phase D: 基于 ContextCompressor 重写
│   └── context_compressor.py        # Phase D: 核心压缩算法 + Phase E can_parallel
│
├── prompts/
│   ├── lead_system_prompt.py       # System prompt 模板
│   └── memory_context.py            # 分层记忆格式化（Phase B）
│
└── tools/
    ├── __init__.py                  # 工具注册入口
    ├── task_tool.py                 # Phase A: SubAgent 包装为 tool
    └── task_events.py              # SSE task 事件队列
```

---

## 三、核心组件详解

### 3.1 LangChainAgentClient / run_lead_agent

**职责：** API 请求的入口，协调所有组件。

```
用户请求
  │
  ├─ Qdrant pre-search → 背景知识注入
  ├─ ClarificationMiddleware → 澄清拦截
  ├─ MongoDB memory_context → 记忆注入
  ├─ KG anchors → 实体锚点注入
  ├─ _ensure_agent → 共享 agent 实例
  └─ agent.stream() → 工具调用循环（SSE 推送）
       ├─ AIMessage → emit_fn("ai_message")
       ├─ ToolMessage → emit_fn("tool_result")
       └─ Task SSE → emit_fn("task_started/running/completed")
```

### 3.2 Phase C: 中间件链

| 中间件 | 文件 | 职责 |
|--------|------|------|
| ClarificationMiddleware | `clarification.py` | 拦截模糊问题（<10字符 / 无标的）→ clarification_request SSE |
| LoopDetectionMiddleware | `loop_detection.py` | 检测重复调用同一节点 → 注入 loop_warning |
| SubagentLimitMiddleware | `subagent_limit.py` | 限制每轮 task 并发数 → subagent_limit_exceeded SSE |
| LeakDetectionMiddleware | `langalpha.py` | 敏感信息脱敏（LeakDetectionMiddleware） |
| ToolUsageTracker | `tracking.py` | 追踪工具使用统计 |

### 3.3 Phase D: ContextCompressor

**核心算法：**

```python
class ContextCompressor:
    def compress(self, messages: list, current_task: str = "") -> list:
        # 1. 快速路径：低于阈值直接返回
        if not self._should_summarize(messages):
            return messages

        # 2. 修剪旧 tool results（保留首尾，中间替换为占位符）
        pruned = self._prune_tool_results(messages)

        # 3. 保护 head（前3条：system + 首次交换）
        head, tail = self._protect_head(pruned)

        # 4. Tail token 保护（保留20% token）
        kept_tail = self._truncate_tail(tail)

        # 5. LLM 摘要中间部分
        middle = messages[protect_first_n : -len(kept_tail)]
        summary = await self._llm_summarize(middle, current_task)

        # 6. Anti-Thrashing 更新
        self._last_compression_savings_pct = savings

        return head + [summary] + kept_tail
```

**LLM 摘要格式：**
```
## 当前任务
分析光模块行业竞争格局

## 已完成行动
- 收集了中际旭创2024年财务数据
- 整理了行业技术路线（800G/1.6T）

## 遇到障碍
暂无

## 剩余工作
完成竞争格局总结
```

### 3.4 Phase E: ToolExecutor

**并发启发式：**

```python
SAFE_TO_PARALLEL = frozenset({
    "get_kline", "get_concept_hot", "get_market_breadth",
    "neo4j_traverse", "tavily_search", "get_stock_profile",
    "get_irm", "get_research_report", "get_announcement",
})

NEVER_PARALLEL = frozenset({
    "clarify",   # 用户交互，永远串行
    "present_chart",  # 生成文件
    "write_file",
})

def can_parallel(tool_calls: list[dict]) -> bool:
    # 1. 单个工具 → 不并发
    # 2. NEVER_PARALLEL 工具存在 → 不并发
    # 3. 未知工具（非SAFE_TO_PARALLEL）→ 不并发
    # 4. 相同标的（code冲突）→ 不并发
    return True
```

**执行策略：**
```python
async def execute_batch(self, tool_calls: list[dict], harness) -> list:
    if can_parallel(tool_calls):
        # asyncio.gather 并发执行
        tasks = [self._execute_single(name, args, harness) for tc in tool_calls]
        return await asyncio.gather(*tasks)
    else:
        # 串行执行
        return [await self._execute_single(tc["name"], tc["args"], harness)
                for tc in tool_calls]
```

---

## 四、数据流

```
Request: POST /chat
    │
    ▼
Qdrant semantic search → background context
    │
    ▼
ClarificationMiddleware.check_question() → 如果模糊 → SSE clarification_request
    │
    ▼
_load_memory_context() → MongoDB agent_memory collection
    │
    ▼
format_kg_anchors() → Neo4j entity retrieval
    │
    ▼
apply_prompt_template() → system_prompt（含 memory_context + kg_anchors）
    │
    ▼
_ensure_agent() → 共享 LangChain CompiledStateGraph 实例
    │
    ▼
agent.stream() loop（每轮）
    │
    ├── AIMessage → SSE ai_message
    │                   │
    │                   ├─ HarnessManager.update_memory()（异步）
    │                   └─ ToolUsageTracker.record_usage()
    │
    ├── ToolMessage → SSE tool_result
    │                   │
    │                   ├─ LeakDetectionMiddleware（脱敏）
    │                   ├─ BudgetEnforcer（截断）
    │                   └─ HarnessManager.update_memory()（异步）
    │
    └── Task SSE events → task_started / task_running / task_completed
                            │
                            ├─ SubagentLimitMiddleware（并发控制）
                            └─ task_events.py 队列
    │
    ▼
ContextCompressor.compress_sync()（超过阈值时触发）
    │
    ▼
HarnessManager.stop() → 持久化记忆 / 实体追踪
ToolUsageTracker.persist() → 持久化工具统计
    │
    ▼
Response: { content, turns, tool_calls, tool_results, thread_id, tool_usage }
```

---

## 五、Layer 3/4 决策输出层（独立模块）

```
backend/app/reasoning/output/
├── confidence.py     # 置信度体系（TIER0-4，悲观融合，冲突降级）
├── report.py         # AnalysisReport dataclass（结论/催化剂/风险/情景/跟踪指标）
├── compliance.py     # 合规声明生成
└── __init__.py
```

---

## 六、Phase A/B/C/D/E 完成状态

| Phase | 名称 | 状态 | 文件 |
|-------|------|------|------|
| A | task_tool 完整实现 | ✅ | `tools/task_tool.py` |
| B | 记忆分层 schema + MemoryMiddleware | ✅ | `prompts/memory_context.py` |
| C | 中间件链完善（Clarification + SubagentLimit） | ✅ | `middlewares/clarification.py`, `subagent_limit.py` |
| D | 上下文压缩系统（hermes-agent 风格） | ✅ | `middlewares/context_compressor.py` |
| E | 工具并发执行（启发式 asyncio.gather） | ✅ | `client.py ToolExecutor` |

---

## 七、测试覆盖

```
tests/reasoning/
├── test_task_tool.py              # Phase A: 13 tests ✅
├── test_memory_middleware.py       # Phase B: 17 tests ✅
├── test_middleware_chain.py       # Phase C: 11 tests ✅
├── test_context_compressor.py      # Phase D: 35 tests ✅
└── test_tool_concurrency.py       # Phase E: 11 tests ✅
──────────────────────────────────────────────────────────
总计:                                           179 tests ✅
```

---

## 八、与参考项目的对比

| 特性 | deer-flow | hermes-agent | 清水实现 |
|------|-----------|-------------|---------|
| Agent 引擎 | LangGraph | 自研循环 | LangChain V2 |
| SubAgent tool | task_tool.py | delegate_task | task_tool.py ✅ |
| 记忆分层 | updater.py | MemoryProvider | memory_context.py ✅ |
| 上下文压缩 | — | context_compressor.py | context_compressor.py ✅ |
| 工具并发 | — | 启发式 | ToolExecutor ✅ |
| 中间件链 | 15层命名 | 7层 | 6层 ✅ |
| 澄清拦截 | clarification_middleware | clarify tool | clarification.py ✅ |

---

## 九、下一步方向

1. **Phase F（可选）**：Phase F 是 langgraph 迁移（高风险，文档中标注为高风险）
2. **实际集成测试**：使用 VCR/Playback 录制真实 API 响应做 E2E 测试
3. **Phase E 集成验证**：`ToolExecutor` 已就绪，待接入 `agent.stream()` 替代手动执行路径时激活

---

## 十、Phase 7 Runtime Hardening（2026-05-20）

**永久产品边界**：清水系统是投研平台，不是交易或量化执行系统。Agent runtime、工具注册、记忆、提示词、前端事件都不得引入交易、自动下单、券商/交易所执行、量化执行链路。

Phase 7 对 DeerFlow/Hermes 的借鉴采用“局部吸收，不迁移框架”：

| 能力 | 借鉴来源 | 清水落点 |
|------|----------|----------|
| Stream lifecycle | DeerFlow StreamBridge | `reasoning_start` / `thinking` / `tool_called` / `tool_result` / `task_*` / `stream_end` canonical event contract |
| SubAgent delegation | DeerFlow `task` tool | `backend/app/reasoning/tools/builtins/task.py`，仅 lead agent 在 `subagent_enabled=True` 时可用 |
| Run journal | DeerFlow RunJournal + Hermes trajectory | `backend/app/reasoning/runtime/journal.py`，记录 run_id、事件、耗时、错误、token usage |
| Research memory queue | DeerFlow memory queue | `middlewares/memory_queue.py` + `memory_middleware.py`，只持久化投研分类记忆 |
| Tool health | Hermes tool registry | `backend/app/reasoning/tools/registry.py`，TTL health cache |
| Product boundary | Hermes security pattern 的研究化改造 | `backend/app/reasoning/tools/guardrails.py`，注册与调用前拒绝执行意图 |

关键实现约束：

- `/v2/stream` 不再额外补发 `{status: done}` 的 `stream_end`，避免正常完成时双终止事件。
- 旧 `reasoning_started` 在 API 边界映射为 canonical `reasoning_start`。
- `task` 工具包装现有 `SubagentExecutor`，并通过 `task_started` / `task_running` / `task_completed` / `task_failed` 进入同一 SSE 管道。
- `RunJournal-lite` 随 `run_lead_agent` 创建，最终随结果返回 `run_id` 和 compact journal。
- post-run memory 更新在 stream 完成后入队，过滤下单/交易执行意图。
- `validate_tool_boundary()` 会拒绝工具名或描述中出现执行链路语义。
