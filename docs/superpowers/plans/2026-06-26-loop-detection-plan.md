# Loop Detection 优化实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 迁移 DeerFlow 完整的 Loop Detection 实现到清水投研，增强循环检测能力

**Architecture:** 
- 创建 `LoopDetectionConfig` Pydantic 配置模型
- 完全替换现有的 `LoopDetectionMiddleware`，采用 DeerFlow 的双层检测架构
- 保持向后兼容，原有构造函数参数仍可用

**Tech Stack:** Python, Pydantic, LangChain AgentMiddleware, threading

---

## 文件结构

```
app/reasoning/
├── config/
│   └── loop_detection_config.py     # 新建: Pydantic 配置模型
├── langchain_agent/
│   └── middlewares/
│       ├── __init__.py             # 修改: 导出新配置
│       ├── loop_detection.py       # 修改: 替换为 DeerFlow 实现
│       └── loop_detection_backup.py # 新建: 备份原实现
tests/
└── reasoning/
    └── test_loop_detection.py      # 新建/修改: 完整测试
```

---

## Task 1: 备份现有实现

**Files:**
- Modify: `app/reasoning/langchain_agent/middlewares/loop_detection.py` → `loop_detection_backup.py`

- [ ] **Step 1: 备份现有实现**

```bash
cp /home/lwm/code/QingshuiYanTou/backend/app/reasoning/langchain_agent/middlewares/loop_detection.py \
   /home/lwm/code/QingshuiYanTou/backend/app/reasoning/langchain_agent/middlewares/loop_detection_backup.py
```

- [ ] **Step 2: 提交备份**

```bash
git add app/reasoning/langchain_agent/middlewares/loop_detection_backup.py
git commit -m "backup: save original loop_detection.py before migration"
```

---

## Task 2: 创建 LoopDetectionConfig 配置模型

**Files:**
- Create: `app/reasoning/config/loop_detection_config.py`

- [ ] **Step 1: 创建配置模型**

```python
"""Loop Detection Configuration — DeerFlow 风格"""

from pydantic import BaseModel, Field, model_validator


class ToolFreqOverride(BaseModel):
    """Per-tool frequency threshold override."""

    warn: int = Field(ge=1)
    hard_limit: int = Field(ge=1)

    @model_validator(mode="after")
    def _validate(self) -> "ToolFreqOverride":
        if self.hard_limit < self.warn:
            raise ValueError("hard_limit must be >= warn")
        return self


class LoopDetectionConfig(BaseModel):
    """Configuration for repetitive tool-call loop detection."""

    enabled: bool = Field(
        default=True,
        description="Whether to enable repetitive tool-call loop detection",
    )
    warn_threshold: int = Field(
        default=3,
        ge=1,
        description="Number of identical tool-call sets before injecting a warning",
    )
    hard_limit: int = Field(
        default=5,
        ge=1,
        description="Number of identical tool-call sets before forcing a stop",
    )
    window_size: int = Field(
        default=20,
        ge=1,
        description="Number of recent tool-call sets to track per thread",
    )
    max_tracked_threads: int = Field(
        default=100,
        ge=1,
        description="Maximum number of thread histories to keep in memory",
    )
    tool_freq_warn: int = Field(
        default=30,
        ge=1,
        description="Number of calls to the same tool type before injecting a frequency warning",
    )
    tool_freq_hard_limit: int = Field(
        default=50,
        ge=1,
        description="Number of calls to the same tool type before forcing a stop",
    )
    tool_freq_overrides: dict[str, ToolFreqOverride] = Field(
        default_factory=dict,
        description="Per-tool overrides for tool_freq thresholds",
    )

    @model_validator(mode="after")
    def validate_thresholds(self) -> "LoopDetectionConfig":
        if self.hard_limit < self.warn_threshold:
            raise ValueError("hard_limit must be >= warn_threshold")
        if self.tool_freq_hard_limit < self.tool_freq_warn:
            raise ValueError("tool_freq_hard_limit must be >= tool_freq_warn")
        return self
```

- [ ] **Step 2: 创建目录并写入文件**

```bash
mkdir -p /home/lwm/code/QingshuiYanTou/backend/app/reasoning/config
```

- [ ] **Step 3: 验证配置模型**

```bash
cd /home/lwm/code/QingshuiYanTou/backend && python -c "
from app.reasoning.config.loop_detection_config import LoopDetectionConfig, ToolFreqOverride
config = LoopDetectionConfig()
print(f'warn_threshold: {config.warn_threshold}')
print(f'hard_limit: {config.hard_limit}')
print(f'window_size: {config.window_size}')
print(f'tool_freq_warn: {config.tool_freq_warn}')
# 测试验证器
try:
    bad_config = LoopDetectionConfig(hard_limit=1, warn_threshold=5)
except ValueError as e:
    print(f'Validator works: {e}')
print('Config validation passed!')
"
```

- [ ] **Step 4: 提交**

```bash
git add app/reasoning/config/loop_detection_config.py
git commit -m "feat: add LoopDetectionConfig Pydantic model

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: 实现完整的 LoopDetectionMiddleware

**Files:**
- Create: `app/reasoning/langchain_agent/middlewares/loop_detection.py`

- [ ] **Step 1: 写入完整的 LoopDetectionMiddleware 实现**

完整代码太长，请参考 DeerFlow 的 `loop_detection_middleware.py`，核心实现要点：

```python
# 关键导入
from collections import OrderedDict, defaultdict
from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest, ModelResponse
from langchain_core.messages import HumanMessage
from langgraph.runtime import Runtime

# 核心功能
class LoopDetectionMiddleware(AgentMiddleware[AgentState]):
    # 1. 双层检测: hash-based + frequency-based
    # 2. LRU eviction: max_tracked_threads
    # 3. 延迟 warning 注入: wrap_model_call
    # 4. Per-tool 阈值覆盖: tool_freq_overrides
    
    # 钩子: before_agent, after_model, after_agent, wrap_model_call
```

**完整实现请直接复制** `/home/lwm/code/deer-flow/backend/packages/harness/deerflow/agents/middlewares/loop_detection_middleware.py` 并做以下适配：

1. 导入路径修改：
   - `from deerflow.config.loop_detection_config import LoopDetectionConfig` → `from app.reasoning.config.loop_detection_config import LoopDetectionConfig`

2. 类型导入可能需要调整（LangChain 版本兼容）

- [ ] **Step 2: 验证实现可导入**

```bash
cd /home/lwm/code/QingshuiYanTou/backend && python -c "
from app.reasoning.langchain_agent.middlewares.loop_detection import LoopDetectionMiddleware
mw = LoopDetectionMiddleware()
print(f'mw.warn_threshold: {mw.warn_threshold}')
print(f'mw.hard_limit: {mw.hard_limit}')
print(f'mw.window_size: {mw.window_size}')
print(f'mw.tool_freq_warn: {mw.tool_freq_warn}')
print('Import successful!')
"
```

- [ ] **Step 3: 提交**

```bash
git add app/reasoning/langchain_agent/middlewares/loop_detection.py
git commit -m "feat: migrate DeerFlow LoopDetectionMiddleware

- Hash-based + frequency-based dual-layer detection
- LRU eviction for thread tracking
- Deferred warning injection via wrap_model_call
- Per-tool frequency threshold overrides

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: 更新 Middleware 导出

**Files:**
- Modify: `app/reasoning/langchain_agent/middlewares/__init__.py`

- [ ] **Step 1: 更新 __init__.py**

```python
"""LangChain Agent Middlewares"""

from app.reasoning.langchain_agent.middlewares.clarification import ClarificationMiddleware
from app.reasoning.langchain_agent.middlewares.context_compressor import ContextCompressorMiddleware
from app.reasoning.langchain_agent.middlewares.loop_detection import LoopDetectionMiddleware
from app.reasoning.langchain_agent.middlewares.subagent_limit import SubagentLimitMiddleware
from app.reasoning.langchain_agent.middlewares.title import TitleMiddleware
from app.reasoning.langchain_agent.middlewares.todo_list import TodoListMiddleware

__all__ = [
    "ClarificationMiddleware",
    "ContextCompressorMiddleware",
    "LoopDetectionMiddleware",  # 新增
    "SubagentLimitMiddleware",
    "TitleMiddleware",
    "TodoListMiddleware",
]
```

- [ ] **Step 2: 验证导出**

```bash
cd /home/lwm/code/QingshuiYanTou/backend && python -c "
from app.reasoning.langchain_agent.middlewares import LoopDetectionMiddleware
print('Export verified!')
"
```

- [ ] **Step 3: 提交**

```bash
git add app/reasoning/langchain_agent/middlewares/__init__.py
git commit -m "feat: export LoopDetectionMiddleware from middlewares package

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: 创建/更新测试

**Files:**
- Create: `tests/reasoning/test_loop_detection.py`

- [ ] **Step 1: 编写测试**

```python
"""Tests for LoopDetectionMiddleware"""

import pytest
from unittest.mock import MagicMock

from app.reasoning.langchain_agent.middlewares.loop_detection import (
    LoopDetectionMiddleware,
    _hash_tool_calls,
    _normalize_tool_call_args,
    _stable_tool_key,
)
from app.reasoning.config.loop_detection_config import (
    LoopDetectionConfig,
    ToolFreqOverride,
)


class TestHashToolCalls:
    """Test hash generation for tool calls."""

    def test_same_calls_same_hash(self):
        """Identical tool calls produce same hash."""
        calls = [{"name": "get_kline", "args": {"code": "000001.SZ"}}]
        hash1 = _hash_tool_calls(calls)
        hash2 = _hash_tool_calls(calls)
        assert hash1 == hash2

    def test_different_calls_different_hash(self):
        """Different tool calls produce different hash."""
        calls1 = [{"name": "get_kline", "args": {"code": "000001.SZ"}}]
        calls2 = [{"name": "get_kline", "args": {"code": "000002.SZ"}}]
        hash1 = _hash_tool_calls(calls1)
        hash2 = _hash_tool_calls(calls2)
        assert hash1 != hash2

    def test_order_independent(self):
        """Order of tool calls doesn't affect hash."""
        calls1 = [
            {"name": "get_kline", "args": {"code": "000001.SZ"}},
            {"name": "get_concept_hot", "args": {}},
        ]
        calls2 = [
            {"name": "get_concept_hot", "args": {}},
            {"name": "get_kline", "args": {"code": "000001.SZ"}},
        ]
        assert _hash_tool_calls(calls1) == _hash_tool_calls(calls2)


class TestStableToolKey:
    """Test stable key generation for different tool types."""

    def test_read_file_bucketing(self):
        """read_file keys should bucket by 200-line ranges."""
        args1 = {"path": "/file.py", "start_line": 1, "end_line": 100}
        args2 = {"path": "/file.py", "start_line": 50, "end_line": 150}
        # Same bucket (1-200)
        key1 = _stable_tool_key("read_file", args1, None)
        key2 = _stable_tool_key("read_file", args2, None)
        assert key1 == key2, "Adjacent 200-line ranges should bucket together"

    def test_read_file_different_bucket(self):
        """read_file keys should differ for non-overlapping buckets."""
        args1 = {"path": "/file.py", "start_line": 1, "end_line": 100}
        args2 = {"path": "/file.py", "start_line": 201, "end_line": 300}
        key1 = _stable_tool_key("read_file", args1, None)
        key2 = _stable_tool_key("read_file", args2, None)
        assert key1 != key2


class TestLoopDetectionMiddleware:
    """Test LoopDetectionMiddleware behavior."""

    def test_default_initialization(self):
        """Default constructor works."""
        mw = LoopDetectionMiddleware()
        assert mw.warn_threshold == 3
        assert mw.hard_limit == 5
        assert mw.window_size == 20
        assert mw.tool_freq_warn == 30
        assert mw.tool_freq_hard_limit == 50

    def test_from_config(self):
        """from_config creates middleware from config."""
        config = LoopDetectionConfig(
            warn_threshold=5,
            hard_limit=10,
            tool_freq_overrides={"bash": ToolFreqOverride(warn=50, hard_limit=100)},
        )
        mw = LoopDetectionMiddleware.from_config(config)
        assert mw.warn_threshold == 5
        assert mw.hard_limit == 10
        assert mw._tool_freq_overrides == {"bash": (50, 100)}

    def test_reset(self):
        """reset() clears all tracking state."""
        mw = LoopDetectionMiddleware()
        mw._history["thread-1"] = ["hash1", "hash2"]
        mw._tool_freq["thread-1"] = {"get_kline": 5}
        mw.reset("thread-1")
        assert "thread-1" not in mw._history
        assert "thread-1" not in mw._tool_freq


class TestConfigValidation:
    """Test LoopDetectionConfig validation."""

    def test_valid_config(self):
        """Valid config passes validation."""
        config = LoopDetectionConfig()
        assert config.enabled is True

    def test_hard_limit_must_be_gte_warn(self):
        """hard_limit < warn_threshold raises."""
        with pytest.raises(ValueError, match="hard_limit must be >= warn_threshold"):
            LoopDetectionConfig(warn_threshold=5, hard_limit=3)

    def test_tool_freq_hard_limit_must_be_gte_warn(self):
        """tool_freq_hard_limit < tool_freq_warn raises."""
        with pytest.raises(ValueError, match="tool_freq_hard_limit must be >= tool_freq_warn"):
            LoopDetectionConfig(tool_freq_warn=50, tool_freq_hard_limit=30)

    def test_tool_freq_override_validation(self):
        """ToolFreqOverride validates hard_limit >= warn."""
        with pytest.raises(ValueError, match="hard_limit must be >= warn"):
            ToolFreqOverride(warn=10, hard_limit=5)
```

- [ ] **Step 2: 运行测试**

```bash
cd /home/lwm/code/QingshuiYanTou/backend && python -m pytest tests/reasoning/test_loop_detection.py -v
```

- [ ] **Step 3: 提交**

```bash
git add tests/reasoning/test_loop_detection.py
git commit -m "test: add LoopDetectionMiddleware tests

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: 集成验证

**Files:**
- Test: `app/reasoning/langchain_agent/client.py` (验证 lead_agent 仍能正常工作)

- [ ] **Step 1: 验证 lead_agent 可导入**

```bash
cd /home/lwm/code/QingshuiYanTou/backend && python -c "
from app.reasoning.langchain_agent.lead_agent import make_lead_agent
from app.reasoning.langchain_agent.middlewares import LoopDetectionMiddleware
print('Integration check: all imports successful!')
"
```

- [ ] **Step 2: 运行现有测试确保无回归**

```bash
cd /home/lwm/code/QingshuiYanTou/backend && python -m pytest tests/test_v2_architecture.py -v -k "loop"
```

- [ ] **Step 3: 提交**

```bash
git add -A
git commit -m "test: verify LoopDetection integration

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## 验证清单

- [ ] 备份完成
- [ ] LoopDetectionConfig 创建成功
- [ ] 完整 LoopDetectionMiddleware 实现
- [ ] Middleware 导出更新
- [ ] 测试通过
- [ ] 集成验证通过
- [ ] 无回归

---

## 执行选项

**Plan complete and saved to `docs/superpowers/plans/2026-06-26-loop-detection-plan.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
