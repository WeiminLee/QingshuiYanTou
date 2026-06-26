# Skill 系统设计

**日期**: 2026-06-26
**参考**: HermesAgent skill 系统
**状态**: 设计完成，待审核

---

## 1. 概述

### 1.1 背景

清水研投当前系统将 6 个分析场景（个股深度、行业扫描、事件驱动、产业链传导、行业状态、预期差挖掘）的全部指令硬编码在 system prompt 的 `<tool_strategy>` 和 `<graph_reasoning>` 等标签中。这导致：
- system prompt 持续膨胀（当前 ~400 行），token 消耗大
- 添加新分析场景需要修改 system prompt 模板
- 场景指令无法被 agent 按需加载，始终占用 context window

### 1.2 目标

参考 HermesAgent 的 skill 系统，将分析场景指令从 system prompt 中抽离为独立的 SKILL.md 文件，实现：
- **渐进式加载**：system prompt 只注入 skill 索引（name + description），完整指令由 agent 按需调用 `skill_view` 加载
- **Agent 自我进化**：agent 可以从成功经验中创建新 skill，修正现有 skill 的错误
- **内置 + 外部双目录**：项目内置默认 skill（git 管理，只读），agent 创建的用户 skill 写到外部目录

### 1.3 非目标

- 多 profile 隔离（单用户/单项目）
- 平台过滤（全部在 Linux 服务端运行）
- Plugin 命名空间
- 条件激活（`requires_toolsets` / `fallback_for_toolsets`）

---

## 2. 分阶段计划

### P0 — 最小可行版本（本文档详述）

1. 定义 `skills/` 目录结构 + `SKILL.md` 格式
2. 实现 skill 发现模块（扫描内置 + 外部目录，解析 frontmatter）
3. 实现 `skills_list` 和 `skill_view` 两个 LangChain tool
4. 改造 system prompt，注入 skill 索引替代硬编码场景指令
5. 编写 6 个内置 SKILL.md

### P1 — Agent 自我进化 + 智能推荐

6. 实现 `skill_manage` 工具（create / patch / edit / delete）
7. 实现 skill 覆盖优先级（外部 > 内置）
8. 实现关联 skill 推荐（`related_skills` 字段）
9. 实现使用统计（`.usage.json`）

---

## 3. P0 详细设计

### 3.1 目录结构

```
backend/app/reasoning/
├── skills/                              # 内置 skills (git 管理, 只读)
│   ├── stock-deep-dive/
│   │   └── SKILL.md
│   ├── industry-scan/
│   │   └── SKILL.md
│   ├── event-driven/
│   │   └── SKILL.md
│   ├── supply-chain/
│   │   └── SKILL.md
│   ├── industry-state/
│   │   └── SKILL.md
│   └── divergence-mining/
│       └── SKILL.md
├── langchain_agent/
│   ├── skills/                          # skill 核心模块 (新增)
│   │   ├── __init__.py
│   │   ├── discovery.py                 # 扫描、解析、过滤
│   │   ├── models.py                    # Skill 数据类
│   │   └── tools.py                     # skills_list + skill_view 工具
│   └── ...

~/.qingshui/skills/                      # 外部目录 (agent 创建的 skill)
    └── ...
```

### 3.2 SKILL.md 格式

每个 skill 是一个目录，包含一个 `SKILL.md` 文件，格式为 YAML frontmatter + Markdown 正文：

```markdown
---
name: stock-deep-dive
description: 个股深度分析，从基本面、技术面、产业链、事件四个维度全面评估
version: 1.0.0
metadata:
  tags: [个股, 基本面, 技术面, 估值]
  category: finance
  related_skills: [event-driven, supply-chain]
---

# 个股深度分析

## 触发条件
- 用户明确询问某只股票的分析
- 用户要求评估某公司的投资价值
- ...

## 分析流程
1. resolve + expand 获取公司画像
2. get_stock_profile 补充基本信息
...

## 关键工具
- resolve, expand, get_stock_profile, get_kline, get_research_report, ...

## 陷阱
- 不要仅凭单一指标下结论
- ...
```

**字段约束**：
- `name`: 必需，最长 64 字符，小写字母+数字+连字符
- `description`: 必需，最长 1024 字符
- `version`: 可选
- `metadata.tags`: 可选，用于分类检索
- `metadata.category`: 可选
- `metadata.related_skills`: 可选，关联 skill 列表

### 3.3 核心模块

#### 3.3.1 models.py — 数据类

```python
@dataclass
class Skill:
    name: str
    description: str
    path: Path           # SKILL.md 文件路径
    content: str         # 完整 Markdown 正文（不含 frontmatter，懒加载）
    frontmatter: dict    # 解析后的 YAML frontmatter
    is_builtin: bool     # True = 内置只读, False = 外部可写
    _content: str | None = None  # 懒加载：首次访问时从文件读取

@dataclass
class SkillIndex:
    """注入 system prompt 的轻量索引"""
    name: str
    description: str
    related_skills: list[str]
```

#### 3.3.2 discovery.py — 发现模块

```python
def scan_skills() -> list[Skill]:
    """扫描内置目录 + 外部目录，返回所有 Skill 对象。
    外部同名 skill 覆盖内置（外部优先）。
    """

def get_skills_index() -> list[SkillIndex]:
    """返回轻量索引列表，用于注入 system prompt。
    只包含 name + description + related_skills。
    """

def load_skill(name: str) -> Skill | None:
    """按名称加载完整 skill 内容（含 body）。
    外部优先，其次内置。
    """
```

扫描逻辑：
1. 遍历内置目录 `skills/`，解析每个 `SKILL.md` 的 frontmatter
2. 遍历外部目录 `~/.qingshui/skills/`，解析每个 `SKILL.md`
3. 外部同名 skill 覆盖内置（存入结果 dict 时覆盖）
4. 返回 `{name: Skill}` 字典

缓存策略：启动时扫描一次，缓存索引。`skill_view` 调用时按需读取文件内容。

#### 3.3.3 tools.py — Agent 工具

```python
# skills_list 工具
# 描述: 列出所有可用 skill（name + description）
# 返回: JSON，包含 skills 数组和 categories 数组

# skill_view 工具
# 描述: 加载指定 skill 的完整内容
# 参数: name (必需)
# 返回: JSON，包含 name, description, content, related_skills
```

注册到 `get_available_tools()` 的内置工具列表中，与 `ask_clarification` 同级。

### 3.4 System Prompt 改造

**当前结构**：
```xml
<tool_strategy>    <!-- 6 个场景的工具组合 ~60 行 -->
<graph_reasoning>  <!-- 图谱推理规则 ~30 行 -->
{skills_section}   <!-- 已存在但为空 -->
```

**改造后**：
```xml
<tool_strategy>    <!-- 精简为通用并发规则 + 失败处理 ~15 行 -->
<graph_reasoning>  <!-- 精简为通用导航原则 ~10 行 -->
<skills>
**可用 Skills**（如任务复杂，优先加载对应 Skill）：
- stock-deep-dive: 个股深度分析，从基本面、技术面、产业链、事件四个维度全面评估
- industry-scan: 行业/板块扫描，识别板块热度和轮动机会
- event-driven: 事件驱动分析，评估公告/新闻对股价的影响
- supply-chain: 产业链传导分析，追踪上下游影响
- industry-state: 行业状态评估，分析竞争格局和景气度
- divergence-mining: 预期差挖掘，发现 Fact vs Estimate 分歧点
</skills>
```

**具体变更**：
- `lead_system_prompt.py` 中 `get_skills_prompt_section()` 从 discovery 获取索引
- `<tool_strategy>` 中的场景 A-F 移除，保留通用并发规则和失败处理
- `<graph_reasoning>` 中的详细场景移除，保留通用导航原则

### 3.5 集成点

| 集成点 | 文件 | 变更 |
|--------|------|------|
| 工具注册 | `tools/tools.py` | `BUILTIN_TOOLS` 添加 `skills_list` + `skill_view` |
| System prompt | `prompts/lead_system_prompt.py` | 改造 `get_skills_prompt_section()`，精简场景标签 |
| Prompt 构建 | `client.py` | `run_lead_agent()` 中调用 `get_skills_index()` 传入 `apply_prompt_template()` |
| Skill 发现 | 新增 `skills/discovery.py` | 扫描内置 + 外部目录 |

### 3.6 6 个内置 Skill 内容规划

| Skill | 来源 | 内容 |
|-------|------|------|
| `stock-deep-dive` | 从 `<tool_strategy>` 场景 A 提取 | 个股分析流程、工具组合、输出规范 |
| `industry-scan` | 从 `<tool_strategy>` 场景 B 提取 | 板块扫描流程、热度判断、轮动识别 |
| `event-driven` | 从 `<tool_strategy>` 场景 C 提取 | 公告/新闻分析、利好利空判断、影响评估 |
| `supply-chain` | 从 `<tool_strategy>` 场景 D 提取 | 产业链上下游追踪、传导逻辑、路径分析 |
| `industry-state` | 从 `<tool_strategy>` 场景 E 提取 | 竞争格局、景气度评估、行业生命周期 |
| `divergence-mining` | 从 `<tool_strategy>` 场景 F 提取 | Fact vs Estimate 对比、预期差发现、证据追溯 |

每个 SKILL.md 包含：触发条件、分析流程（步骤化）、关键工具列表、常见陷阱、输出格式要求。

---

## 4. P1 详细设计

### 4.1 目录结构新增

```
backend/app/reasoning/langchain_agent/skills/
├── ...
├── tools.py              # P1: 新增 skill_manage 工具
└── usage.py              # P1: 使用统计

~/.qingshui/skills/
├── .usage.json           # 使用统计
└── my-custom-skill/      # agent 创建的 skill
    └── SKILL.md
```

### 4.2 skill_manage 工具

参照 HermesAgent 的 `skill_manage`，适配为 LangChain tool：

| Action | 参数 | 用途 |
|--------|------|------|
| `create` | `name`, `content`, `category?` | 创建新 skill 到外部目录 |
| `patch` | `name`, `old_string`, `new_string` | 精确替换（内置 skill 创建覆盖版到外部） |
| `edit` | `name`, `content` | 完整重写 SKILL.md |
| `delete` | `name` | 删除外部目录中的 skill |

**约束**：
- 只能写入外部目录 `~/.qingshui/skills/`
- 内置 skill 不可直接修改——`patch`/`edit` 内置 skill 时，将修改后的完整内容写入外部目录作为覆盖版本
- 内置 skill 不可 `delete`
- 创建/删除前需用户确认（通过 `ask_user_question` 提示）

**输入验证**：
- `name` 格式：`[a-z0-9][a-z0-9._-]*`，最长 64 字符
- `content` 必须包含合法的 YAML frontmatter（`name` + `description` 字段）
- 文件大小限制：100KB（~36K tokens）

### 4.3 Skill 覆盖优先级

同名 skill 查找顺序：
```
1. ~/.qingshui/skills/<name>/SKILL.md    (外部定制, 最高优先级)
2. backend/app/reasoning/skills/<name>/SKILL.md  (内置默认)
```

实现方式：`discovery.scan_skills()` 先扫描内置，再扫描外部，同名时后者覆盖前者。

### 4.4 关联 Skill 推荐

在 system prompt 的 skill 索引中展示关联关系：

```xml
<skills>
**可用 Skills**（如任务复杂，优先加载对应 Skill）：
- stock-deep-dive: 个股深度分析 → 关联: event-driven, supply-chain
- event-driven: 事件驱动分析 → 关联: stock-deep-dive, divergence-mining
- supply-chain: 产业链传导分析 → 关联: industry-state, divergence-mining
- ...
</skills>
```

`skill_view` 返回内容中也包含 `related_skills` 字段，agent 可按需加载关联 skill。

### 4.5 使用统计

`~/.qingshui/skills/.usage.json`：

```json
{
  "stock-deep-dive": {
    "created_at": "2026-06-20T00:00:00",
    "use_count": 47,
    "last_used": "2026-06-26T10:30:00"
  },
  "my-custom-skill": {
    "created_at": "2026-06-25T14:00:00",
    "use_count": 3,
    "last_used": "2026-06-25T14:00:00"
  }
}
```

每次 `skill_view` 调用时更新 `use_count` 和 `last_used`（best-effort，失败不影响主流程）。

**用途**：
- `skills_list` 按 `use_count` 降序排列，高频 skill 靠前
- agent 可以通过 `skills_list` 看到使用频率，判断是否值得优化
- 未来可扩展 `success_rate` 字段（需要用户反馈机制，不在 P1 范围）

### 4.6 内置 skill 覆盖流程

当 agent 发现内置 skill 有问题时：

```
1. skill_view("stock-deep-dive") → 读取内置的完整内容
2. skill_manage(action="patch", name="stock-deep-dive",
                old_string="...", new_string="...")
   → discovery 检测到 name 是内置 skill，无法直接修改
   → 将修改后的完整内容写入 ~/.qingshui/skills/stock-deep-dive/SKILL.md
   → 下次 scan_skills() 时外部版本覆盖内置版本
3. 之后 agent 加载 skill_view("stock-deep-dive") → 返回外部覆盖版本
```

---

## 5. 与现有系统的共存

### 5.1 System Prompt 精简范围

| 标签 | 当前行数 | 改造后 | 说明 |
|------|---------|--------|------|
| `<tool_strategy>` | ~60 行 | ~15 行 | 场景 A-F 迁移到 6 个 skill，保留并发规则和失败处理 |
| `<graph_reasoning>` | ~30 行 | ~10 行 | 详细场景迁移到 skill，保留通用导航原则 |
| `<skills>` | 2 行（空） | ~10 行 | 注入 skill 索引 |
| 其他标签 | ~180 行 | ~180 行 | 不变 |

**总计精简 ~65 行**（从 ~270 行 → ~205 行），同时 skill 内容按需加载时 token 效率更高。

### 5.2 向后兼容

- 不传 skill 参数的请求：system prompt 中注入 skill 索引，agent 按需加载，行为不变
- 用户直接问"分析茅台"：agent 看到索引中 `stock-deep-dive` 匹配，加载后执行
- 用户问"最近有什么公告"：agent 加载 `event-driven`

---

## 6. 风险与缓解

| 风险 | 缓解 |
|------|------|
| `skill_view` 加载内容过大（如 DCF model 类 skill 可能很长） | SKILL.md 大小限制 100KB，超长内容拆分到 `references/` 目录按需加载 |
| Agent 忘记加载 skill 就直接分析 | System prompt 中强调"任务复杂时优先加载 skill" |
| 外部目录 skill 覆盖内置后行为异常 | 内置 skill 保留在 git 中不可修改，用户可删除外部覆盖版恢复默认 |
| `skill_manage` 创建低质量 skill | 需要用户确认才能创建/删除 |
| 并发场景下 `.usage.json` 写入冲突 | best-effort 更新，失败不影响主流程 |

---

## 7. 文件清单

### P0 新增文件

| 文件 | 说明 |
|------|------|
| `backend/app/reasoning/skills/stock-deep-dive/SKILL.md` | 个股深度分析 |
| `backend/app/reasoning/skills/industry-scan/SKILL.md` | 行业扫描 |
| `backend/app/reasoning/skills/event-driven/SKILL.md` | 事件驱动 |
| `backend/app/reasoning/skills/supply-chain/SKILL.md` | 产业链传导 |
| `backend/app/reasoning/skills/industry-state/SKILL.md` | 行业状态 |
| `backend/app/reasoning/skills/divergence-mining/SKILL.md` | 预期差挖掘 |
| `backend/app/reasoning/langchain_agent/skills/__init__.py` | 模块初始化 |
| `backend/app/reasoning/langchain_agent/skills/models.py` | Skill/SkillIndex 数据类 |
| `backend/app/reasoning/langchain_agent/skills/discovery.py` | 扫描 + 解析 + 缓存 |
| `backend/app/reasoning/langchain_agent/skills/tools.py` | skills_list + skill_view 工具 |

### P0 修改文件

| 文件 | 变更 |
|------|------|
| `backend/app/reasoning/tools/tools.py` | `BUILTIN_TOOLS` 注册 skills_list + skill_view |
| `backend/app/reasoning/langchain_agent/prompts/lead_system_prompt.py` | 改造 `get_skills_prompt_section()`，精简 `<tool_strategy>` 和 `<graph_reasoning>` |
| `backend/app/reasoning/langchain_agent/client.py` | `run_lead_agent()` 中调用 discovery 获取索引 |

### P1 新增文件

| 文件 | 说明 |
|------|------|
| `backend/app/reasoning/langchain_agent/skills/usage.py` | 使用统计读写 |

### P1 修改文件

| 文件 | 变更 |
|------|------|
| `backend/app/reasoning/langchain_agent/skills/tools.py` | 新增 `skill_manage` 工具 |
| `backend/app/reasoning/langchain_agent/skills/discovery.py` | 支持外部覆盖优先级 |
| `backend/app/reasoning/tools/tools.py` | 注册 `skill_manage` 工具 |