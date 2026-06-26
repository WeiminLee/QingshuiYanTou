# Loop Detection 优化设计

**日期**: 2026-06-26  
**状态**: 设计中  
**优先级**: P0

---

## 1. 背景

当前清水投研的 `LoopDetectionMiddleware` 实现过于简化：
- 只有简单的 hash 计数
- 无 frequency-based 检测（同工具不同参数）
- 无 LRU eviction（内存泄漏风险）
- Warning 注入时机可能破坏 tool_calls pairing
- 无 per-tool 阈值覆盖

参考 DeerFlow 的 `loop_detection_middleware.py`，该实现经过充分测试，提供了完整的功能集。

---

## 2. 设计目标

迁移 DeerFlow 的完整 Loop Detection 实现，保留以下核心功能：

| 功能 | 描述 |
|------|------|
| Hash-based 检测 | 精确匹配相同 tool call 组合 |
| Frequency-based 检测 | 同一工具类型的调用频率（不同参数） |
| LRU Eviction | 限制追踪的线程数量，防止内存泄漏 |
| Per-tool 阈值覆盖 | 允许针对特定工具配置不同阈值 |
| Warning 延迟注入 | 避免破坏 OpenAI/Moonshot tool pairing |
| 多钩子支持 | before_agent, after_model, after_agent, wrap_model_call |

---

## 3. 架构设计

### 3.1 文件结构

```
app/reasoning/langchain_agent/middlewares/
├── loop_detection.py          # 保留旧文件作为备份 (loop_detection_backup.py)
└── loop_detection.py          # 新实现，替换旧版本
```

### 3.2 配置模型

新增 `app/reasoning/config/loop_detection_config.py`：

```python
@dataclass
class LoopDetectionConfig:
    warn_threshold: int = 3          # 注入警告前的重复次数
    hard_limit: int = 5             # 强制停止前的重复次数
    window_size: int = 20           # 滑动窗口大小
    max_tracked_threads: int = 100 # 最大追踪线程数（LRU eviction）
    tool_freq_warn: int = 30       # 同类工具频率警告阈值
    tool_freq_hard_limit: int = 50  # 同类工具频率硬限制
    tool_freq_overrides: dict[str, tuple[int, int]] | None = None
```

### 3.3 核心组件

| 组件 | 职责 |
|------|------|
| `_hash_tool_calls()` | 生成工具调用的稳定 hash |
| `_stable_tool_key()` | 为特定工具生成稳定 key（如 read_file 分桶） |
| `_track_and_check()` | 双层检测：hash-based + frequency-based |
| `_queue_pending_warning()` | 延迟 warning 到下一轮 |
| `_drain_pending_warnings()` | 取出待注入的 warnings |
| `_augment_request()` | 在 wrap_model_call 中注入 warning |

### 3.4 数据结构

```python
# 追踪历史 (OrderedDict 实现 LRU)
_history: OrderedDict[str, list[str]]  # thread_id -> [call_hash, ...]

# Hash 警告记录
_warned: dict[str, set[str]]  # thread_id -> {hash1, hash2, ...}

# 频率追踪
_tool_freq: dict[str, dict[str, int]]  # thread_id -> {tool_name: count}

# 频率警告记录
_tool_freq_warned: dict[str, set[str]]

# 延迟警告队列
_pending_warnings: dict[tuple[str, str], list[str]]  # (thread_id, run_id) -> [warnings]
```

---

## 4. 检测策略

### 4.1 Hash-based 检测

```python
# 相同 tool_calls 集合被视为一次循环
call_hash = _hash_tool_calls(tool_calls)

if count >= hard_limit:
    return HARD_STOP_MSG, True
if count >= warn_threshold:
    return WARNING_MSG, False
```

### 4.2 Frequency-based 检测

```python
# 同一工具类型（不同参数）被频繁调用
for tc in tool_calls:
    freq[tool_name] += 1
    if freq >= tool_freq_hard_limit:
        return TOOL_FREQ_HARD_STOP_MSG, True
```

### 4.3 特殊工具处理

| 工具 | 处理方式 |
|------|----------|
| `read_file` | 按 200 行分桶，避免大文件逐行读取被误判 |
| `write_file` / `str_replace` | 使用完整 args hash（内容敏感） |
| 其他工具 | 使用显著字段 (path, url, query, command) |

---

## 5. Warning 注入机制

### 5.1 问题

在 `after_model` 中直接修改 AIMessage 会导致：
- OpenAI/Moonshot: `"tool_call_ids did not have response messages"`
- Anthropic: mid-stream SystemMessage 限制

### 5.2 解决方案

```
ToolCall → ToolMessage → ToolMessage → ... → AIMessage(tool_calls)
                                                       ↓
                                              after_model (queue warning)
                                                       ↓
UserMessage ← AIMessage ← HumanMessage(warning) ← wrap_model_call (inject)
```

Warning 被延迟到 `wrap_model_call`，此时所有 ToolMessage 已就位。

---

## 6. LRU Eviction

```python
def _evict_if_needed(self):
    while len(self._history) > self.max_tracked_threads:
        evicted_id, _ = self._history.popitem(last=False)
        # 同时清理关联状态
        self._warned.pop(evicted_id, None)
        self._tool_freq.pop(evicted_id, None)
        self._tool_freq_warned.pop(evicted_id, None)
```

---

## 7. 消息模板

```python
_WARNING_MSG = "[LOOP DETECTED] You are repeating the same tool calls. Stop calling tools and produce your final answer now."

_TOOL_FREQ_WARNING_MSG = "[LOOP DETECTED] You have called {tool_name} {count} times without producing a final answer..."

_HARD_STOP_MSG = "[FORCED STOP] Repeated tool calls exceeded the safety limit. Producing final answer with results collected so far."

_TOOL_FREQ_HARD_STOP_MSG = "[FORCED STOP] Tool {tool_name} called {count} times — exceeded the per-tool safety limit."
```

---

## 8. 迁移步骤

1. **备份现有实现** → `loop_detection_backup.py`
2. **创建配置模型** → `app/reasoning/config/loop_detection_config.py`
3. **迁移 DeerFlow 实现** → `loop_detection.py`
4. **更新测试** → `test_loop_detection.py`
5. **验证功能** → 运行现有测试 + 手动测试

---

## 9. 兼容性

- 保持原有接口：`LoopDetectionMiddleware(max_repeats=3, window_size=10)`
- 默认参数兼容旧行为
- 新增参数可选

```python
# 旧用法（仍支持）
middleware = LoopDetectionMiddleware()

# 新用法（完整配置）
from app.reasoning.config.loop_detection_config import LoopDetectionConfig
config = LoopDetectionConfig(
    warn_threshold=3,
    hard_limit=5,
    tool_freq_overrides={"bash": (50, 100)}  # bash 允许更高频率
)
middleware = LoopDetectionMiddleware.from_config(config)
```
