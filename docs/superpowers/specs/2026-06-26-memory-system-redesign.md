# Memory System Redesign — Provider Architecture + Memory Tool + Context Compression

Date: 2026-06-26

## Context

当前记忆系统有三个碎片化子系统，且均存在严重问题：

| 子系统 | 状态 | 问题 |
|--------|------|------|
| Harness MemoryManager（流内 LLM 摘要） | 死代码 | 所有 API 端点未传 `harness_config`，从不激活 |
| Post-Run Memory Queue（关键词分类） | 工作中 | 仅 post-run，无法在流内注入记忆 |
| Pre-Run 上下文加载 | 断裂 | `app.reasoning.middlewares.memory` 模块不存在，`get_memory_context_async()` 永远返回 `""` |

目标：参考 hermes-agent 的 MemoryProvider + MemoryManager 架构，重建记忆系统，使 agent 能：
1. 在每轮 LLM 调用前召回历史记忆
2. 通过 `memory` 工具主动写入持久笔记
3. 在上下文窗口超限时自动压缩旧轮次

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    MemoryProvider ABC                     │
│  prefetch(query) → str       sync_turn(user, asst)       │
│  get_tool_schemas() → []     handle_tool_call(name, args)│
│  system_prompt_block() → str initialize(session_id)      │
│  on_turn_start()  on_session_end()  on_pre_compress()    │
└──────────┬──────────────────────────────┬────────────────┘
           │ implements                   │ implements
   ┌───────▼──────────┐         ┌─────────▼──────────┐
   │  BuiltinProvider  │         │  (future providers) │
   │  - MongoDB facts  │         │  - Mem0 / Honcho   │
   │  - agent_notes    │         └────────────────────┘
   │  - agent_profile  │
   └───────┬──────────┘
           │ managed by
   ┌───────▼──────────┐
   │  MemoryManager    │   ← 单例，编排所有 provider
   │  prefetch_all()   │   ← 每轮 LLM 前召回
   │  sync_all()       │   ← 每轮 LLM 后同步
   │  handle_tool_call │   ← 路由到对应 provider
   └───────┬──────────┘
           │ consumed by
   ┌───────▼──────────────────┐
   │  run_lead_agent()         │
   │  - system_prompt volatile │
   │  - per-turn context inj   │
   │  - memory tool reg        │
   └──────────────────────────┘
```

### 关键约定

- **MemoryProvider** — 抽象接口，内置实现用 MongoDB
- **MemoryManager** — 编排器，管理所有 provider
- **会话冻结快照** — 记忆数据在 session 开始时固定到 system prompt volatile tier，不中途刷新（保持 prefix cache）
- **每轮召回** — `prefetch_all()` 在每次 LLM 调用前执行，结果注入 `<memory-context>` 标签
- **`manage_memory` 工具** — `return_direct=True`，LLM 通过工具主动写入持久笔记

## Component Design

### MemoryProvider ABC

```python
class MemoryProvider(ABC):
    @property
    def name(self) -> str: ...

    def initialize(self, session_id: str) -> None: ...
    def shutdown(self) -> None: ...

    # 每轮生命周期
    def on_turn_start(self, turn_number: int, message: str) -> None: ...
    def prefetch(self, query: str) -> str: ...
    def sync_turn(self, user: str, assistant: str) -> None: ...

    # 记忆工具
    def get_tool_schemas(self) -> list[dict]: ...
    def handle_tool_call(self, name: str, args: dict) -> str: ...

    # 系统提示
    def system_prompt_block(self) -> str: ...

    # 会话边界
    def on_session_end(self) -> None: ...
    def on_pre_compress(self, messages: list) -> str: ...
```

### BuiltinProvider

**存储：** MongoDB，三张 collection：

| Collection | 用途 | 文档结构 |
|-----------|------|---------|
| `agent_memory` | LLM 摘要的持久事实 | `{session_id, facts[], workContext, topOfMind, updated_at}` |
| `agent_notes` | LLM 主动写入的笔记 | `{session_id, entries[{id, content, category, created_at}]}` |
| `agent_profile` | 用户画像 | `{user_id, profile: str, updated_at}` |

**召回策略：**
- `prefetch(query)`：取当前 session 的 `agent_notes` + 用户画像 + 最近 `agent_memory` 事实
- 结果用 `<memory-context>` 标签包裹
- 召回结果不超过 2000 tokens（可配置）

**`manage_memory` 工具：**

```python
@tool("manage_memory", return_direct=True)
def manage_memory(
    action: Annotated[str, "add | replace | remove"],
    target: Annotated[str, "notes | profile"],
    content: Annotated[str, "内容文本"],
    old_text: Annotated[str | None, "replace/remove 匹配文本"] = None,
) -> str:
    """管理持久记忆：记录笔记、更新用户画像。"""
```

### MemoryManager

```python
class MemoryManager:
    def __init__(self):
        self._providers: dict[str, MemoryProvider] = {}
        self._builtin: BuiltinProvider | None = None

    def add_provider(self, provider: MemoryProvider) -> None: ...
    def initialize_all(self, session_id: str) -> None: ...
    def shutdown_all(self) -> None: ...

    # 编排方法
    def prefetch_all(self, query: str) -> str: ...
    def sync_all(self, user: str, assistant: str) -> None: ...
    def on_turn_start(self, turn_number: int, message: str) -> None: ...

    # 工具路由
    def get_all_tool_schemas(self) -> list[dict]: ...
    def handle_tool_call(self, name: str, args: dict) -> str: ...

    # 系统提示
    def build_system_prompt_block(self) -> str: ...

    # 会话边界
    def on_session_end(self) -> None: ...
    def on_pre_compress(self, messages: list) -> str: ...
```

### Context Compression 集成

复用现有 `context_compressor.py`（保护 `<memory-context>` 标签），新增：

- `MemoryManager.on_pre_compress()` — 压缩前向所有 provider 获取 insights
- 压缩后 `MemoryManager.on_session_end()` + 重新 `initialize_all()`
- 压缩阈值：LLM context window 的 75%（与 hermes 一致）

### 与 run_lead_agent 集成

**System prompt 构建（volatile tier）：**

```
[STABLE TIER]
- 角色设定
- 工具定义
- 行为规则

[VOLATILE TIER]  ← 每轮可能变化
- <memory-context>
  {MemoryManager.prefetch_all(question)}
  </memory-context>
- 本轮特殊指令
```

**每轮流程：**

```
1. on_turn_start(turn_number, question)
2. prefetch_all(question) → context block
3. system_prompt = build_system_prompt(volatile=context block)
4. agent.astream(system_prompt + messages)
5. sync_all(user_question, assistant_response)
```

## Edges

### 写入安全
- `guardrails.filter_research_memory_text()` 在写入前过滤敏感内容
- `manage_memory` 工具结果不直接回 LLM（`return_direct=True`）

### 容量控制
- `agent_notes` 单 session 上限 50 条
- `agent_profile` 单条上限 2000 chars
- `prefetch` 结果上限 2000 tokens，超长截断

### 并发安全
- `MemoryManager` 用 `asyncio.Lock` 保护 provider 列表
- `BuiltinProvider` MongoDB 操作用 `replace_one` upsert，无需悲观锁

### 向后兼容
- 旧 `agent_memory` collection 数据继续使用（`BuiltinProvider` 读取）
- `agent_memory_queue_enabled` 设置保留但默认跟随新路径
- `HarnessConfig.memory_enabled` 废弃，迁移到 `MemoryManager`

## 删除/废弃的代码

- `backend/app/reasoning/harness/memory.py` → 移除（含 MemoryManager/MemoryUpdater/MemoryUpdateQueue）
- `backend/app/reasoning/langchain_agent/middlewares/memory_middleware.py` → 移除（HarnessMemoryUpdater/classify_research_memory）
- `backend/app/reasoning/langchain_agent/middlewares/memory_queue.py` → 移除（MemoryQueueLite）
- `backend/app/reasoning/langchain_agent/integrations.py` → 移除 HarnessConfig.memory_enabled / HarnessManager._init_memory / update_memory / flush_memory
- `backend/app/reasoning/langchain_agent/prompts/lead_system_prompt.py` → 简化 get_memory_context_async，删除断裂的 import

## 测试计划

1. **MemoryProvider ABC 接口测试** — mock provider
2. **BuiltinProvider 存储测试** — MongoDB CRUD + 召回
3. **MemoryManager 编排测试** — provider 注册、prefetch_all、sync_all
4. **manage_memory 工具测试** — add/replace/remove
5. **集成测试** — run_lead_agent 中 memory 正确注入 system prompt
6. **压缩集成测试** — context_compressor 不破坏 memory-context 标签
