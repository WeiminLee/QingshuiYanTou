# Skill 系统 P0+P1 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将分析场景指令从 system prompt 抽离为可渐进加载的 SKILL.md 文件，agent 按需调用 skill_view 加载，支持自我进化。

**Architecture:** 新增 `langchain_agent/skills/` 模块（models → discovery → tools），内置 6 个 SKILL.md 放在 `reasoning/skills/`。skill 索引注入 system prompt 替代硬编码场景，agent 通过 `skills_list`/`skill_view`/`skill_manage` 三个 LangChain tool 交互。

**Tech Stack:** Python 3.12+, dataclasses, PyYAML, LangChain BaseTool

---

## File Structure

```
backend/app/reasoning/
├── skills/                                    # [CREATE] 内置 skills 目录
│   ├── stock-deep-dive/SKILL.md
│   ├── industry-scan/SKILL.md
│   ├── event-driven/SKILL.md
│   ├── supply-chain/SKILL.md
│   ├── industry-state/SKILL.md
│   └── divergence-mining/SKILL.md
├── langchain_agent/
│   ├── skills/                                # [CREATE] skill 核心模块
│   │   ├── __init__.py
│   │   ├── models.py       # Skill / SkillIndex 数据类
│   │   ├── discovery.py    # 扫描 + 解析 + 缓存 + 覆盖优先级
│   │   ├── tools.py        # skills_list / skill_view / skill_manage
│   │   └── usage.py        # [P1] 使用统计 .usage.json
│   ├── prompts/
│   │   └── lead_system_prompt.py              # [MODIFY] 精简场景标签 + 接入 skill 索引
│   └── client.py                              # [MODIFY] 调用 discovery 获取索引
└── tools/
    └── tools.py                               # [MODIFY] 注册 3 个 skill 工具
```

**Responsibility boundaries:**
- `models.py` — 纯数据类，零依赖
- `discovery.py` — 文件 I/O + YAML 解析 + 缓存，不依赖 LangChain
- `tools.py` — LangChain BaseTool 封装，依赖 discovery + models
- `usage.py` — JSON 文件读写，独立模块，被 tools.py 调用

---

### Task 1: Skill 数据模型

**Files:**
- Create: `backend/app/reasoning/langchain_agent/skills/__init__.py`
- Create: `backend/app/reasoning/langchain_agent/skills/models.py`

- [ ] **Step 1: Write models.py**

```python
"""Skill 数据模型 — 纯数据类，零外部依赖。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Skill:
    """单个 Skill 的完整表示。

    content 采用懒加载：创建实例时不读取文件正文，
    首次访问 .content 属性时才从磁盘读取。
    """

    name: str
    description: str
    path: Path  # SKILL.md 文件路径
    frontmatter: dict[str, Any] = field(default_factory=dict)
    is_builtin: bool = True
    _content: str | None = field(default=None, repr=False, init=False)

    @property
    def content(self) -> str:
        """懒加载：首次访问时从文件读取正文（不含 frontmatter）。"""
        if self._content is None:
            raw = self.path.read_text(encoding="utf-8")
            _, body = _split_frontmatter(raw)
            self._content = body
        return self._content

    @property
    def tags(self) -> list[str]:
        metadata = self.frontmatter.get("metadata", {})
        if not isinstance(metadata, dict):
            return []
        tags = metadata.get("tags", [])
        if isinstance(tags, list):
            return [str(t) for t in tags]
        return []

    @property
    def related_skills(self) -> list[str]:
        metadata = self.frontmatter.get("metadata", {})
        if not isinstance(metadata, dict):
            return []
        related = metadata.get("related_skills", [])
        if isinstance(related, list):
            return [str(r) for r in related]
        return []

    @property
    def category(self) -> str | None:
        metadata = self.frontmatter.get("metadata", {})
        if not isinstance(metadata, dict):
            return None
        return metadata.get("category")


@dataclass
class SkillIndex:
    """注入 system prompt 的轻量索引 — 只含 name + description + 关联。"""

    name: str
    description: str
    related_skills: list[str] = field(default_factory=list)


def _split_frontmatter(raw: str) -> tuple[dict[str, Any], str]:
    """解析 YAML frontmatter，返回 (frontmatter_dict, body)。"""
    import re

    import yaml

    frontmatter: dict[str, Any] = {}
    body = raw

    if not raw.startswith("---"):
        return frontmatter, body

    end_match = re.search(r"\n---\s*\n", raw[3:])
    if not end_match:
        return frontmatter, body

    yaml_content = raw[3 : end_match.start() + 3]
    body = raw[end_match.end() + 3 :]

    try:
        parsed = yaml.safe_load(yaml_content)
        if isinstance(parsed, dict):
            frontmatter = parsed
    except Exception:
        pass

    return frontmatter, body
```

- [ ] **Step 2: Write __init__.py**

```python
from app.reasoning.langchain_agent.skills.models import Skill, SkillIndex

__all__ = ["Skill", "SkillIndex"]
```

- [ ] **Step 3: Verify models import**

Run: `cd backend && python -c "from app.reasoning.langchain_agent.skills.models import Skill, SkillIndex; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add backend/app/reasoning/langchain_agent/skills/__init__.py backend/app/reasoning/langchain_agent/skills/models.py
git commit -m "feat(skills): add Skill/SkillIndex data models with lazy content loading"
```

---

### Task 2: Skill 发现模块

**Files:**
- Create: `backend/app/reasoning/langchain_agent/skills/discovery.py`

- [ ] **Step 1: Write discovery.py**

```python
"""Skill 发现模块 — 扫描内置 + 外部目录，解析 frontmatter，缓存索引。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from app.reasoning.langchain_agent.skills.models import Skill, SkillIndex, _split_frontmatter

logger = logging.getLogger(__name__)

# 内置 skills 目录（相对于 reasoning 包）
_BUILTIN_SKILLS_DIR = Path(__file__).resolve().parent.parent.parent / "skills"

# 外部 skills 目录（agent 创建）
_EXTERNAL_SKILLS_DIR = Path.home() / ".qingshui" / "skills"

# 排除的目录名
_EXCLUDED_DIRS = frozenset(
    {".git", "__pycache__", "node_modules", ".venv", "venv"}
)

# 内存缓存
_cache: dict[str, Skill] | None = None


def _get_skills_dirs() -> list[tuple[Path, bool]]:
    """返回 [(目录路径, is_builtin), ...] 列表。"""
    dirs: list[tuple[Path, bool]] = []
    if _BUILTIN_SKILLS_DIR.is_dir():
        dirs.append((_BUILTIN_SKILLS_DIR, True))
    if _EXTERNAL_SKILLS_DIR.is_dir():
        dirs.append((_EXTERNAL_SKILLS_DIR, False))
    return dirs


def _scan_dir(root: Path, is_builtin: bool) -> dict[str, Skill]:
    """扫描单个目录，返回 {name: Skill} 字典。"""
    skills: dict[str, Skill] = {}
    if not root.is_dir():
        return skills

    for skill_md in root.rglob("SKILL.md"):
        # 跳过排除目录
        parts = set(skill_md.parts)
        if parts & _EXCLUDED_DIRS:
            continue

        try:
            raw = skill_md.read_text(encoding="utf-8")
            frontmatter, _body = _split_frontmatter(raw)
        except Exception as e:
            logger.warning(f"Failed to read SKILL.md at {skill_md}: {e}")
            continue

        name = frontmatter.get("name", skill_md.parent.name)
        description = frontmatter.get("description", "")

        if not name or not description:
            logger.warning(f"Skipping skill at {skill_md}: missing name or description")
            continue

        skills[name] = Skill(
            name=name,
            description=description,
            path=skill_md,
            frontmatter=frontmatter,
            is_builtin=is_builtin,
        )

    return skills


def scan_skills(force: bool = False) -> dict[str, Skill]:
    """扫描所有 skill 目录，返回 {name: Skill} 字典。

    外部同名 skill 覆盖内置（外部优先）。
    结果缓存在内存中，除非 force=True。
    """
    global _cache

    if _cache is not None and not force:
        return _cache

    all_skills: dict[str, Skill] = {}

    for skills_dir, is_builtin in _get_skills_dirs():
        dir_skills = _scan_dir(skills_dir, is_builtin)
        # 外部覆盖内置（后扫描的覆盖先扫描的）
        all_skills.update(dir_skills)

    _cache = all_skills
    logger.info(f"Scanned {len(all_skills)} skills (builtin={sum(1 for s in all_skills.values() if s.is_builtin)})")
    return _cache


def get_skills_index() -> list[SkillIndex]:
    """返回轻量索引列表，用于注入 system prompt。"""
    skills = scan_skills()
    return [
        SkillIndex(
            name=s.name,
            description=s.description,
            related_skills=s.related_skills,
        )
        for s in skills.values()
    ]


def load_skill(name: str) -> Skill | None:
    """按名称加载完整 skill（含正文内容）。

    外部优先，其次内置。
    """
    skills = scan_skills()
    skill = skills.get(name)
    if skill is None:
        return None
    # 触发懒加载
    _ = skill.content
    return skill


def invalidate_cache() -> None:
    """清除缓存（skill_manage 修改后调用）。"""
    global _cache
    _cache = None
```

- [ ] **Step 2: Verify discovery with a test scan**

Run: `cd backend && python -c "
from app.reasoning.langchain_agent.skills.discovery import scan_skills, get_skills_index
skills = scan_skills()
print(f'Found {len(skills)} skills')
# 内置目录还不存在，应该返回 0
assert len(skills) == 0
print('OK')
"`

Expected: `Found 0 skills` then `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/app/reasoning/langchain_agent/skills/discovery.py
git commit -m "feat(skills): add discovery module with dual-directory scan and cache"
```

---

### Task 3: 6 个内置 SKILL.md

**Files:**
- Create: `backend/app/reasoning/skills/stock-deep-dive/SKILL.md`
- Create: `backend/app/reasoning/skills/industry-scan/SKILL.md`
- Create: `backend/app/reasoning/skills/event-driven/SKILL.md`
- Create: `backend/app/reasoning/skills/supply-chain/SKILL.md`
- Create: `backend/app/reasoning/skills/industry-state/SKILL.md`
- Create: `backend/app/reasoning/skills/divergence-mining/SKILL.md`

- [ ] **Step 1: Write stock-deep-dive/SKILL.md**

```markdown
---
name: stock-deep-dive
description: 个股深度分析，从基本面、技术面、产业链、事件四个维度全面评估
version: 1.0.0
metadata:
  tags: [个股, 基本面, 技术面, 估值, 产业链]
  category: finance
  related_skills: [event-driven, supply-chain, divergence-mining]
---

# 个股深度分析

## 触发条件
- 用户明确询问某只股票/公司的分析或评估
- 用户要求评估某公司的投资价值或基本面
- 用户提到具体股票代码或简称并询问"怎么看"

## 分析流程

### 第一步：公司画像
1. `resolve("股票名")` → 锚定图谱实体
2. `expand(entity_id, select=["properties","metrics"])` → 获取公司属性和量化指标
3. `get_stock_profile` → 补充主营业务、行业分类等基本信息

### 第二步：技术面
4. `get_kline` → 获取 K 线数据，观察趋势和估值分位

### 第三步：基本面
5. `get_research_report` → 获取最新研报观点
6. `get_announcement` → 查看近期公告
7. `get_irm` → 查看投资者关系互动记录

### 第四步：事件与舆情
8. `find_events` → 搜索国内相关新闻事件（优先于 tavily_search）
9. `tavily_search` → 补充外部视角和政策动态

### 第五步：可视化
10. `present_chart` → 渲染 K 线/指标图表（最后调用）

## 关键工具
- resolve, expand, get_stock_profile, get_kline
- get_research_report, get_announcement, get_irm
- find_events, get_event_detail, tavily_search
- present_chart

## 输出要求
- 使用结构化报告格式：核心逻辑链 → 关键数据支撑 → 催化剂日历 → 风险矩阵 → 情景推演 → 跟踪指标
- 所有定量结论必须追溯到 L1 证据（fetch_evidence）
- 不确定处标注 TIER 置信度等级
- 报告末尾附"本报告不构成投资建议"

## 陷阱
- 不要仅凭单一指标（如 PE）下结论
- 不要忽略产业链传导效应
- 技术面分析需结合基本面验证
- 研报观点需交叉验证，不可单一来源采信
```

- [ ] **Step 2: Write industry-scan/SKILL.md**

```markdown
---
name: industry-scan
description: 行业/板块扫描，识别板块热度、轮动机会和市场情绪
version: 1.0.0
metadata:
  tags: [行业, 板块, 轮动, 市场情绪]
  category: finance
  related_skills: [industry-state, supply-chain]
---

# 行业/板块扫描

## 触发条件
- 用户询问某个行业/板块的走势或机会
- 用户要求扫描市场热点或轮动方向
- 用户无具体标的，要求推荐方向

## 分析流程

### 第一步：市场情绪
1. `get_concept_hot` → 获取当前热门概念板块
2. `get_market_breadth` → 获取市场宽度数据，判断整体情绪

### 第二步：行业动态
3. `find_events` → 搜索行业相关新闻和政策动态
4. `tavily_search` → 补充外部行业资讯

### 第三步：产业链视角
5. `resolve("行业关键词")` → 锚定行业核心实体
6. `expand(entity_id, select=["upstream","downstream"])` → 产业链结构

### 第四步：研报验证
7. `get_research_report` → 获取行业研报，验证判断

## 关键工具
- get_concept_hot, get_market_breadth
- find_events, tavily_search
- resolve, expand
- get_research_report

## 输出要求
- 列出当前热门板块及热度排序
- 分析轮动逻辑和持续性
- 标注板块内代表性标的
- 给出关注方向和建议

## 陷阱
- 板块热度可能短期脉冲，需区分趋势和噪音
- 概念板块分类可能不精确，需交叉验证
- 行业研报可能有利益冲突，注意来源可信度
```

- [ ] **Step 3: Write event-driven/SKILL.md**

```markdown
---
name: event-driven
description: 事件驱动分析，评估公告、新闻、政策事件对股价的影响方向和程度
version: 1.0.0
metadata:
  tags: [事件驱动, 公告, 新闻, 催化剂]
  category: finance
  related_skills: [stock-deep-dive, divergence-mining]
---

# 事件驱动分析

## 触发条件
- 用户询问某个事件对股票的影响
- 用户提到某条新闻/公告要求分析
- 用户问"最近有什么利好/利空"

## 分析流程

### 第一步：事件收集
1. `find_events` → 搜索国内 A 股相关新闻事件
2. `get_event_detail` → 获取感兴趣事件的全文内容

### 第二步：外部视角
3. `tavily_search` → 补充外部媒体和机构观点
4. `web_fetch` → 获取重要链接的全文

### 第三步：官方信息
5. `get_announcement` → 查看相关官方公告
6. `get_irm` → 查看投资者互动记录

### 第四步：影响分析
7. `resolve("涉及公司")` → 锚定图谱实体
8. `expand(entity_id, select=["relations"])` → 查看影响传导链

### 第五步：价格验证
9. `get_kline` → 观察事件前后价格反应

## 关键工具
- find_events, get_event_detail, tavily_search, web_fetch
- get_announcement, get_irm
- resolve, expand
- get_kline

## 输出要求
- 事件分类：利好/利空/中性
- 影响程度评估：重大/中等/轻微
- 影响路径分析：直接影响 vs 间接传导
- 时间维度：短期冲击 vs 长期趋势
- 标注信息来源和可信度

## 陷阱
- 不要过度解读单一事件
- 区分市场预期内和预期外事件
- 注意事件的时间衰减效应
- 公告标题可能误导，必须阅读全文
```

- [ ] **Step 4: Write supply-chain/SKILL.md**

```markdown
---
name: supply-chain
description: 产业链传导分析，追踪上下游关系、传导路径和竞争格局
version: 1.0.0
metadata:
  tags: [产业链, 供应链, 上下游, 竞争]
  category: finance
  related_skills: [industry-state, divergence-mining]
---

# 产业链传导分析

## 触发条件
- 用户询问产业链上下游关系
- 用户要求分析某个环节变化对整条链的影响
- 用户询问供应商/客户关系

## 分析流程

### 第一步：产业链结构
1. `resolve("核心公司")` → 锚定实体
2. `expand(entity_id, select=["upstream","downstream"], filter={depth:3})` → 获取上下游

### 第二步：路径分析
3. `neo4j_path` → 补充任意两点间最短路径（resolve/expand 不支持时使用）

### 第三步：竞争格局
4. `expand(entity_id, select=["peers"])` → 获取竞争对手

### 第四步：预期差视角
5. `expand(entity_id, select=["divergence"])` → 查看 Fact vs Estimate 分歧

### 第五步：验证
6. `get_research_report` → 研报验证传导逻辑
7. `tavily_search` → 实时资讯补充催化剂

## 关键工具
- resolve, expand, neo4j_path
- get_research_report, tavily_search

## 输出要求
- 绘制产业链结构图（用文字描述关键节点和关系）
- 标注各环节的议价能力和利润分配
- 识别关键瓶颈和替代风险
- 分析传导方向和时滞

## 陷阱
- 产业链关系可能随时间和政策变化
- 不要假设线性传导，注意反馈循环
- 区分直接供应商和间接供应商
- 注意进口替代和国产化趋势
```

- [ ] **Step 5: Write industry-state/SKILL.md**

```markdown
---
name: industry-state
description: 行业状态评估，分析竞争格局、景气度、生命周期和政策环境
version: 1.0.0
metadata:
  tags: [行业, 竞争格局, 景气度, 政策]
  category: finance
  related_skills: [industry-scan, supply-chain]
---

# 行业状态评估

## 触发条件
- 用户询问某个行业的竞争格局
- 用户要求评估行业景气度
- 用户询问行业发展趋势

## 分析流程

### 第一步：行业画像
1. `neo4j_industry_state` → 获取行业公司状态分布

### 第二步：竞争分析
2. `resolve("行业代表公司")` → 锚定实体
3. `expand(entity_id, select=["properties","peers"])` → 各公司属性和竞争格局

### 第三步：市场情绪
4. `get_concept_hot` → 板块热度
5. `get_market_breadth` → 市场宽度

## 关键工具
- neo4j_industry_state
- resolve, expand
- get_concept_hot, get_market_breadth

## 输出要求
- 行业生命周期阶段判断
- 竞争格局分析（集中度、龙头地位）
- 景气度指标和趋势
- 政策环境评估
- 关键成功因素

## 陷阱
- 行业分类标准可能不统一
- 景气度指标有滞后性
- 不同细分行业可能处于不同周期阶段
```

- [ ] **Step 6: Write divergence-mining/SKILL.md**

```markdown
---
name: divergence-mining
description: 预期差挖掘，发现 Fact vs Estimate 分歧点，寻找市场尚未充分定价的机会
version: 1.0.0
metadata:
  tags: [预期差, 信息差, 认知差, 时间差]
  category: finance
  related_skills: [stock-deep-dive, event-driven, supply-chain]
---

# 预期差挖掘

## 触发条件
- 用户要求寻找预期差或投资机会
- 用户询问市场是否充分定价了某个因素
- 用户要求做深度基本面挖掘

## 分析流程

### 第一步：分歧发现
1. `resolve("目标公司")` → 锚定实体
2. `expand(entity_id, select=["divergence"])` → Fact vs Estimate 分歧点

### 第二步：向上追溯
3. `expand(entity_id, select=["upstream"])` → 追踪预期差传导来源

### 第三步：横向对比
4. `expand(entity_id, select=["peers"])` → 同行对比验证认知差

### 第四步：证据追溯
5. `fetch_evidence` → L1 证据追溯，确认 Fact 可信度

### 第五步：外部验证
6. `get_research_report` → 券商一致预期参考
7. `tavily_search` → 催化剂和最新动态

## 关键工具
- resolve, expand, fetch_evidence
- get_research_report, tavily_search

## 输出要求
- 列出发现的预期差点（按置信度排序）
- 每条预期差包含：分歧点描述、Fact vs Estimate 对比、证据来源
- 判断预期差类型：信息差/认知差/时间差
- 评估市场修正的可能性和时间窗口
- 给出关注建议和证伪条件

## 陷阱
- Fact 和 Estimate 的区别需要仔细甄别
- 不要将短期波动误判为预期差
- 预期差可能已经被市场消化，需验证时间窗口
- 单一证据不足以支撑结论，需交叉验证
```

- [ ] **Step 7: Verify all 6 skills are discoverable**

Run: `cd backend && python -c "
from app.reasoning.langchain_agent.skills.discovery import scan_skills, get_skills_index
skills = scan_skills()
print(f'Found {len(skills)} skills:')
for name, s in sorted(skills.items()):
    print(f'  - {name}: {s.description[:50]}... (builtin={s.is_builtin})')
assert len(skills) == 6
index = get_skills_index()
assert len(index) == 6
# Verify lazy content loading
for s in skills.values():
    c = s.content
    assert len(c) > 100, f'{s.name} content too short: {len(c)} chars'
print('All skills loaded OK')
"`

Expected: 6 skills listed, all with `builtin=True`, all content loaded

- [ ] **Step 8: Commit**

```bash
git add backend/app/reasoning/skills/
git commit -m "feat(skills): add 6 built-in SKILL.md files covering all analysis scenarios"
```

---

### Task 4: skills_list + skill_view LangChain Tools

**Files:**
- Create: `backend/app/reasoning/langchain_agent/skills/tools.py`
- Modify: `backend/app/reasoning/tools/tools.py` (register tools)

- [ ] **Step 1: Write tools.py — skills_list and skill_view as LangChain BaseTool**

```python
"""Skill Agent Tools — skills_list + skill_view (P0) + skill_manage (P1)."""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from app.reasoning.langchain_agent.skills.discovery import (
    get_skills_index,
    invalidate_cache,
    load_skill,
    scan_skills,
)

logger = logging.getLogger(__name__)

# ── skills_list ──────────────────────────────────────────────────────────


class SkillsListInput(BaseModel):
    """skills_list 的输入参数（无参数，列出所有 skill）。"""
    pass


class SkillsListTool(BaseTool):
    name: str = "skills_list"
    description: str = (
        "列出所有可用的 skill（name + description）。"
        "使用 skill_view(name) 加载完整内容。"
    )
    args_schema: type[BaseModel] = SkillsListInput

    def _run(self, **kwargs: Any) -> str:
        index = get_skills_index()
        if not index:
            return json.dumps(
                {"success": True, "skills": [], "count": 0, "message": "没有可用的 skill"},
                ensure_ascii=False,
            )

        skills_data = [
            {
                "name": s.name,
                "description": s.description,
                "related_skills": s.related_skills,
            }
            for s in index
        ]

        categories = sorted({
            s.related_skills[0] if s.related_skills else "other"
            for s in index
        })

        return json.dumps(
            {
                "success": True,
                "skills": skills_data,
                "count": len(skills_data),
                "categories": categories,
                "hint": "使用 skill_view(name) 加载完整 skill 内容",
            },
            ensure_ascii=False,
        )


# ── skill_view ───────────────────────────────────────────────────────────


class SkillViewInput(BaseModel):
    """skill_view 的输入参数。"""
    name: str = Field(description="skill 名称（使用 skills_list 查看可用 skill）")


class SkillViewTool(BaseTool):
    name: str = "skill_view"
    description: str = (
        "加载指定 skill 的完整内容。"
        "Skill 包含详细的分析流程、工具组合和注意事项。"
        "当任务复杂时，优先加载对应 skill 获取指导。"
    )
    args_schema: type[BaseModel] = SkillViewInput

    def _run(self, name: str, **kwargs: Any) -> str:
        skill = load_skill(name)
        if skill is None:
            available = [s.name for s in get_skills_index()]
            return json.dumps(
                {
                    "success": False,
                    "error": f"Skill '{name}' 不存在",
                    "available_skills": available,
                    "hint": "使用 skills_list 查看所有可用 skill",
                },
                ensure_ascii=False,
            )

        result = {
            "success": True,
            "name": skill.name,
            "description": skill.description,
            "content": skill.content,
            "tags": skill.tags,
            "related_skills": skill.related_skills,
            "is_builtin": skill.is_builtin,
        }

        # 更新使用统计（best-effort）
        try:
            from app.reasoning.langchain_agent.skills.usage import bump_usage
            bump_usage(name)
        except Exception:
            pass

        return json.dumps(result, ensure_ascii=False)


# ── 工具实例 ─────────────────────────────────────────────────────────────

skills_list_tool = SkillsListTool()
skill_view_tool = SkillViewTool()
```

- [ ] **Step 2: Register skills_list and skill_view in tools/tools.py**

Read the current `BUILTIN_TOOLS` list in `backend/app/reasoning/tools/tools.py`:

```python
# Current:
from app.reasoning.tools.builtins import ask_clarification, ask_user_question

BUILTIN_TOOLS: list[BaseTool] = [
    ask_user_question,
    ask_clarification,
]
```

Change to:

```python
from app.reasoning.tools.builtins import ask_clarification, ask_user_question
from app.reasoning.langchain_agent.skills.tools import skills_list_tool, skill_view_tool

BUILTIN_TOOLS: list[BaseTool] = [
    ask_user_question,
    ask_clarification,
    skills_list_tool,
    skill_view_tool,
]
```

- [ ] **Step 3: Verify tools are registered**

Run: `cd backend && python -c "
from app.reasoning.tools.tools import get_available_tools
tools = get_available_tools()
names = {t.name for t in tools}
assert 'skills_list' in names, f'skills_list not found in {names}'
assert 'skill_view' in names, f'skill_view not found in {names}'
print(f'All {len(tools)} tools: {sorted(names)}')
print('OK')
"`

Expected: both `skills_list` and `skill_view` in tool names

- [ ] **Step 4: Test skills_list tool**

Run: `cd backend && python -c "
from app.reasoning.langchain_agent.skills.tools import skills_list_tool
result = skills_list_tool._run()
import json
data = json.loads(result)
assert data['success']
assert data['count'] == 6
print(json.dumps(data, ensure_ascii=False, indent=2))
"`

Expected: JSON with 6 skills listed

- [ ] **Step 5: Test skill_view tool**

Run: `cd backend && python -c "
from app.reasoning.langchain_agent.skills.tools import skill_view_tool
result = skill_view_tool._run('stock-deep-dive')
import json
data = json.loads(result)
assert data['success']
assert 'content' in data
assert len(data['content']) > 200
print(f'Loaded {data[\"name\"]}: {len(data[\"content\"])} chars')
print(f'Related: {data[\"related_skills\"]}')
"`

Expected: `Loaded stock-deep-dive: <N> chars` with related skills

- [ ] **Step 6: Test skill_view for non-existent skill**

Run: `cd backend && python -c "
from app.reasoning.langchain_agent.skills.tools import skill_view_tool
result = skill_view_tool._run('nonexistent')
import json
data = json.loads(result)
assert not data['success']
assert 'available_skills' in data
print(data['error'])
"`

Expected: `Skill 'nonexistent' 不存在`

- [ ] **Step 7: Commit**

```bash
git add backend/app/reasoning/langchain_agent/skills/tools.py backend/app/reasoning/tools/tools.py
git commit -m "feat(skills): add skills_list and skill_view LangChain tools"
```

---

### Task 5: System Prompt 改造 — 精简场景标签 + 注入 skill 索引

**Files:**
- Modify: `backend/app/reasoning/langchain_agent/prompts/lead_system_prompt.py`

- [ ] **Step 1: Replace `<tool_strategy>` section — keep only concurrency rules + failure handling**

Replace the entire `<tool_strategy>...</tool_strategy>` block (lines 172-228) with:

```xml
<tool_strategy>
**工具使用策略**：

具体的分析场景和工具组合请参考对应 Skill（调用 `skill_view` 加载）。通用规则：

**并发规则**：
- 同一步骤中的多个独立工具可并发调用
- `present_chart` 和 `write_file` 必须串行（有副作用）
- `ask_clarification` 必须单独调用（会暂停执行）

**工具失败处理**：
- 单个工具失败不影响整体分析，用已有信息继续
- 图谱查询失败 → 用搜索和研报替代
- 搜索失败 → 用已有知识库数据
- 所有工具失败 → 基于已有信息给出分析，明确标注数据不足
</tool_strategy>
```

- [ ] **Step 2: Replace `<graph_reasoning>` section — keep only general principles**

Replace the entire `<graph_reasoning>...</graph_reasoning>` block (lines 230-249) with:

```xml
<graph_reasoning>
**图谱推理通用原则**：

1. **实体锚定**：从用户消息中识别公司名、产品名，用 `resolve` 锚定到图谱实体
2. **受控展开**：用 `expand(entity_id, select=[...])` 按需获取子图，避免一次性加载全部关系
3. **置信度参考**：RELATES 边 weight 表示关系强度（0-1），stmt_type 表示可信度：
   - Fact = 直接采信
   - Claim = 需交叉验证
   - Estimate = 标注为预测
4. **四层导航**：L4 行业主题 → L3 逻辑关系 → L2 结构化索引 → L1 证据原文
5. **降级规则**：图谱查询失败 → 用 `tavily_search` + `get_research_report` 替代

具体场景的工具组合请查看对应 Skill（调用 `skill_view` 加载）。
</graph_reasoning>
```

- [ ] **Step 3: Update `get_skills_prompt_section()` to pull from discovery**

Replace the current implementation:

```python
def get_skills_prompt_section(available_skills: set[str] | None = None) -> str:
    if available_skills is None:
        return ""

    skills_list = sorted(available_skills)
    if not skills_list:
        return ""

    items = "\n".join(f"- {s}" for s in skills_list)
    return f"""\
<skills>
**可用 Skills**（如任务复杂，优先加载对应 Skill）：
{items}
</skills>
"""
```

With:

```python
def get_skills_prompt_section() -> str:
    """从 discovery 模块获取 skill 索引并格式化注入 system prompt。"""
    try:
        from app.reasoning.langchain_agent.skills.discovery import get_skills_index

        index = get_skills_index()
    except Exception:
        return ""

    if not index:
        return ""

    items: list[str] = []
    for s in index:
        line = f"- {s.name}: {s.description}"
        if s.related_skills:
            related = ", ".join(s.related_skills)
            line += f" → 关联: {related}"
        items.append(line)

    skills_list = "\n".join(items)
    return f"""\
<skills>
**可用 Skills**（如任务复杂，优先调用 `skill_view` 加载对应 Skill）：
{skills_list}

使用方式：
- 调用 `skills_list` 查看所有 skill
- 调用 `skill_view(name)` 加载完整分析流程
</skills>
"""
```

- [ ] **Step 4: Update `apply_prompt_template()` signature**

Remove `available_skills` parameter and update the call to `get_skills_prompt_section()`:

```python
def apply_prompt_template(
    subagent_enabled: bool = False,
    max_concurrent_subagents: int = 3,
    memory_content: str = "",
    kg_anchors: str = "",
    background_context: str = "",
    graph_context: str = "",
) -> str:
```

And in the body:

```python
skills_section = get_skills_prompt_section()
```

- [ ] **Step 5: Verify the prompt builds correctly**

Run: `cd backend && python -c "
from app.reasoning.langchain_agent.prompts.lead_system_prompt import apply_prompt_template
prompt = apply_prompt_template()
assert '<skills>' in prompt
assert 'stock-deep-dive' in prompt
assert 'skill_view' in prompt
# Verify old scenarios are removed
assert '场景 A' not in prompt
assert '场景 B' not in prompt
# Verify concurrency rules are kept
assert '并发规则' in prompt
# Verify graph reasoning principles are kept
assert '实体锚定' in prompt
print(f'Prompt length: {len(prompt)} chars')
print('OK')
"`

Expected: `OK` with prompt containing skills index but not old scenarios

- [ ] **Step 6: Commit**

```bash
git add backend/app/reasoning/langchain_agent/prompts/lead_system_prompt.py
git commit -m "refactor(skills): replace hardcoded scenarios with dynamic skill index in system prompt"
```

---

### Task 6: Client 集成 — 传入 skill 索引

**Files:**
- Modify: `backend/app/reasoning/langchain_agent/client.py`

- [ ] **Step 1: Update `run_lead_agent()` — remove `available_skills` param from `apply_prompt_template()` call**

Find the call to `apply_prompt_template()` in `run_lead_agent()` and remove the `available_skills` argument. The function no longer accepts it since it pulls from discovery internally.

Read the current invocation (search for `apply_prompt_template` in client.py):

```python
# Old:
system_prompt = apply_prompt_template(
    subagent_enabled=subagent_enabled,
    max_concurrent_subagents=max_concurrent_subagents,
    available_skills=available_skills,  # REMOVE
    memory_content=memory_content,
    kg_anchors=kg_anchors,
    background_context=background_context,
    graph_context=graph_context,
)
```

Change to:

```python
system_prompt = apply_prompt_template(
    subagent_enabled=subagent_enabled,
    max_concurrent_subagents=max_concurrent_subagents,
    memory_content=memory_content,
    kg_anchors=kg_anchors,
    background_context=background_context,
    graph_context=graph_context,
)
```

- [ ] **Step 2: Verify client imports still work**

Run: `cd backend && python -c "
from app.reasoning.langchain_agent.client import LangChainAgentClient
print('Client imports OK')
"`

Expected: `Client imports OK`

- [ ] **Step 3: Commit**

```bash
git add backend/app/reasoning/langchain_agent/client.py
git commit -m "refactor(skills): remove available_skills param, now auto-discovered from skills directory"
```

---

### Task 7: P1 — skill_manage 工具

**Files:**
- Modify: `backend/app/reasoning/langchain_agent/skills/tools.py` (add skill_manage)
- Create: `backend/app/reasoning/langchain_agent/skills/usage.py`
- Modify: `backend/app/reasoning/tools/tools.py` (register skill_manage)

- [ ] **Step 1: Write usage.py**

```python
"""Skill 使用统计 — 读写 ~/.qingshui/skills/.usage.json。"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_USAGE_FILE = Path.home() / ".qingshui" / "skills" / ".usage.json"


def _read_usage() -> dict:
    """读取使用统计文件（best-effort）。"""
    if not _USAGE_FILE.exists():
        return {}
    try:
        return json.loads(_USAGE_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        logger.debug(f"Failed to read usage file: {e}")
        return {}


def _write_usage(data: dict) -> None:
    """写入使用统计文件（best-effort）。"""
    try:
        _USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _USAGE_FILE.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        logger.debug(f"Failed to write usage file: {e}")


def bump_usage(name: str) -> None:
    """增加 skill 使用计数（best-effort）。"""
    try:
        data = _read_usage()
        now = datetime.now(timezone.utc).isoformat()

        if name not in data:
            data[name] = {
                "created_at": now,
                "use_count": 0,
                "last_used": now,
            }

        data[name]["use_count"] = data[name].get("use_count", 0) + 1
        data[name]["last_used"] = now

        _write_usage(data)
    except Exception as e:
        logger.debug(f"Failed to bump usage for {name}: {e}")


def forget_usage(name: str) -> None:
    """删除 skill 使用统计（skill 被删除时调用）。"""
    try:
        data = _read_usage()
        if name in data:
            del data[name]
            _write_usage(data)
    except Exception as e:
        logger.debug(f"Failed to forget usage for {name}: {e}")
```

- [ ] **Step 2: Add skill_manage tool to tools.py**

Add the following to `backend/app/reasoning/langchain_agent/skills/tools.py`:

```python
# ── skill_manage (P1) ────────────────────────────────────────────────────

import re
import os
from pathlib import Path

_EXTERNAL_SKILLS_DIR = Path.home() / ".qingshui" / "skills"
_VALID_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_MAX_NAME_LENGTH = 64
_MAX_CONTENT_BYTES = 100_000  # ~36K tokens


class SkillManageInput(BaseModel):
    action: str = Field(
        description="操作类型: create, patch, edit, delete"
    )
    name: str = Field(
        description="skill 名称（小写字母+数字+连字符，最长 64 字符）"
    )
    content: str | None = Field(
        default=None,
        description="[create/edit] 完整 SKILL.md 内容（YAML frontmatter + Markdown 正文）"
    )
    old_string: str | None = Field(
        default=None,
        description="[patch] 要替换的文本（需精确匹配文件中的内容）"
    )
    new_string: str | None = Field(
        default=None,
        description="[patch] 替换后的文本（空字符串表示删除）"
    )


class SkillManageTool(BaseTool):
    name: str = "skill_manage"
    description: str = (
        "管理 skill（创建、修改、删除）。"
        "Skill 是分析场景的流程指南，可以帮助你更高效地完成复杂任务。\n\n"
        "操作说明：\n"
        "- create: 从成功经验中提炼新 skill，保存到外部目录\n"
        "- patch: 精确替换 skill 中的部分内容（修改内置 skill 时，"
        "会自动创建外部覆盖版本）\n"
        "- edit: 完整重写 skill 内容\n"
        "- delete: 删除外部目录中的 skill（内置 skill 不可删除）\n\n"
        "注意：创建和删除 skill 前请先与用户确认。"
    )
    args_schema: type[BaseModel] = SkillManageInput

    def _run(
        self,
        action: str,
        name: str,
        content: str | None = None,
        old_string: str | None = None,
        new_string: str | None = None,
        **kwargs: Any,
    ) -> str:
        if action == "create":
            return self._create(name, content)
        elif action == "patch":
            return self._patch(name, old_string, new_string)
        elif action == "edit":
            return self._edit(name, content)
        elif action == "delete":
            return self._delete(name)
        else:
            return json.dumps(
                {
                    "success": False,
                    "error": f"未知操作 '{action}'。可用操作: create, patch, edit, delete",
                },
                ensure_ascii=False,
            )

    def _validate_name(self, name: str) -> str | None:
        if not name:
            return "skill 名称不能为空"
        if len(name) > _MAX_NAME_LENGTH:
            return f"skill 名称超过 {_MAX_NAME_LENGTH} 字符"
        if not _VALID_NAME_RE.match(name):
            return "skill 名称格式无效（小写字母+数字+连字符/下划线/点）"
        return None

    def _validate_content(self, content: str) -> str | None:
        if not content or not content.strip():
            return "content 不能为空"
        if len(content.encode("utf-8")) > _MAX_CONTENT_BYTES:
            return f"content 超过 {_MAX_CONTENT_BYTES} 字节限制"
        if not content.startswith("---"):
            return "SKILL.md 必须以 YAML frontmatter (---) 开头"
        return None

    def _resolve_target(self, name: str) -> tuple[Path, bool]:
        """返回 (target_dir, is_builtin_only)。

        如果 skill 只存在于内置目录，返回内置路径 + is_builtin_only=True。
        如果存在外部版本，返回外部路径 + is_builtin_only=False。
        如果完全不存在，返回外部路径 + is_builtin_only=False。
        """
        external_dir = _EXTERNAL_SKILLS_DIR / name
        if external_dir.exists():
            return external_dir, False

        skills = scan_skills()
        skill = skills.get(name)
        if skill and skill.is_builtin:
            return skill.path.parent, True

        return external_dir, False

    def _create(self, name: str, content: str | None) -> str:
        if content is None:
            return json.dumps(
                {"success": False, "error": "create 操作需要 content 参数"},
                ensure_ascii=False,
            )

        err = self._validate_name(name)
        if err:
            return json.dumps({"success": False, "error": err}, ensure_ascii=False)

        err = self._validate_content(content)
        if err:
            return json.dumps({"success": False, "error": err}, ensure_ascii=False)

        # 检查是否已存在
        existing = scan_skills().get(name)
        if existing:
            return json.dumps(
                {
                    "success": False,
                    "error": f"Skill '{name}' 已存在（{'内置' if existing.is_builtin else '外部'}）。"
                    f"使用 edit 或 patch 修改。",
                },
                ensure_ascii=False,
            )

        target_dir = _EXTERNAL_SKILLS_DIR / name
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / "SKILL.md").write_text(content, encoding="utf-8")

        invalidate_cache()

        return json.dumps(
            {
                "success": True,
                "message": f"Skill '{name}' 创建成功",
                "path": str(target_dir / "SKILL.md"),
            },
            ensure_ascii=False,
        )

    def _patch(self, name: str, old_string: str | None, new_string: str | None) -> str:
        if old_string is None or new_string is None:
            return json.dumps(
                {"success": False, "error": "patch 操作需要 old_string 和 new_string 参数"},
                ensure_ascii=False,
            )

        target_dir, is_builtin_only = self._resolve_target(name)

        if is_builtin_only:
            # 内置 skill → 读取内置内容，patch 后写入外部目录
            skill = load_skill(name)
            if skill is None:
                return json.dumps(
                    {"success": False, "error": f"Skill '{name}' 不存在"},
                    ensure_ascii=False,
                )
            raw = skill.path.read_text(encoding="utf-8")
        else:
            skill_md = target_dir / "SKILL.md"
            if not skill_md.exists():
                return json.dumps(
                    {"success": False, "error": f"Skill '{name}' 不存在"},
                    ensure_ascii=False,
                )
            raw = skill_md.read_text(encoding="utf-8")

        if old_string not in raw:
            return json.dumps(
                {
                    "success": False,
                    "error": "old_string 在文件中未找到。请使用 skill_view 查看完整内容后重试。",
                },
                ensure_ascii=False,
            )

        new_content = raw.replace(old_string, new_string, 1)

        err = self._validate_content(new_content)
        if err:
            return json.dumps({"success": False, "error": f"patch 后内容无效: {err}"}, ensure_ascii=False)

        # 写入外部目录
        external_dir = _EXTERNAL_SKILLS_DIR / name
        external_dir.mkdir(parents=True, exist_ok=True)
        (external_dir / "SKILL.md").write_text(new_content, encoding="utf-8")

        invalidate_cache()

        note = ""
        if is_builtin_only:
            note = "（已创建外部覆盖版本，原内置 skill 保持不变）"

        return json.dumps(
            {
                "success": True,
                "message": f"Skill '{name}' patch 成功{note}",
                "path": str(external_dir / "SKILL.md"),
            },
            ensure_ascii=False,
        )

    def _edit(self, name: str, content: str | None) -> str:
        if content is None:
            return json.dumps(
                {"success": False, "error": "edit 操作需要 content 参数"},
                ensure_ascii=False,
            )

        err = self._validate_content(content)
        if err:
            return json.dumps({"success": False, "error": err}, ensure_ascii=False)

        target_dir, is_builtin_only = self._resolve_target(name)

        if is_builtin_only:
            # 内置 skill → 写入外部目录
            external_dir = _EXTERNAL_SKILLS_DIR / name
            external_dir.mkdir(parents=True, exist_ok=True)
            (external_dir / "SKILL.md").write_text(content, encoding="utf-8")
            invalidate_cache()
            return json.dumps(
                {
                    "success": True,
                    "message": f"Skill '{name}' 编辑成功（已创建外部覆盖版本）",
                    "path": str(external_dir / "SKILL.md"),
                },
                ensure_ascii=False,
            )

        if not target_dir.exists():
            return json.dumps(
                {"success": False, "error": f"Skill '{name}' 不存在"},
                ensure_ascii=False,
            )

        (target_dir / "SKILL.md").write_text(content, encoding="utf-8")
        invalidate_cache()

        return json.dumps(
            {
                "success": True,
                "message": f"Skill '{name}' 编辑成功",
                "path": str(target_dir / "SKILL.md"),
            },
            ensure_ascii=False,
        )

    def _delete(self, name: str) -> str:
        target_dir, is_builtin_only = self._resolve_target(name)

        if is_builtin_only:
            return json.dumps(
                {
                    "success": False,
                    "error": f"Skill '{name}' 是内置 skill，不可删除。"
                    f"如需禁用，可以创建空的外部覆盖版本。",
                },
                ensure_ascii=False,
            )

        if not target_dir.exists():
            return json.dumps(
                {"success": False, "error": f"Skill '{name}' 不存在"},
                ensure_ascii=False,
            )

        import shutil
        shutil.rmtree(target_dir)
        invalidate_cache()

        # 清理使用统计
        try:
            from app.reasoning.langchain_agent.skills.usage import forget_usage
            forget_usage(name)
        except Exception:
            pass

        return json.dumps(
            {"success": True, "message": f"Skill '{name}' 已删除"},
            ensure_ascii=False,
        )


skill_manage_tool = SkillManageTool()
```

- [ ] **Step 3: Register skill_manage in tools/tools.py**

Add `skill_manage_tool` to `BUILTIN_TOOLS`:

```python
from app.reasoning.langchain_agent.skills.tools import (
    skills_list_tool,
    skill_view_tool,
    skill_manage_tool,
)

BUILTIN_TOOLS: list[BaseTool] = [
    ask_user_question,
    ask_clarification,
    skills_list_tool,
    skill_view_tool,
    skill_manage_tool,
]
```

- [ ] **Step 4: Test skill_manage create**

Run: `cd backend && python -c "
from app.reasoning.langchain_agent.skills.tools import skill_manage_tool
import json

# Test create
result = skill_manage_tool._run(
    action='create',
    name='test-skill',
    content='''---
name: test-skill
description: 测试 skill，验证创建功能
---
# Test
This is a test skill.
'''
)
data = json.loads(result)
assert data['success'], f'Create failed: {data}'
print(f'Created: {data[\"message\"]}')

# Test duplicate
result2 = skill_manage_tool._run(
    action='create',
    name='test-skill',
    content='''---
name: test-skill
description: duplicate
---
# Dup
'''
)
data2 = json.loads(result2)
assert not data2['success']
print(f'Duplicate rejected: {data2[\"error\"]}')

# Cleanup
result3 = skill_manage_tool._run(action='delete', name='test-skill')
data3 = json.loads(result3)
assert data3['success']
print('Cleanup OK')
print('All tests passed')
"`

Expected: `All tests passed`

- [ ] **Step 5: Test skill_manage patch on builtin skill**

Run: `cd backend && python -c "
from app.reasoning.langchain_agent.skills.tools import skill_manage_tool
import json

# Patch builtin skill
result = skill_manage_tool._run(
    action='patch',
    name='stock-deep-dive',
    old_string='## 陷阱',
    new_string='## 注意事项'
)
data = json.loads(result)
assert data['success'], f'Patch failed: {data}'
print(f'Patch result: {data[\"message\"]}')

# Verify external override created
from pathlib import Path
ext = Path.home() / '.qingshui' / 'skills' / 'stock-deep-dive' / 'SKILL.md'
assert ext.exists(), f'External file not found at {ext}'
content = ext.read_text()
assert '## 注意事项' in content
assert '## 陷阱' not in content
print(f'External override verified at {ext}')

# Cleanup
import shutil
shutil.rmtree(ext.parent)
print('Cleanup OK')
"`

Expected: patch creates external override, cleanup removes it

- [ ] **Step 6: Commit**

```bash
git add backend/app/reasoning/langchain_agent/skills/usage.py backend/app/reasoning/langchain_agent/skills/tools.py backend/app/reasoning/tools/tools.py
git commit -m "feat(skills): add skill_manage tool (create/patch/edit/delete) with external override support"
```

---

### Task 8: P1 — 关联 Skill 推荐 + 使用统计排序

**Files:**
- Modify: `backend/app/reasoning/langchain_agent/skills/tools.py` (skills_list sorted by usage)

- [ ] **Step 1: Update skills_list to sort by usage and include related_skills**

In `SkillsListTool._run()`, update the skills_data construction to sort by `use_count` descending:

```python
def _run(self, **kwargs: Any) -> str:
    index = get_skills_index()

    # 加载使用统计用于排序
    try:
        from app.reasoning.langchain_agent.skills.usage import _read_usage
        usage = _read_usage()
    except Exception:
        usage = {}

    if not index:
        return json.dumps(
            {"success": True, "skills": [], "count": 0, "message": "没有可用的 skill"},
            ensure_ascii=False,
        )

    skills_data = []
    for s in index:
        u = usage.get(s.name, {})
        skills_data.append({
            "name": s.name,
            "description": s.description,
            "related_skills": s.related_skills,
            "use_count": u.get("use_count", 0),
            "last_used": u.get("last_used"),
        })

    # 按使用次数降序
    skills_data.sort(key=lambda s: s["use_count"], reverse=True)

    return json.dumps(
        {
            "success": True,
            "skills": skills_data,
            "count": len(skills_data),
            "hint": "使用 skill_view(name) 加载完整 skill 内容",
        },
        ensure_ascii=False,
    )
```

- [ ] **Step 2: Verify skills_list returns sorted results with related_skills**

Run: `cd backend && python -c "
from app.reasoning.langchain_agent.skills.tools import skills_list_tool
import json
result = skills_list_tool._run()
data = json.loads(result)
assert data['success']
for s in data['skills']:
    print(f'{s[\"name\"]}: use_count={s[\"use_count\"]}, related={s[\"related_skills\"]}')
assert 'related_skills' in data['skills'][0]
assert 'use_count' in data['skills'][0]
print('OK')
"`

Expected: All skills listed with related_skills and use_count fields

- [ ] **Step 3: Commit**

```bash
git add backend/app/reasoning/langchain_agent/skills/tools.py
git commit -m "feat(skills): sort skills_list by usage count, include related_skills in listing"
```

---

### Task 9: 最终集成验证

- [ ] **Step 1: Run full integration test**

Run: `cd backend && python -c "
# Full integration test: discovery → tools → prompt
from app.reasoning.langchain_agent.skills.discovery import scan_skills, get_skills_index
from app.reasoning.langchain_agent.skills.tools import skills_list_tool, skill_view_tool, skill_manage_tool
from app.reasoning.langchain_agent.prompts.lead_system_prompt import apply_prompt_template
from app.reasoning.tools.tools import get_available_tools
import json

# 1. Discovery
skills = scan_skills()
assert len(skills) == 6, f'Expected 6 skills, got {len(skills)}'
print(f'[1/6] Discovery: {len(skills)} skills found')

# 2. Skills index
index = get_skills_index()
assert len(index) == 6
print(f'[2/6] Index: {len(index)} entries')

# 3. Tools registration
tools = get_available_tools()
names = {t.name for t in tools}
for expected in ['skills_list', 'skill_view', 'skill_manage']:
    assert expected in names, f'{expected} not in tools'
print(f'[3/6] Tools: {len(tools)} total, skill tools registered')

# 4. skills_list
result = skills_list_tool._run()
data = json.loads(result)
assert data['success']
assert data['count'] == 6
print(f'[4/6] skills_list: {data[\"count\"]} skills')

# 5. skill_view
result = skill_view_tool._run('stock-deep-dive')
data = json.loads(result)
assert data['success']
assert len(data['content']) > 200
print(f'[5/6] skill_view: {data[\"name\"]} loaded ({len(data[\"content\"])} chars)')

# 6. Prompt
prompt = apply_prompt_template()
assert '<skills>' in prompt
assert 'stock-deep-dive' in prompt
assert 'skill_view' in prompt
assert '场景 A' not in prompt  # Old scenarios removed
print(f'[6/6] Prompt: {len(prompt)} chars, skill index injected')

print()
print('All integration tests passed!')
"`

Expected: All 6 checks pass

- [ ] **Step 2: Commit**

```bash
git add -A
git commit -m "test(skills): add full integration verification"
```

---

## Plan Summary

| Task | Description | Files Created | Files Modified |
|------|------------|---------------|----------------|
| 1 | Skill 数据模型 | `models.py`, `__init__.py` | — |
| 2 | Skill 发现模块 | `discovery.py` | — |
| 3 | 6 个内置 SKILL.md | 6 × `SKILL.md` | — |
| 4 | skills_list + skill_view tools | `tools.py` | `tools/tools.py` |
| 5 | System prompt 改造 | — | `lead_system_prompt.py` |
| 6 | Client 集成 | — | `client.py` |
| 7 | P1: skill_manage tool | `usage.py` | `tools.py`, `tools/tools.py` |
| 8 | P1: 关联推荐 + 排序 | — | `tools.py` |
| 9 | 集成验证 | — | — |

**Total: 10 new files, 4 modified files, 9 commits**