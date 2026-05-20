# Agent 架构优化路线图

> 制定日期：2026-04-24
> 最后更新：2026-04-26（SSE 流式输出改进 Phase A/B/C/D/E/F 全部完成 ✅）
> 状态：全部完成（Agent 优化全部完成；SSE 流式改进 Phase A/B/C/D/E/F 全部完成 ✅）
> 参考项目：deer-flow（/home/10241671/code/OpenSourceProjects/deer-flow）、hermes-agent（/home/10241671/code/OpenSourceProjects/hermes-agent）
> 维护周期：每次 Phase 完成时更新

---

## 一、现状与目标

### 现状（2026-04-24）

LangChain V2 Agent 已上线，但以下能力缺失或不完整：

| 能力 | 当前状态 | 优先级 |
|------|---------|--------|
| SubAgent `task` tool | `SubagentExecutor` 已实现，但未注册为 V2 tool | 🔴 高 |
| 上下文压缩 | `SummarizationMiddleware` 仅标记，未实际执行 | 🔴 高 |
| V2 中间件链 | 仅 2 个中间件（loop_detection, summarization） | 🟠 中 |
| Memory middleware | V1 Canvas 版本，未接入 V2 | 🟠 中 |
| Clarification middleware | V1 Canvas 版本，未接入 V2 | 🟠 中 |
| 工具并发 | 顺序执行，无并行 | 🟡 低 |
| 自注册工具发现 | YAML 配置驱动 | 🟡 低 |
| 可观测性回调 | 无 callback 接口 | 🟡 低 |

### 目标

将清水 Agent 升级为具备以下能力的投研专用智能体：
1. **多步并发分析**：通过 `task` tool 并行分析多家公司/行业
2. **长对话稳定**：上下文压缩确保 30+ 轮对话不崩溃
3. **完整中间件链**：对齐 deer-flow 15 层中间件设计
4. **投研分层记忆**：区分工作上下文、短期热点、长期判断

---

## 二、参考架构分析

### 2.1 deer-flow 核心精华

**文件位置**：`/home/10241671/code/OpenSourceProjects/deer-flow/backend/packages/harness/deerflow/`

| 精华 | 文件 | 关键行 | 说明 |
|------|------|--------|------|
| SubAgent task_tool | `tools/builtins/task_tool.py` | 22-195 | 注册为 tool，后台轮询，emit SSE 进度 |
| 15 层中间件链 | `agents/lead_agent/agent.py` | 208-265 | 顺序文档化，单一职责 |
| 记忆分层结构 | `agents/memory/updater.py` | 43-59 | workContext / personalContext / facts |
| 记忆流程 | `queue.py` + `updater.py` | — | 队列→防抖→LLM摘要→文件 |
| 工具聚合入口 | `tools/tools.py` | 23-101 | `get_available_tools()` 单入口 |
| Custom SSE task 事件 | `task_tool.py` | 128-161 | task_started / running / completed |
| Clarification 拦截 | `middlewares/clarification_middleware.py` | 91-129 | 返回类型化澄清请求 |
| LangGraph 引擎 | `agents/lead_agent/agent.py` | 268-343 | `create_agent()` 工厂 |

### 2.2 hermes-agent 核心精华

**文件位置**：`/home/10241671/code/OpenSourceProjects/hermes-agent/`

| 精华 | 文件 | 关键行 | 说明 |
|------|------|--------|------|
| 多级上下文压缩 | `agent/context_compressor.py` | 235-1229 | 修剪→保护→尾部→LLM摘要→迭代 |
| 工具并发启发式 | `run_agent.py` | 7651 | 读操作为安全并发，clarify 永不并发 |
| MemoryProvider ABC | `agent/memory_provider.py` | 42-232 | 可插拔多种记忆后端 |
| StepCallbacks | `run_agent.py` | 8907-8933 | step / tool_complete / thinking 等回调 |
| Trajectory 保存 | `agent/trajectory.py` | 30-56 | ShareGPT JSONL 格式 |
| 工具自注册 | `tools/registry.py` | 56 | 模块级 `registry.register()` |

### 2.3 三方取舍决策

| 特性 | 选用来源 | 原因 |
|------|---------|------|
| SubAgent task_tool | **deer-flow** | 已有 `SubagentExecutor`，只需包装成 tool |
| 记忆分层 schema | **deer-flow** | 投资分析师天然需要分层（持仓/热点/背景） |
| 中间件链设计 | **deer-flow** | 命名和职责划分最清晰 |
| 上下文压缩算法 | **hermes-agent** | 多级压缩策略最完整，有 anti-thrashing |
| 工具并发 | **hermes-agent** | 启发式判断比规则更灵活 |
| 记忆 Provider | **hermes-agent** | ABC 模式支持未来多后端 |
| 工具发现 | **自研**（`get_available_tools`） | YAML 配置更符合团队习惯 |

---

## 三、实施计划

### Phase A — task_tool 完整实现 ✅ 已完成

**目标**：将 `SubagentExecutor` 包装为 V2 agent 可调用的 `task` tool

**文件变更**：

```
新增：
  backend/app/reasoning/langchain_agent/tools/task_tool.py   # task tool 实现
  backend/tests/reasoning/test_task_tool.py                 # 单元测试

修改：
  backend/app/reasoning/langchain_agent/tools/__init__.py   # 注册 task_tool
  backend/app/reasoning/langchain_agent/client.py            # 注入 task SSE 事件发射
```

**核心逻辑**（参考 deer-flow `task_tool.py`）：

```python
# task_tool.py 伪代码
@tool("task")
async def task(description: str, subagent_type: str = "general", max_turns: int = 20) -> str:
    """
    将复杂分析任务分解并发执行。
    
    - subagent_type: "industry" | "financial" | "research"
    - max_turns: 子任务最大步数
    """
    # 1. 创建 SubagentExecutor（复用现有代码）
    executor = SubagentExecutor(subagent_type=normalize_subagent_type(subagent_type))
    
    # 2. 后台轮询（每5秒）
    task_id = executor.execute_async(question=description, max_turns=max_turns)
    while not executor.is_done(task_id):
        # emit SSE: task_running
        await emit_fn("task_running", {"task_id": task_id, "status": executor.status(task_id)})
        await asyncio.sleep(5)
    
    # 3. 返回结果
    result = executor.get_result(task_id)
    return format_result(result)  # "Task Completed.\n\n## 分析结论\n..."
```

**验收标准**：
- [x] `task("分析中际旭创竞争格局", subagent_type="industry")` 能并发执行
- [x] SSE 事件序列：`task_started → task_running → task_completed`
- [x] `max_turns` 超出时正确超时
- [x] 单元测试覆盖率 ≥ 80%（13 tests passing）

**预计工时**：1-2 人天（TDD 驱动）

---

### Phase B — 记忆分层 schema + V2 MemoryMiddleware ✅ 已完成（2026-04-25）

**目标**：扩展 MongoDB schema 对齐 deer-flow 分层，设计 V2 MemoryMiddleware

**文件变更**：

```
新增：
  backend/tests/reasoning/test_memory_middleware.py          # 中间件测试
  backend/app/reasoning/langchain_agent/middlewares/memory_middleware.py

修改：
  backend/app/reasoning/memory.py                            # 扩展 schema
  backend/app/reasoning/langchain_agent/middlewares/__init__.py  # 注册中间件
  backend/app/reasoning/langchain_agent/client.py             # 接入中间件链
```

**新记忆 schema**（扩展现有 `agent_memory` collection）：

```python
# 在 facts 文档中新增分层字段
{
    "thread_id": "xxx",
    "analyst_id": "default",
    "agent_name": None,  # None = global memory
    
    "workContext": {
        "summary": "用户当前关注光模块行业和中际旭创",
        "updatedAt": "2026-04-24T10:00:00Z"
    },
    "topOfMind": {
        "summary": "高频提及：中际旭创（Company，4次）",
        "updatedAt": "2026-04-24T10:00:00Z"
    },
    "facts": [
        {
            "content": "中际旭创2024年净利润同比增长150%",
            "category": "financial",  # financial / industry / personal
            "confidence": 0.95,
            "source": "2024年报",
            "createdAt": "2026-04-24T10:00:00Z"
        }
    ],
    "updatedAt": "2026-04-24T10:00:00Z"
}
```

**MemoryMiddleware 伪代码**：

```python
# memory_middleware.py
class MemoryMiddleware:
    """接入 deer-flow 风格分层记忆到 V2 agent"""
    
    async def after_tool(self, tool_name: str, tool_result: str):
        """工具调用后，防抖触发记忆更新"""
        if self.debounce_timer:
            self.debounce_timer.cancel()
        self.debounce_timer = threading.Timer(
            self.debounce_seconds, 
            self._flush_to_mongodb
        )
        self.debounce_timer.start()
    
    def _flush_to_mongodb(self):
        """防抖窗口结束后执行 LLM 摘要 + MongoDB 写入"""
        # 调用 LLM 提取关键事实
        # 更新 workContext / topOfMind
        # 追加 facts（含 confidence 和 source）
```

**验收标准**：
- [x] 多轮对话后 memory_content 包含 workContext + topOfMind
- [x] facts 包含 confidence 字段（0.0-1.0）
- [x] 降级处理（MongoDB 不可用时不阻断 Agent）
- [x] 单元测试覆盖率 ≥ 80%（17 tests passing）

**预计工时**：1 人天

---

### Phase C — 中间件链完善 ✅ 已完成（2026-04-25）

**目标**：对齐 deer-flow 15 层中间件设计，补全清水缺失的中间件

**当前清水中间件 vs deer-flow 中间件**：

| 顺序 | deer-flow | 清水状态 | 操作 |
|------|---------|---------|------|
| 1 | ThreadDataMiddleware | — | 跳过（LangGraph 管理） |
| 2 | SandboxMiddleware | — | 跳过（清水无沙箱） |
| 3 | UploadsMiddleware | — | 跳过（清水无文件上传） |
| 4 | DanglingToolCallMiddleware | — | 跳过（LangGraph 管理） |
| 5 | GuardrailMiddleware | — | 保留未来（内容安全） |
| 6 | ToolErrorHandlingMiddleware | ⚠️ 已有（`middleware/tool_error_handling.py`） | **迁移到 V2** |
| 7 | SummarizationMiddleware | ⚠️ 仅标记 | **升级为真实压缩** |
| 8 | TodoMiddleware | — | 跳过（投研场景不需要） |
| 9 | TokenUsageMiddleware | ⚠️ 已有（`tracking/__init__.py`） | **迁移到 V2** |
| 10 | TitleMiddleware | — | 跳过（清水无标题生成） |
| 11 | MemoryMiddleware | ❌ 未接入 V2 | **Phase B 实现** |
| 12 | ViewImageMiddleware | — | 跳过（清水无图片查看） |
| 13 | DeferredToolFilterMiddleware | — | 跳过（清水无 MCP deferred tools） |
| 14 | SubagentLimitMiddleware | ❌ 仅有注释 | **实现** |
| 15 | LoopDetectionMiddleware | ✅ 已有（`middlewares/loop_detection.py`） | **迁移到 V2** |
| 16 | ClarificationMiddleware | ⚠️ V1 Canvas | **重写为 V2** |

**清水 V2 中间件链（目标）**：

```
1. LoopDetectionMiddleware    ✅ 已有
2. ClarificationMiddleware    ✅ Phase C V2 实现
3. ToolErrorHandlingMiddleware ✅ 已集成（LeakDetectionMiddleware）
4. MemoryMiddleware          ✅ Phase B 实现
5. TokenUsageMiddleware      ✅ 已集成（ToolUsageTracker）
6. SubagentLimitMiddleware   ✅ Phase C V2 实现
7. SummarizationMiddleware   🔄 Phase D 实现
```

**验收标准**：
- [x] 中间件链在 client.py 中正确顺序组装
- [x] ClarificationMiddleware V2 发射 clarification_request SSE（3 tests）
- [x] SubagentLimitMiddleware V2 追踪 task 调用并限制（6 tests）
- [x] 中间件异常降级不阻断 Agent（2 tests）
- [x] 单元测试覆盖率 ≥ 80%（17 tests passing）

**预计工时**：1-2 人天

---

### Phase D — 上下文压缩系统

**目标**：实现 hermes-agent 风格的多级上下文压缩，替换现有仅标记的 `SummarizationMiddleware`

**文件变更**：

```
新增：
  backend/app/reasoning/langchain_agent/middlewares/context_compressor.py  # 多级压缩算法
  backend/tests/reasoning/test_context_compressor.py

修改：
  backend/app/reasoning/langchain_agent/middlewares/summarization.py        # 重写
```

**压缩算法（伪代码）**：

```python
# context_compressor.py
class ContextCompressor:
    """
    多级上下文压缩（参考 hermes-agent context_compressor.py）
    
    触发条件（满足任一）：
      - 超过 30 轮对话
      - 累计 token > 60000
    
    压缩层级：
      1. 修剪旧 tool results（无 LLM 调用，预先保护）
      2. 保护 head messages（system prompt + 首次交换）
      3. Token 尾部保护（保留 20% 预算）
      4. LLM 结构化摘要（Active Task / Completed / Blocked / Remaining）
      5. 迭代更新（后续压缩复用已有摘要）
    """
    
    def compress(self, messages: list) -> list:
        # Step 1: 修剪 tool results（保留首尾，去除中间重复）
        pruned = self._prune_tool_results(messages)
        
        # Step 2: 保护 head
        head_protected = self._protect_head(pruned)
        
        # Step 3: 尾部 token 保护
        if self._estimate_tokens(head_protected) > self.token_budget * 0.8:
            tail_truncated = self._truncate_tail(head_protected, budget_pct=0.2)
        else:
            tail_truncated = head_protected
        
        # Step 4: LLM 摘要中间部分
        middle = self._get_middle(head_protected)
        if middle and self._should_summarize(middle):
            summary = await self._llm_summarize(middle)
            return head_protected + [summary] + tail_truncated
        
        return head_protected + tail_truncated
    
    def _llm_summarize(self, messages: list) -> AIMessage:
        """调用 LLM 生成结构化摘要"""
        prompt = f"""
请将以下对话历史压缩为结构化摘要（保留所有重要信息）：

当前任务：{self.current_task}
已完成行动：{self._extract_completed(messages)}
遇到障碍：{self._extract_blocked(messages)}
剩余工作：{self._extract_remaining(messages)}

输出格式：
## 当前任务
## 已完成行动
## 遇到障碍
## 剩余工作
"""
        return chat(prompt, model=self.summary_model, temperature=0.1)
```

**验收标准**：
- [ ] 30+ 轮对话后，system prompt token 不超 60K
- [ ] 摘要保留原始关键信息（人工抽检）
- [ ] anti-thrashing（上次压缩节省 <10% 时跳过）
- [ ] 单元测试覆盖率 ≥ 80%

**预计工时**：2-3 人天

---

### Phase E — 工具并发执行

**目标**：在 V2 agent 工具执行循环加入 hermes-agent 风格的启发式并发

**文件变更**：

```
修改：
  backend/app/reasoning/langchain_agent/client.py  # 工具执行循环改为 asyncio.gather
```

**并发策略（伪代码）**：

```python
# 在 client.py 的 agent.stream() 循环中

# tool_executor.py
from concurrent.futures import ThreadPoolExecutor

SAFE_TO_PARALLEL = {
    "get_kline",      # 只读市场数据
    "get_stock_profile",  # 只读公司信息
    "neo4j_traverse",  # 只读图谱
    "tavily_search",   # 只读搜索
    "get_concept_hot",  # 只读数据
}

NEVER_PARALLEL = {
    "write_file",    # 写操作
    "present_chart",  # 生成文件
}

def can_parallel(tool_calls: list[dict]) -> bool:
    """判断一组 tool_calls 是否可安全并发"""
    if len(tool_calls) <= 1:
        return False
    if any(tc["name"] in NEVER_PARALLEL for tc in tool_calls):
        return False
    if any(tc["name"] not in SAFE_TO_PARALLEL for tc in tool_calls):
        return False
    # 检查路径冲突（涉及文件路径的 tool）
    paths = [tc["args"].get("path") for tc in tool_calls if "path" in tc["args"]]
    if len(paths) != len(set(paths)):  # 有重复路径
        return False
    return True

# 在 client.py 中
if can_parallel(tool_calls):
    results = await asyncio.gather(*[
        execute_tool(tc) for tc in tool_calls
    ])
else:
    results = [await execute_tool(tc) for tc in tool_calls]
```

**验收标准**：
- [ ] 3 个读工具并发时，响应时间降低 ≥ 50%（实测）
- [ ] 不出现竞态条件（路径冲突检测）
- [ ] `clarify` 工具永远顺序执行

**预计工时**：1 人天

---

## 四、实施顺序与依赖

```
Phase A（task_tool）
    ↓
Phase B（记忆分层 + MemoryMiddleware）←─┐
    ↓                                    │
Phase C（中间件链完善）                   │（可并行，但 Phase B→C 有依赖）
    ↓                                    │
Phase D（上下文压缩）──────────────────────┘（Phase C 完成后进行）
    ↓
Phase E（工具并发）──────────────────────┘（Phase D 完成后进行）
```

---

## 五、进度跟踪

| Phase | 名称 | 状态 | 开始日期 | 完成日期 | 备注 |
|-------|------|------|---------|---------|------|
| A | task_tool 完整实现 | ✅ 已完成 | — | 2026-04-25 | |
| B | 记忆分层 schema + MemoryMiddleware | ✅ 已完成 | — | 2026-04-25 | |
| C | 中间件链完善 | ✅ 已完成 | — | 2026-04-25 | |
| D | 上下文压缩系统 | ✅ 已完成 | 2026-04-25 | 2026-04-25 | TDD 驱动 |
| E | 工具并发执行 | ✅ 已完成 | 2026-04-25 | 2026-04-25 | TDD 驱动 |

| Phase | 名称 | 状态 | 完成日期 | 备注 |
|-------|------|------|---------|------|
| A | SSE 事件类型规范化 | ✅ 已完成 | 2026-04-26 | |
| B | Thinking 流式折叠面板 | ✅ 已完成 | 2026-04-26 | |
| C | Tool Result 渲染增强 | ✅ 已完成 | 2026-04-26 | |
| D | stream_end 内嵌完整报告 | ✅ 已完成 | 2026-04-26 | TDD 驱动 |
| E | 错误处理与保活增强 | ✅ 已完成 | 2026-04-26 | TDD 驱动 |

## 八、SSE 流式输出推送前端展示（2026-04-26 新增）

> 对应 `/plan` 规划的 Phase A-D 实施计划

### Phase A — SSE 事件类型规范化 ✅ 已完成

**目标**：统一后端 emit_fn 事件类型，含截断元信息

**后端改动**：

| 文件 | 变更 |
|------|------|
| `manual_agent_loop.py` | `ai_message` → `thinking_delta`，`tool_call` → `tool_called`，`tool_result` 增加 `truncated/original_len/truncated_len/duration_ms` |
| `client.py` | `agent.stream()` 路径同步更新为 `thinking_delta` |
| `agent.py` | `_emit_to_manager` 接收 Phase A 事件；`_VISIBLE_MAP` 透传所有 Phase A 事件；`_FILTERED` 清空 |
| `tests/test_sse_events.py` | **新建** 10 个验收测试 |
| `tests/test_manual_agent_loop.py` | 更新 2 个旧事件名测试 |
| `tests/test_manual_agent_loop_integration.py` | 更新 1 个旧事件名测试 |
| `tests/test_sse_event_filter.py` | 更新 9 个事件过滤测试 |

**统一事件类型**：

```
后端 emit_fn：           前端 SSE：
thinking_delta    →      thinking（LLM 思考）
tool_called     →      tool_called（工具调用）
tool_result    →      tool_result（含 truncated 元信息）
stream_end     →      stream_end（含报告）
error          →      error
```

**新增 tool_result 元信息**：
```python
{
    "id": "call_1",
    "name": "get_kline",
    "result": "x" * 2000 + "...",
    "truncated": True,        # 是否截断
    "original_len": 5000,     # 原始长度
    "truncated_len": 2000,    # 截断后长度
    "duration_ms": 234.5,     # 执行耗时
}
```

**验收标准**：221 后端测试全部通过

---

### Phase B — Thinking 流式折叠面板 ✅ 已完成

**目标**：实时看到 LLM 思考过程，流结束后保留供查看

**前端改动**：

| 文件 | 变更 |
|------|------|
| `useStreamingRenderer.js` | `finalize()` 保留 thinking 内容并渲染 markdown；新增 `thinkingStartTime/EndTime` 追踪 |
| `ReportView.vue` | thinking 事件优先取 `delta` 字段；🧠图标+实时时长；流结束后自动折叠（`:open` 绑定） |
| `tests/sse_streaming.test.js` | **新建** 24 个验收测试（Vitest） |
| `vite.config.js` | 新增 `test.environment: jsdom` |
| `package.json` | 新增 `vitest`/`@vue/test-utils`/`jsdom` 依赖 |

**UI 改进**：
```
之前：<details open> 纯文字 "思考过程"
现在：<details :open="isLoading">
        ├─ 🧠 思考过程  [12秒]     ← 实时时长
        └─ <渲染后的 markdown 内容>  ← 流结束后也保留
```

**验收标准**：
- 24 个前端测试全部通过
- 前端构建成功（`pnpm build`）
- 221 个后端测试无回归

---

### Phase C — Tool Result 渲染增强 ✅ 已完成

**目标**：CoT 步骤条更有信息量

**前端改动**：

| 文件 | 变更 |
|------|------|
| `useStreamingRenderer.js` | `appendToolResult` 第4参数 `meta`（`duration_ms/truncated/original_len/truncated_len`）；新增导出辅助函数 |
| `ReportView.vue` | 导入 Phase C 辅助函数；CoT 模板使用图标/中文名/耗时/格式化结果 |
| `tests/sse_streaming.test.js` | **新增** 26 个 Phase C 测试（工具名映射/图标/参数格式化/耗时/K线检测/JSON格式化/截断提示） |

**UI 改进**：
```
之前：✓ get_kline         完成        ← 纯英文工具名
现在：📈 K线查询 [1.2秒]  完成        ← 中文名 + 图标 + 耗时
```

**格式化结果展示**：
- JSON 数据自动美化缩进
- truncated 结果追加 `[...+400 字符被截断]`
- K 线数据（检测 `date`/`open`/`close` 等字段）可扩展为迷你表格

**验收标准**：
- 52 个前端测试全部通过
- 前端构建成功
- 221 个后端测试无回归

---

### Phase D — stream_end 内嵌完整报告 ✅ 已完成

**目标**：消除 stream_end 后 REST 查询的网络往返

**后端改动**：
- `ManualAgentLoop.run()` 结束时发射 `stream_end`（含 `report_content`/`report_json`/`report_id`/`compliance_passed`）
- `_build_analysis_report()` 辅助函数：构造 AnalysisReport + 合规扫描
- `client.py` 中 `use_manual_loop` 路径不再重复发射 `reasoning_end`

**前端改动**：
- `ReportView.vue` 的 `stream_end` 分支：优先取 `event.data.report_content`，无内嵌数据时降级 REST

**新增测试**：
- `tests/reasoning/test_sse_events.py`：7 个 Phase D 测试
- `frontend/tests/sse_streaming.test.js`：14 个 Phase D 测试

**UI 效果**：SSE stream_end 到达后直接渲染报告，无额外网络往返

---

### Phase E — 错误处理与保活增强 ✅ 已完成

**目标**：健壮的长连接 + 用户友好的错误展示

**后端改动**：
- `agent_events.py`：`PING_INTERVAL = 60` 常量 + `event_generator` 每 60s yield ping 事件
- `emit_error` 事件包含 `error_type` 字段（timeout/model_error/tool_error/auth_error/internal_error）

**前端改动**：
- `ReportView.vue`：`ping` 事件静默忽略，不触发 phase 变化
- `onerror` 指数退避重连（1s → 2s → 4s，最多 3 次）
- `getFriendlyErrorMsg(errorType)` 函数：错误类型 → 友好文案映射
- `sseRetryCount` 状态：`stream_end` 到达后归零；`disconnect()` 时归零

**新增测试**：
- 后端：`tests/reasoning/test_sse_events.py` 6 个 Phase E 测试
- 前端：`tests/sse_streaming.test.js` 16 个 Phase E 测试

---

### Phase F — tool_result Preview 替代原始数据 ✅ 已完成（2026-04-26）

**目标**：减少 SSE 推送体积，避免大 JSON 阻塞通道；参考 Hermes-agent 的 tool preview 策略

**方案（方案B：后端解析 Markdown 生成 preview）**：
- 所有工具返回 Markdown 格式化文本（不是 JSON）
- `build_preview(tool_name, markdown_text)` 从 Markdown 中用正则提取统计字段，生成 30-100 字符描述性 preview
- `ToolResult` 新增 `preview` 字段
- `tool_result` SSE 事件推送 `result=preview`（不再推送截断后的原始 Markdown）
- `success` 字段添加到 SSE 事件（之前缺失）
- `truncated/truncated_len` 字段移除（不再需要硬截断）

**预览生成规则**：

| 工具 | Preview 格式 | 正则 |
|------|------------|------|
| `get_kline` | "查询到 {N} 条K线数据" | `共(\d+)条` |
| `tavily_search` | "找到 {N} 篇相关文章" | `^\*\*\d+\.` 计数 |
| `get_announcement` | "获取到 {N} 条公告" | `（共\s*(\d+)\s*条` |
| `get_research_report` | "获取到 {N} 篇研报" | `（共\s*(\d+)\s*条` |
| `get_concept_hot` | "热度排名共 {N} 个板块" | `（(\d+)\s*条）` |
| `get_market_breadth` | "市场情绪：{情绪}" | `市场情绪[：:]*\s*\*\*([^*]+)\*\*` |
| `neo4j_traverse` | "获取到 {N} 条关系" | `的直接关系[（(](\d+)\s*条` |
| `get_irm` | "获取到 {N} 条互动易问答" | `（共\s*(\d+)\s*条` |
| `present_chart` | "图表已生成" / "图表渲染失败" | 字面判断 |
| `get_stock_profile` | "主营业务：{关键词}" | `主营业务[：:]*\s*([^\"\n]{4,60})` |
| 错误结果 | "{工具名} 查询失败：{原因}" | 错误前缀匹配 |
| 兜底 | "{工具名}：{前60字}" | — |

**测试覆盖**：16 个新测试用例（`TestToolResultPreview`）
- 各工具 preview 格式正确性
- `success` 字段存在性
- 空结果/错误结果兜底
- 前端字段适配（`truncated` 移除）

---

## 六、风险与缓解

| 风险 | 级别 | 缓解措施 |
|------|------|---------|
| deer-flow 的 LangGraph 迁移路径不兼容 | 高 | 不迁移引擎，保持 LangChain V2，只借鉴中间件命名 |
| task_tool 后台轮询阻塞事件循环 | 高 | 用 `asyncio.create_task()` 非阻塞轮询，emit_fn 异步发射 SSE |
| 上下文压缩导致信息丢失 | 中 | anti-thrashing + 人工抽检流程 |
| MongoDB 不可用时记忆降级 | 低 | 所有操作加 try/except，返回空字符串不阻断 |
| Phase B schema 变更影响现有数据 | 中 | MongoDB schema 向后兼容，新增字段加默认值 |

---

## 七、成功标准

所有 Phase 完成后，清水 Agent 达成：

1. **task 工具可用**：复杂分析任务（5家竞品对比）并发完成，耗时降至 1/N
2. **长对话稳定**：50 轮对话无崩溃，token 不超 80K
3. **记忆有效**：3轮对话后，memory_content 包含分层信息
4. **中间件健壮**：任一中间件异常不阻断 Agent，有降级日志
5. **测试覆盖**：所有新代码 ≥ 80% 覆盖率，86 → 150+ 测试数

---

## 八、Phase 7 — Agent Runtime Hardening ✅ 已实施（2026-05-20）

**边界声明**：清水投研系统永远不涉及交易、自动下单、券商执行、交易所执行、量化执行链路。所有 Agent 能力仅服务于投研分析、证据整理、风险识别、催化跟踪和假设验证。

### 8.1 已完成改动

| 模块 | 改动 |
|------|------|
| SSE 协议 | canonical `reasoning_start`，兼容旧 `reasoning_started`；移除 `/v2/stream` 正常完成时额外 `stream_end` |
| SubAgent | 新增 `tools/builtins/task.py`，包装 `SubagentExecutor`，仅 `subagent_enabled=True` 时进入 lead agent 工具集 |
| Task events | `task_started` / `task_running` / `task_completed` / `task_failed` 进入前后端统一流管道 |
| RunJournal-lite | 新增 `runtime/journal.py`，记录 run_id、事件、耗时、错误、token usage，结果中返回 compact journal |
| MemoryQueue-lite | 新增 `middlewares/memory_queue.py` 与 `memory_middleware.py`，按投研分类过滤并异步更新记忆 |
| Tool health | 新增 `tools/registry.py`，对工具 availability 做 TTL cache |
| Product boundary | 新增 `tools/guardrails.py`，工具注册、task 调用、memory 持久化均拒绝执行意图 |
| Frontend stream | `useStreamPipeline.ts` / `useChatSession.ts` 支持 `reasoning_start` 和 `task_*` 事件 |

### 8.2 测试

新增/更新测试：

- `tests/reasoning/test_sse_events.py`
- `tests/reasoning/test_subagent_task_tool.py`
- `tests/reasoning/test_run_journal.py`
- `tests/reasoning/test_memory_queue.py`
- `tests/reasoning/test_tool_registry.py`
- `tests/reasoning/test_product_boundary.py`
- `tests/reasoning/test_v2_agent_integration.py`

验证结果：

```bash
cd backend
python -m pytest tests/reasoning/test_sse_events.py tests/reasoning/test_subagent_task_tool.py tests/reasoning/test_run_journal.py tests/reasoning/test_memory_queue.py tests/reasoning/test_tool_registry.py tests/reasoning/test_product_boundary.py tests/reasoning/test_sse_event_filter.py tests/reasoning/test_task_events.py tests/reasoning/test_stream_report_bugs.py tests/reasoning/test_v2_agent_integration.py -q
# 72 passed, 2 skipped, 1 warning
```

前端构建验证当前受阻：`npm run build` 失败于 `vite: command not found`，需要先安装 frontend 依赖。
