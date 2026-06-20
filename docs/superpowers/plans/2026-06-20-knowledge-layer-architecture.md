# Knowledge Layer Architecture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement V1.3 Schema unification (remove V4 7-type dual-track) and resolve/expand query primitives for the knowledge query layer.

**Architecture:** Two-phase delivery: Phase A cleans up V4 Schema → unified 3-type (Company/Product/Metric) across prompts, parsers, and services; Phase B adds `resolve` and `expand` LangChain tools that map declarative `select` fields to Cypher queries on the unified graph.

**Tech Stack:** Python 3.12, LangChain (Tool), Neo4j (py2neo/neo4j driver), Qdrant, MongoDB, pytest

---

## File Structure

### Phase A: V4 Schema Cleanup

| Action | File | Responsibility |
|--------|------|---------------|
| Modify | `backend/app/knowledge/extraction/rag_prompts.py` | Unify prompts to V1.3, remove ENTITY_TYPES_V4, merge ANNOUNCEMENT_EXTRACTION_PROMPT into unified prompt |
| Modify | `backend/app/knowledge/extraction/rag_extractor.py` | Rename `_parse_relates_v4` → `_parse_relates`, `_parse_metrics_v4` → `_parse_metrics`, `_parse_chunk_output_v4` → `_parse_chunk_output`, update VALID_ENTITY_TYPES_V2 |
| Modify | `backend/app/knowledge/relation_service.py` | Rename `upsert_relates_v4` → `upsert_relates`, update `upsert_relates` wrapper to pass through all params |
| Modify | `backend/app/knowledge/kg_extractor.py` | Update import and 3 call sites from `upsert_relates_v4` → `upsert_relates` |
| Modify | `backend/app/knowledge/irm_extractor.py` | Update import and 3 call sites, add stmt_type/relation_subtype |
| Modify | `backend/app/knowledge/extraction/light_extractor.py` | Update prompt reference |
| Create | `backend/tests/test_v13_schema_unified.py` | Integration test for unified schema |

### Phase B: resolve/expand Query Primitives

| Action | File | Responsibility |
|--------|------|---------------|
| Create | `backend/app/reasoning/tools/knowledge/graph_navigator.py` | `resolve` and `expand` tool implementations |
| Create | `backend/tests/test_graph_navigator.py` | Tests for resolve and expand |
| Modify | `backend/app/reasoning/tools/knowledge/__init__.py` | Export new tools |
| Modify | `backend/app/reasoning/tools/knowledge/neo4j/kg_search.py` | Refactor internal helpers for reuse by expand |

---

## Phase A: V4 Schema Cleanup

### Task 1: Unify rag_prompts.py — Remove V4, Create Unified V1.3 Prompt

**Files:**
- Modify: `backend/app/knowledge/extraction/rag_prompts.py`
- Test: `backend/tests/test_v13_schema_unified.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_v13_schema_unified.py`:

```python
"""Test that V1.3 Schema is unified — no V4 remnants in prompts."""
import re
from app.knowledge.extraction.rag_prompts import (
    EXTRACTION_PROMPT_V13,
    RELATES_EXTRACTION_PROMPT,
    ENTITY_TYPES,
    DEFAULT_ENTITY_TYPES,
    get_extraction_prompt,
)


def test_entity_types_is_v13():
    """ENTITY_TYPES must be exactly 3 types: Company, Product, Metric."""
    assert ENTITY_TYPES == ["Company", "Product", "Metric"]


def test_default_entity_types_is_v13():
    """DEFAULT_ENTITY_TYPES must point to V1.3 3-type list."""
    assert DEFAULT_ENTITY_TYPES == ENTITY_TYPES


def test_no_entity_types_v4_exported():
    """ENTITY_TYPES_V4 must not exist in the module."""
    from app.knowledge.extraction import rag_prompts
    assert not hasattr(rag_prompts, "ENTITY_TYPES_V4")


def test_v13_prompt_has_3_entity_types():
    """Unified prompt must only list 3 entity types."""
    prompt = EXTRACTION_PROMPT_V13
    assert "Company" in prompt
    assert "Product" in prompt
    assert "Metric" in prompt
    # V4 types must NOT appear as entity type headers
    assert "Category（分类）" not in prompt
    assert "Application（应用）" not in prompt
    assert "Technology（技术）" not in prompt
    assert "Project（项目）" not in prompt


def test_v13_prompt_has_stmt_type():
    """Unified prompt must include stmt_type (Fact/Claim/Estimate)."""
    prompt = EXTRACTION_PROMPT_V13
    assert "陈述类型" in prompt
    assert "Fact" in prompt
    assert "Claim" in prompt
    assert "Estimate" in prompt


def test_v13_prompt_has_metric_format():
    """Unified prompt must include structured Metric output format."""
    prompt = EXTRACTION_PROMPT_V13
    assert "METRIC:" in prompt
    assert "period:" in prompt or "period" in prompt


def test_v13_prompt_has_relates_format():
    """Unified prompt must include RELATES format with stmt_type."""
    prompt = EXTRACTION_PROMPT_V13
    assert "RELATES:" in prompt
    assert "陈述类型" in prompt


def test_v13_prompt_has_noise_rules():
    """Unified prompt must include 7-class noise prohibition rules."""
    prompt = EXTRACTION_PROMPT_V13
    assert "禁止抽取" in prompt


def test_get_extraction_prompt_returns_v13_for_all_source_types():
    """get_extraction_prompt must return V1.3 prompt for all source types."""
    for source_type in ("cninfo", "irm", "cninfo_announcement", "announcement",
                        "annual_report", "prospectus", "招股书", "research"):
        prompt = get_extraction_prompt(source_type)
        assert "Company" in prompt
        assert "Category（分类）" not in prompt


def test_no_announcement_v4_source_type():
    """announcement_v4 source_type must not appear in routing logic."""
    # This tests the routing function directly
    prompt = get_extraction_prompt("announcement_v4")
    # Should still get V1.3 prompt, not a V4-specific one
    assert "Category（分类）" not in prompt
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/lwm/code/QingshuiYanTou/backend && source .venv/bin/activate && python -m pytest tests/test_v13_schema_unified.py -v`
Expected: FAIL — `EXTRACTION_PROMPT_V13` not defined, `ENTITY_TYPES_V4` still exists

- [ ] **Step 3: Implement unified V1.3 prompt in rag_prompts.py**

In `backend/app/knowledge/extraction/rag_prompts.py`, make these changes:

1. **Replace `ENTITY_TYPES_V4` with unified `ENTITY_TYPES`** — the existing `ENTITY_TYPES = ["Company", "Product", "Metric"]` at line 260 already exists. Delete the `ENTITY_TYPES_V4` list (lines 148-156) entirely.

2. **Replace `DEFAULT_ENTITY_TYPES`** at line 261:
```python
DEFAULT_ENTITY_TYPES = ENTITY_TYPES
```

3. **Create `EXTRACTION_PROMPT_V13`** — merge the best of V4 + ANNOUNCEMENT + V1.3 prompts. Replace both `EXTRACTION_PROMPT_V4` and `ANNOUNCEMENT_EXTRACTION_PROMPT` with this unified prompt:

```python
EXTRACTION_PROMPT_V13 = """你是一名专业的投资研究知识图谱抽取专家。从以下文本中抽取 Schema V1.3 实体和 RELATES 关系。

【文本类型判断】
先判断文本属于哪一类：
- A. 研报正文/公告正文/互动易问答 → 可以抽取
- B. 封面声明/免责声明/风险提示 → 【禁止抽取】
- C. 文件路径/URL/Email/联系方式 → 【禁止抽取】
- D. 表格行（含"|"的多列对齐内容）→ 【禁止抽取】
- E. 页眉页脚/累计合计行/章节标题 → 【禁止抽取】

只有 A 类内容才参与实体和关系的抽取。

【实体类型白名单】只抽取以下3类，禁止生成白名单外的类型：
- Company（公司）：上市公司、重要客户、供应商、竞争对手
  禁止：券商研究所、投资公司、基金、监管机构
- Product（产品）：上市公司生产或销售的具体产品、材料、设备、服务
  应用场景/下游领域 → 写入关系的描述中，不作为独立实体
  技术路线/工艺 → 写入关系的描述中，不作为独立实体
- Metric（指标）：必须同时含【数字+单位】的量化或趋势指标
  禁止：无数值的泛化指标、指数名称、股票代码

【关系格式】统一使用 RELATES 自然语言关系：
RELATES: 实体A → 实体B
  关系描述: "100字以内，保留时间、方向、状态变化"
  置信度: 1.0
  陈述类型: Fact / Claim / Estimate
  来源: "原文相关句"

陈述类型规则：
- Fact: 原文明确陈述的客观事实（如"2024年营收120亿元"）
- Claim: 公司/管理层的主张或声明（如"管理层表示订单饱满"）
- Estimate: 预测、推测、目标（如"预计2025年产能翻倍"）

置信度规则：
- 1.0 = 原文直接陈述
- 0.7 = LLM 基于上下文轻度推断，必须有来源句支撑

Metric 输出格式：
METRIC: 指标名称
  name: 指标名称
  value: 数值或 null
  unit: 标准单位或 null
  period: 2024A / 2025E / 2024Q1 / 2024H1 等
  period_type: actual / forecast / quarterly / half-year
  sentiment: positive / negative / neutral

【必须抽取】
- 公告主体公司，通常来自公告抬头、落款、证券简称或正文中的公司全称
- 业绩预告、年报、半年报、季报中的关键财务指标
- 原文明确出现的产品、客户、供应商

【禁止抽取】（7类噪声）：
1. 研报封面声明/免责声明/机构介绍
2. 文件路径/URL/Email/社交媒体ID
3. 风险提示/法律声明/合规提示
4. 表格行内容（包含"|"的多列数据）
5. 重复累计行、空白单元格内容
6. 指数名称/股票代码/非公司名称
7. 超长碎片（长度超过50字的实体名称）或纯符号内容

【显式陈述原则】只抽取文本中明确陈述的内容，不要推断未写明的事实。

示例：
输入：宁德时代在储能领域生产销售三元锂电池，预计2025年产能增长。
输出：
Entity: 宁德时代(Company)
Entity: 三元锂电池(Product)
Entity: 产能(Metric)
RELATES: 宁德时代 → 三元锂电池
  关系描述: "在储能领域生产销售三元锂电池产品"
  置信度: 1.0
  陈述类型: Fact
  来源: "宁德时代在储能领域生产销售三元锂电池"
METRIC: 产能
  name: 产能
  value: null
  unit: null
  period: 2025E
  period_type: forecast
  sentiment: positive

#####
{input_text}
#####
"""
```

4. **Update `RELATES_EXTRACTION_PROMPT`** — change entity type list from 7 to 3:
```python
RELATES_EXTRACTION_PROMPT = """抽取文本中的 RELATES 关系。

只输出以下格式：
RELATES: 实体A → 实体B
  关系描述: "自然语言描述，100字以内"
  置信度: 1.0 或 0.7
  陈述类型: Fact / Claim / Estimate
  来源: "原文相关句"

陈述类型: Fact=客观事实, Claim=管理层主张, Estimate=预测推测

实体类型范围：Company、Product、Metric。
置信度：1.0=直接陈述，0.7=LLM推断。禁止从免责声明、URL、联系方式、表格噪声中抽取。

示例：
RELATES: 宁德时代 → 三元锂电池
  关系描述: "在储能领域生产销售三元锂电池产品"
  置信度: 1.0
  陈述类型: Fact
  来源: "宁德时代在储能领域生产销售三元锂电池"
"""
```

5. **Update `get_extraction_prompt`** — remove V4 routing, unify all source types to V13:
```python
def get_extraction_prompt(source_type: str, section_title: str = "文档概述") -> str:
    """根据 source_type 返回对应的抽取 prompt。"""
    # 所有数据源统一使用 V1.3 prompt
    return EXTRACTION_PROMPT_V13
```

6. **Keep `ANNOUNCEMENT_SOURCE_TYPES`** list (it may be referenced elsewhere for non-prompt logic).

7. **Keep `EXTRACTION_PROMPT`** (the original 研报 prompt) — it's already V1.3 and used as fallback. But update `get_extraction_prompt` to always return `EXTRACTION_PROMPT_V13`.

8. **Delete `EXTRACTION_PROMPT_V4`** and `ANNOUNCEMENT_EXTRACTION_PROMPT` entirely.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/lwm/code/QingshuiYanTou/backend && source .venv/bin/activate && python -m pytest tests/test_v13_schema_unified.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/knowledge/extraction/rag_prompts.py backend/tests/test_v13_schema_unified.py
git commit -m "feat(prompts): unify to V1.3 Schema — merge V4 and announcement prompts into EXTRACTION_PROMPT_V13"
```

---

### Task 2: Rename _parse_*_v4 Functions in rag_extractor.py

**Files:**
- Modify: `backend/app/knowledge/extraction/rag_extractor.py`
- Test: `backend/tests/test_v13_schema_unified.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_v13_schema_unified.py`:

```python
def test_rag_extractor_no_v4_function_names():
    """rag_extractor must not have _v4 suffixed function names."""
    from app.knowledge.extraction import rag_extractor
    assert not hasattr(rag_extractor, "_parse_relates_v4")
    assert not hasattr(rag_extractor, "_parse_metrics_v4")
    assert not hasattr(rag_extractor, "_parse_chunk_output_v4")
    assert hasattr(rag_extractor, "_parse_relates")
    assert hasattr(rag_extractor, "_parse_metrics")
    assert hasattr(rag_extractor, "_parse_chunk_output")


def test_rag_extractor_valid_entity_types_is_v13():
    """VALID_ENTITY_TYPES_V2 must only contain 3 types."""
    from app.knowledge.extraction.rag_extractor import _parse_chunk_output
    # Call with empty input — just verify the module-level constant
    from app.knowledge.extraction.rag_extractor import VALID_ENTITY_TYPES
    assert VALID_ENTITY_TYPES == frozenset({"Company", "Product", "Metric"})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/lwm/code/QingshuiYanTou/backend && source .venv/bin/activate && python -m pytest tests/test_v13_schema_unified.py::test_rag_extractor_no_v4_function_names tests/test_v13_schema_unified.py::test_rag_extractor_valid_entity_types_is_v13 -v`
Expected: FAIL — `_parse_relates_v4` still exists, `VALID_ENTITY_TYPES` not defined

- [ ] **Step 3: Rename functions and update references in rag_extractor.py**

In `backend/app/knowledge/extraction/rag_extractor.py`:

1. **Update imports** — remove `ENTITY_TYPES_V4` from the import line, add `ENTITY_TYPES` if not already imported:
```python
from app.knowledge.extraction.rag_prompts import (
    TUPLE_DELIMITER, RECORD_DELIMITER, COMPLETION_DELIMITER,
    GRAPH_FIELD_SEP, ENTITY_TYPES, DEFAULT_ENTITY_TYPES,
    EXTRACTION_PROMPT, EXTRACTION_PROMPT_V13,
    CONTINUE_PROMPT, SUMMARIZE_PROMPT, get_extraction_prompt,
)
```

2. **Replace `VALID_ENTITY_TYPES_V2`** — move to module level and use `ENTITY_TYPES`:
```python
VALID_ENTITY_TYPES = frozenset(ENTITY_TYPES)
```
Then replace all references to `VALID_ENTITY_TYPES_V2` with `VALID_ENTITY_TYPES` (inside `_parse_chunk_output` function body).

3. **Rename `_parse_relates_v4` → `_parse_relates`** — function definition and all 2 call sites:
   - Definition at line ~384
   - Call in `_parse_chunk_output_v4` at line ~500

4. **Rename `_parse_metrics_v4` → `_parse_metrics`** — function definition and all 2 call sites:
   - Definition at line ~465
   - Call in `_parse_chunk_output_v4` at line ~513

5. **Rename `_parse_chunk_output_v4` → `_parse_chunk_output`** — function definition and all 4 call sites:
   - Definition at line ~497
   - Call in `_extract_single_chunk` at line ~632
   - Call in `_extract_single_chunk` at line ~644
   - Any other references

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/lwm/code/QingshuiYanTou/backend && source .venv/bin/activate && python -m pytest tests/test_v13_schema_unified.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/knowledge/extraction/rag_extractor.py backend/tests/test_v13_schema_unified.py
git commit -m "refactor(extractor): rename _parse_*_v4 → _parse_*, VALID_ENTITY_TYPES_V2 → VALID_ENTITY_TYPES"
```

---

### Task 3: Rename upsert_relates_v4 → upsert_relates in relation_service.py

**Files:**
- Modify: `backend/app/knowledge/relation_service.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_v13_schema_unified.py`:

```python
def test_relation_service_no_v4_function_names():
    """relation_service must not have upsert_relates_v4."""
    from app.knowledge import relation_service
    assert not hasattr(relation_service, "upsert_relates_v4")
    assert hasattr(relation_service, "upsert_relates")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/lwm/code/QingshuiYanTou/backend && source .venv/bin/activate && python -m pytest tests/test_v13_schema_unified.py::test_relation_service_no_v4_function_names -v`
Expected: FAIL — `upsert_relates_v4` still exists

- [ ] **Step 3: Rename function**

In `backend/app/knowledge/relation_service.py`:

1. **Rename `upsert_relates_v4` → `upsert_relates`** — the function definition at line ~779. This becomes the primary function with full parameters (stmt_type, relation_subtype, etc.).

2. **Remove the old `upsert_relates` wrapper** at lines ~751-776 — it was just a wrapper that called `upsert_relates_v4` without passing through stmt_type/relation_subtype. The renamed function IS the full version now.

3. **If any other code imported the old `upsert_relates`** (the wrapper), verify the signature is compatible. The new `upsert_relates` has the full signature with `stmt_type="Fact"`, `relation_subtype=None`, etc., so all existing callers that omitted these params will still work.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/lwm/code/QingshuiYanTou/backend && source .venv/bin/activate && python -m pytest tests/test_v13_schema_unified.py::test_relation_service_no_v4_function_names -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/knowledge/relation_service.py backend/tests/test_v13_schema_unified.py
git commit -m "refactor(relation): rename upsert_relates_v4 → upsert_relates, remove wrapper"
```

---

### Task 4: Update kg_extractor.py — Import and Call Sites

**Files:**
- Modify: `backend/app/knowledge/kg_extractor.py`

- [ ] **Step 1: Update import**

Change line ~47-49 from:
```python
from app.knowledge.relation_service import (
    upsert_relates_v4, infer_relation_type,
)
```
to:
```python
from app.knowledge.relation_service import (
    upsert_relates, infer_relation_type,
)
```

- [ ] **Step 2: Update 3 call sites**

Replace `upsert_relates_v4(` with `upsert_relates(` at all 3 locations:
- Line ~637 (in `extract_text`)
- Line ~1028 (in `extract_text_async`)
- Line ~1272 (in `extract_evidence_async`)

The arguments remain exactly the same — no signature change needed.

- [ ] **Step 3: Run existing tests to verify no breakage**

Run: `cd /home/lwm/code/QingshuiYanTou/backend && source .venv/bin/activate && python -m pytest tests/ -k "kg" -v --timeout=30`
Expected: No new failures

- [ ] **Step 4: Commit**

```bash
git add backend/app/knowledge/kg_extractor.py
git commit -m "refactor(kg_extractor): update import and calls from upsert_relates_v4 → upsert_relates"
```

---

### Task 5: Update irm_extractor.py — Import, Call Sites, Add stmt_type

**Files:**
- Modify: `backend/app/knowledge/irm_extractor.py`

- [ ] **Step 1: Update import**

Change line ~17 from:
```python
from app.knowledge.relation_service import upsert_relates_v4
```
to:
```python
from app.knowledge.relation_service import upsert_relates
```

Also add:
```python
from app.knowledge.relation_service import infer_relation_type
```

- [ ] **Step 2: Update 3 call sites**

**Call site 1** (~line 207, in `upsert_irm_product`):
```python
upsert_relates(
    company_id, node["entity_id"],
    f"互动易提及公司与产品 {name} 相关",
    source_type="irm", source_name="互动易",
    stmt_type="Fact",
    relation_subtype="produces",
)
```

**Call site 2** (~line 375, in `extract_irm_qa`, mention relation):
```python
upsert_relates(
    company_id, node["entity_id"], text_desc,
    source_type="irm", source_name=source_name,
    stmt_type="Claim",
    relation_subtype=infer_relation_type(text_desc) if text_desc else None,
)
```

**Call site 3** (~line 416-423, in `extract_irm_qa`, LLM extracted relation):
```python
_, is_new = upsert_relates(
    src, tgt, str(rel.get("description") or ""),
    weight=float(rel.get("weight") or 0.7),
    source_type="irm", source_name=source_name,
    stmt_type="Claim",
    relation_subtype=infer_relation_type(str(rel.get("description") or "")),
)
```

- [ ] **Step 3: Run tests to verify**

Run: `cd /home/lwm/code/QingshuiYanTou/backend && source .venv/bin/activate && python -m pytest tests/ -k "irm" -v --timeout=30`
Expected: No new failures

- [ ] **Step 4: Commit**

```bash
git add backend/app/knowledge/irm_extractor.py
git commit -m "refactor(irm): update import and calls, add stmt_type/relation_subtype to upsert_relates"
```

---

### Task 6: Update light_extractor.py — Prompt Reference

**Files:**
- Modify: `backend/app/knowledge/extraction/light_extractor.py`

- [ ] **Step 1: Update import**

Change the import of `ANNOUNCEMENT_EXTRACTION_PROMPT` to `EXTRACTION_PROMPT_V13`:
```python
from app.knowledge.extraction.rag_prompts import EXTRACTION_PROMPT_V13
```

- [ ] **Step 2: Update usage**

At line ~98, change:
```python
prompt = ANNOUNCEMENT_EXTRACTION_PROMPT.format(input_text=text)
```
to:
```python
prompt = EXTRACTION_PROMPT_V13.format(input_text=text)
```

- [ ] **Step 3: Run tests to verify**

Run: `cd /home/lwm/code/QingshuiYanTou/backend && source .venv/bin/activate && python -m pytest tests/test_v13_schema_unified.py -v`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add backend/app/knowledge/extraction/light_extractor.py
git commit -m "refactor(light_extractor): update prompt reference to EXTRACTION_PROMPT_V13"
```

---

### Task 7: Full Integration Test for Phase A

**Files:**
- Modify: `backend/tests/test_v13_schema_unified.py`

- [ ] **Step 1: Write integration test**

Add to `backend/tests/test_v13_schema_unified.py`:

```python
def test_no_v4_references_in_knowledge_module():
    """Scan knowledge module for any remaining _v4 or V4 references."""
    import ast
    import importlib
    from pathlib import Path

    knowledge_dir = Path(__file__).parent.parent / "app" / "knowledge"
    v4_refs = []
    for py_file in knowledge_dir.rglob("*.py"):
        try:
            source = py_file.read_text()
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.Name) and "v4" in node.id.lower():
                    v4_refs.append(f"{py_file.name}:{node.lineno} — {node.id}")
                elif isinstance(node, ast.Attribute) and "v4" in node.attr.lower():
                    v4_refs.append(f"{py_file.name}:{node.lineno} — {node.attr}")
        except SyntaxError:
            pass

    # Allow _parse_chunk_output_v4 in comments/strings only, not as function names
    # Filter to only function/class definitions
    code_v4_refs = [r for r in v4_refs if not any(
        skip in r for skip in ["test_", "__pycache__"]
    )]
    assert len(code_v4_refs) == 0, f"V4 references found: {code_v4_refs}"


def test_entity_types_consistency():
    """All entity type definitions must agree on 3 types."""
    from app.knowledge.extraction.rag_prompts import ENTITY_TYPES, DEFAULT_ENTITY_TYPES
    from app.knowledge.entity_service import ENTITY_TYPES as SERVICE_ENTITY_TYPES

    assert ENTITY_TYPES == ["Company", "Product", "Metric"]
    assert DEFAULT_ENTITY_TYPES == ENTITY_TYPES
    assert SERVICE_ENTITY_TYPES == frozenset({"Company", "Product", "Metric"})
```

- [ ] **Step 2: Run full test suite for Phase A**

Run: `cd /home/lwm/code/QingshuiYanTou/backend && source .venv/bin/activate && python -m pytest tests/test_v13_schema_unified.py -v`
Expected: All PASS

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_v13_schema_unified.py
git commit -m "test: add V1.3 schema integration tests — no V4 remnants, entity type consistency"
```

---

## Phase B: resolve/expand Query Primitives

### Task 8: Create resolve Tool

**Files:**
- Create: `backend/app/reasoning/tools/knowledge/graph_navigator.py`
- Create: `backend/tests/test_graph_navigator.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_graph_navigator.py`:

```python
"""Tests for resolve and expand graph navigation tools."""
import pytest
from unittest.mock import patch, MagicMock


class TestResolve:
    """Tests for the resolve tool."""

    def test_resolve_returns_entity_on_exact_match(self):
        """resolve with exact entity name returns the entity."""
        from app.reasoning.tools.knowledge.graph_navigator import resolve

        mock_result = [{
            "id": "C_宁德时代",
            "name": "宁德时代",
            "type": "Company",
            "score": 1.0,
        }]
        with patch("app.reasoning.tools.knowledge.graph_navigator._search_entity_by_name", return_value=mock_result):
            result = resolve("宁德时代")
        assert result is not None
        assert result["entity_id"] == "C_宁德时代"
        assert result["type"] == "Company"

    def test_resolve_returns_none_on_no_match(self):
        """resolve with non-existent entity returns None."""
        from app.reasoning.tools.knowledge.graph_navigator import resolve

        with patch("app.reasoning.tools.knowledge.graph_navigator._search_entity_by_name", return_value=[]):
            result = resolve("不存在的公司")
        assert result is None

    def test_resolve_with_entity_type_filter(self):
        """resolve with entity_type filter only searches that type."""
        from app.reasoning.tools.knowledge.graph_navigator import resolve

        mock_result = [{
            "id": "P_电源模块",
            "name": "电源模块",
            "type": "Product",
            "score": 0.95,
        }]
        with patch("app.reasoning.tools.knowledge.graph_navigator._search_entity_by_name", return_value=mock_result) as mock_search:
            result = resolve("电源模块", entity_type="Product")
            mock_search.assert_called_once_with("电源模块", "Product")
        assert result["type"] == "Product"

    def test_resolve_normalizes_name(self):
        """resolve normalizes full-width characters and common aliases."""
        from app.reasoning.tools.knowledge.graph_navigator import _normalize_query

        assert _normalize_query("宁德时代") == "宁德时代"
        assert _normalize_query("　宁德时代　") == "宁德时代"  # full-width spaces
        assert _normalize_query("Ａ股") == "A股"  # full-width to half-width
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/lwm/code/QingshuiYanTou/backend && source .venv/bin/activate && python -m pytest tests/test_graph_navigator.py::TestResolve -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement resolve tool**

Create `backend/app/reasoning/tools/knowledge/graph_navigator.py`:

```python
"""
Graph navigation tools: resolve and expand.

resolve — anchor natural language query to a graph entity.
expand  — declarative controlled subgraph expansion by select fields + filters.
"""
from __future__ import annotations

import unicodedata
from typing import Any

from langchain_core.tools import tool

from app.knowledge.entity_id import normalize_name


# ── Helpers ──────────────────────────────────────────────────────────────


def _normalize_query(query: str) -> str:
    """Normalize user query: strip, full-width → half-width, collapse whitespace."""
    # Full-width space → normal space
    text = query.replace("　", " ")
    # Full-width ASCII → half-width
    text = unicodedata.normalize("NFKC", text)
    # Strip and collapse whitespace
    text = " ".join(text.strip().split())
    return text


def _search_entity_by_name(query: str, entity_type: str | None = None) -> list[dict]:
    """Search Neo4j for entities matching the query.

    Strategy:
    1. Exact match on normalized name (via entity_id prefix)
    2. Fuzzy match via CONTAINS on name
    3. Vector semantic search (via Qdrant) as fallback

    Returns list of dicts with keys: id, name, type, score.
    """
    from app.reasoning.tools.knowledge.neo4j.neo4j import run

    normalized = _normalize_query(query)
    results: list[dict] = []

    # Strategy 1: Exact match via entity_id prefix
    # Try each entity type prefix
    type_prefixes = {"Company": "C_", "Product": "P_", "Metric": "M_"}
    if entity_type:
        type_prefixes = {entity_type: type_prefixes[entity_type]}

    for etype, prefix in type_prefixes.items():
        candidate_id = f"{prefix}{normalize_name(normalized)}"
        cypher = "MATCH (e:Entity {id: $eid}) RETURN e.id AS id, e.name AS name, e.type AS type"
        rows = run(cypher, {"eid": candidate_id})
        for row in rows:
            results.append({
                "entity_id": row["id"],
                "name": row["name"],
                "type": row["type"],
                "score": 1.0,
            })

    if results:
        return results

    # Strategy 2: CONTAINS match on name
    cypher = "MATCH (e:Entity) WHERE e.name CONTAINS $name"
    params: dict[str, Any] = {"name": normalized}
    if entity_type:
        cypher += " AND e.type = $etype"
        params["etype"] = entity_type
    cypher += " RETURN e.id AS id, e.name AS name, e.type AS type LIMIT 10"
    rows = run(cypher, params)
    for row in rows:
        results.append({
            "entity_id": row["id"],
            "name": row["name"],
            "type": row["type"],
            "score": 0.9 if row["name"] == normalized else 0.7,
        })

    # Sort by score descending
    results.sort(key=lambda r: r["score"], reverse=True)
    return results


# ── resolve tool ─────────────────────────────────────────────────────────


@tool("resolve")
def resolve(query: str, entity_type: str | None = None) -> dict | None:
    """将自然语言查询锚定到图谱中的具体实体。

    Args:
        query: 实体名称（如"宁德时代"、"电源模块"）
        entity_type: 可选实体类型过滤 ("Company"|"Product"|"Metric")

    Returns:
        锚定的实体 {entity_id, name, type, score}，未找到返回 null
    """
    candidates = _search_entity_by_name(query, entity_type)
    if not candidates:
        return None
    # Return best match
    best = candidates[0]
    return {
        "entity_id": best["entity_id"],
        "name": best["name"],
        "type": best["type"],
        "score": best["score"],
    ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/lwm/code/QingshuiYanTou/backend && source .venv/bin/activate && python -m pytest tests/test_graph_navigator.py::TestResolve -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/reasoning/tools/knowledge/graph_navigator.py backend/tests/test_graph_navigator.py
git commit -m "feat(tools): add resolve tool — natural language → graph entity anchoring"
```

---

### Task 9: Create expand Tool — Core Framework

**Files:**
- Modify: `backend/app/reasoning/tools/knowledge/graph_navigator.py`
- Modify: `backend/tests/test_graph_navigator.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_graph_navigator.py`:

```python
class TestExpand:
    """Tests for the expand tool."""

    def test_expand_properties(self):
        """expand with select=['properties'] returns entity attributes."""
        from app.reasoning.tools.knowledge.graph_navigator import expand

        mock_entity = {
            "id": "C_新雷能", "name": "新雷能", "type": "Company",
            "description": "北京新雷能科技股份有限公司", "industry": "电子",
        }
        with patch("app.reasoning.tools.knowledge.graph_navigator._fetch_entity", return_value=mock_entity):
            result = expand("C_新雷能", select=["properties"])
        assert result["entity"]["name"] == "新雷能"
        assert result["entity"]["type"] == "Company"
        assert "properties" in result

    def test_expand_relations_with_filter(self):
        """expand with select=['relations'] and filter applies stmt_type filter."""
        from app.reasoning.tools.knowledge.graph_navigator import expand

        mock_rels = [
            {"from": "C_新雷能", "to": "M_营收", "text": "营收120亿", "stmt_type": "Fact", "weight": 1.0},
            {"from": "C_新雷能", "to": "M_营收", "text": "预计增长30%", "stmt_type": "Estimate", "weight": 0.7},
        ]
        with patch("app.reasoning.tools.knowledge.graph_navigator._fetch_relations", return_value=mock_rels):
            result = expand("C_新雷能", select=["relations"],
                          filter={"stmt_types": ["Fact"]})
        assert len(result["relations"]) == 1
        assert result["relations"][0]["stmt_type"] == "Fact"

    def test_expand_metrics(self):
        """expand with select=['metrics'] returns metric nodes with stmt_type aggregation."""
        from app.reasoning.tools.knowledge.graph_navigator import expand

        mock_metrics = [
            {"entity_id": "M_营收", "name": "营收", "type": "Metric",
             "stmt_type": "Fact", "text": "2024年营收120亿"},
            {"entity_id": "M_营收", "name": "营收", "type": "Metric",
             "stmt_type": "Estimate", "text": "预计2025年营收增长30%"},
        ]
        with patch("app.reasoning.tools.knowledge.graph_navigator._fetch_typed_neighbors", return_value=mock_metrics):
            result = expand("C_新雷能", select=["metrics"])
        assert "metrics" in result
        # Metrics should be aggregated by entity
        assert "M_营收" in result["metrics"]
        assert len(result["metrics"]["M_营收"]["facts"]) == 1
        assert len(result["metrics"]["M_营收"]["estimates"]) == 1

    def test_expand_peers(self):
        """expand with select=['peers'] returns companies sharing products."""
        from app.reasoning.tools.knowledge.graph_navigator import expand

        mock_peers = [
            {"entity_id": "C_英维克", "name": "英维克", "type": "Company",
             "shared_count": 2, "shared_products": ["精密温控", "电源模块"]},
        ]
        with patch("app.reasoning.tools.knowledge.graph_navigator._fetch_peers", return_value=mock_peers):
            result = expand("C_新雷能", select=["peers"])
        assert len(result["peers"]) == 1
        assert result["peers"][0]["name"] == "英维克"

    def test_expand_upstream(self):
        """expand with select=['upstream'] returns upstream chain path."""
        from app.reasoning.tools.knowledge.graph_navigator import expand

        mock_paths = [
            {"nodes": ["C_新雷能", "P_电源模块", "P_铜箔"],
             "edges": [
                 {"from": "C_新雷能", "to": "P_电源模块", "text": "生产", "subtype": "produces"},
                 {"from": "P_电源模块", "to": "P_铜箔", "text": "原材料", "subtype": "supplied_by"},
             ]},
        ]
        with patch("app.reasoning.tools.knowledge.graph_navigator._fetch_chain", return_value=mock_paths):
            result = expand("C_新雷能", select=["upstream"],
                          filter={"direction": "upstream", "depth": 2})
        assert "paths" in result
        assert len(result["paths"]) == 1

    def test_expand_divergence(self):
        """expand with select=['divergence'] returns Fact vs Estimate comparison."""
        from app.reasoning.tools.knowledge.graph_navigator import expand

        mock_divergence = [
            {
                "metric_id": "M_营收", "metric_name": "营收",
                "facts": [{"text": "2024年营收120亿", "period": "2024A"}],
                "estimates": [{"text": "预计2025年营收150亿", "period": "2025E"}],
                "claims": [],
                "gap": {"fact_value": 120, "estimate_value": 150, "gap_pct": "+25%", "direction": "bullish"},
            },
        ]
        with patch("app.reasoning.tools.knowledge.graph_navigator._fetch_divergence", return_value=mock_divergence):
            result = expand("C_新雷能", select=["divergence"])
        assert "divergences" in result
        assert len(result["divergences"]) == 1
        assert result["divergences"][0]["gap"]["direction"] == "bullish"

    def test_expand_combines_multiple_selects(self):
        """expand with multiple select fields combines results."""
        from app.reasoning.tools.knowledge.graph_navigator import expand

        mock_entity = {"id": "C_新雷能", "name": "新雷能", "type": "Company"}
        mock_metrics = [
            {"entity_id": "M_营收", "name": "营收", "type": "Metric",
             "stmt_type": "Fact", "text": "营收120亿"},
        ]
        with patch("app.reasoning.tools.knowledge.graph_navigator._fetch_entity", return_value=mock_entity), \
             patch("app.reasoning.tools.knowledge.graph_navigator._fetch_typed_neighbors", return_value=mock_metrics):
            result = expand("C_新雷能", select=["properties", "metrics"])
        assert "entity" in result
        assert "metrics" in result
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/lwm/code/QingshuiYanTou/backend && source .venv/bin/activate && python -m pytest tests/test_graph_navigator.py::TestExpand -v`
Expected: FAIL — `expand` not defined

- [ ] **Step 3: Implement expand tool**

Add to `backend/app/reasoning/tools/knowledge/graph_navigator.py`:

```python
# ── expand internals ─────────────────────────────────────────────────────

# Valid select fields
_SELECT_FIELDS = frozenset({
    "properties", "relations", "metrics", "products",
    "companies", "upstream", "downstream", "peers", "divergence",
})

# Upstream relation_subtypes (entity is the receiver/buyer)
_UPSTREAM_SUBTYPES = {"supplied_by", "provided_by", "purchased_from", "sourced_from"}
# Downstream relation_subtypes (entity is the provider/seller)
_DOWNSTREAM_SUBTYPES = {"supplies_to", "provides_to", "sells_to", "produces"}


def _fetch_entity(entity_id: str) -> dict | None:
    """Fetch entity node properties from Neo4j."""
    from app.reasoning.tools.knowledge.neo4j.neo4j import run

    cypher = "MATCH (e:Entity {id: $eid}) RETURN e"
    rows = run(cypher, {"eid": entity_id})
    if not rows:
        return None
    return dict(rows[0]["e"])


def _fetch_relations(entity_id: str, filter_: dict | None = None) -> list[dict]:
    """Fetch RELATES edges connected to entity, with optional filters."""
    from app.reasoning.tools.knowledge.neo4j.neo4j import run

    conditions = []
    params: dict[str, Any] = {"eid": entity_id}

    if filter_:
        if filter_.get("stmt_types"):
            params["stmt_types"] = filter_["stmt_types"]
            conditions.append("r.stmt_type IN $stmt_types")
        if filter_.get("relation_subtypes"):
            params["subtypes"] = filter_["relation_subtypes"]
            conditions.append("r.relation_subtype IN $subtypes")

    where = ""
    if conditions:
        where = " AND " + " AND ".join(conditions)

    cypher = f"""
    MATCH (e:Entity {{id: $eid}})-[r:RELATES]-(t:Entity)
    WHERE true{where}
    RETURN e.id AS from_id, t.id AS to_id, r.text AS text,
           r.weight AS weight, r.stmt_type AS stmt_type,
           r.relation_subtype AS relation_subtype, r.source AS source,
           startNode(r).id AS start_id
    ORDER BY r.weight DESC
    LIMIT $limit
    """
    params["limit"] = (filter_ or {}).get("limit", 20)
    rows = run(cypher, params)

    results = []
    for row in rows:
        # Determine direction: if start_id == entity_id, it's outgoing
        direction = "outgoing" if row["start_id"] == entity_id else "incoming"
        results.append({
            "from": row["from_id"],
            "to": row["to_id"],
            "text": row["text"],
            "weight": row["weight"],
            "stmt_type": row["stmt_type"],
            "relation_subtype": row["relation_subtype"],
            "source": row["source"],
            "direction": direction,
        })
    return results


def _fetch_typed_neighbors(entity_id: str, neighbor_type: str,
                           filter_: dict | None = None) -> list[dict]:
    """Fetch neighbors of a specific entity type with their RELATES edge info."""
    from app.reasoning.tools.knowledge.neo4j.neo4j import run

    conditions = ["t.type = $ntype"]
    params: dict[str, Any] = {"eid": entity_id, "ntype": neighbor_type}

    if filter_ and filter_.get("stmt_types"):
        params["stmt_types"] = filter_["stmt_types"]
        conditions.append("r.stmt_type IN $stmt_types")

    where = " AND ".join(conditions)
    cypher = f"""
    MATCH (e:Entity {{id: $eid}})-[r:RELATES]-(t:Entity)
    WHERE {where}
    RETURN t.id AS entity_id, t.name AS name, t.type AS type,
           r.text AS text, r.stmt_type AS stmt_type,
           r.weight AS weight, r.relation_subtype AS relation_subtype
    ORDER BY r.weight DESC
    LIMIT $limit
    """
    params["limit"] = (filter_ or {}).get("limit", 20)
    rows = run(cypher, params)
    return [dict(r) for r in rows]


def _fetch_peers(entity_id: str, limit: int = 10) -> list[dict]:
    """Find peer entities that share common neighbors (products)."""
    from app.reasoning.tools.knowledge.neo4j.neo4j import run

    cypher = """
    MATCH (e:Entity {id: $eid})-[r1:RELATES]-(n:Entity)<-[r2:RELATES]-(peer:Entity)
    WHERE peer <> e AND peer.type = 'Company'
    WITH peer, collect(DISTINCT n.name) AS shared_products, count(DISTINCT n) AS shared_count
    ORDER BY shared_count DESC
    LIMIT $limit
    RETURN peer.id AS entity_id, peer.name AS name, peer.type AS type,
           shared_count, shared_products
    """
    rows = run(cypher, {"eid": entity_id, "limit": limit})
    return [dict(r) for r in rows]


def _fetch_chain(entity_id: str, direction: str, depth: int = 3,
                 limit: int = 10) -> list[dict]:
    """Fetch upstream or downstream chain paths via directional relation_subtypes."""
    from app.reasoning.tools.knowledge.neo4j.neo4j import run

    if direction == "upstream":
        subtypes = list(_UPSTREAM_SUBTYPES)
    elif direction == "downstream":
        subtypes = list(_DOWNSTREAM_SUBTYPES)
    else:
        subtypes = list(_UPSTREAM_SUBTYPES | _DOWNSTREAM_SUBTYPES)

    cypher = """
    MATCH path = (e:Entity {id: $eid})-[r:RELATES*1..%d]-(other:Entity)
    WHERE ALL(rel IN r WHERE rel.relation_subtype IN $subtypes)
    RETURN [node IN nodes(path) | node.id] AS node_ids,
           [node IN nodes(path) | node.name] AS node_names,
           [rel IN relationships(path) | {text: rel.text, subtype: rel.relation_subtype}] AS edges
    LIMIT $limit
    """ % depth
    rows = run(cypher, {"eid": entity_id, "subtypes": subtypes, "limit": limit})
    paths = []
    for row in rows:
        paths.append({
            "nodes": row["node_names"],
            "edges": row["edges"],
        })
    return paths


def _fetch_divergence(entity_id: str, metric_name: str | None = None) -> list[dict]:
    """Find Fact vs Estimate divergences on metrics connected to entity."""
    from app.reasoning.tools.knowledge.neo4j.neo4j import run

    conditions = ["t.type = 'Metric'"]
    params: dict[str, Any] = {"eid": entity_id}

    if metric_name:
        conditions.append("t.name CONTAINS $mname")
        params["mname"] = metric_name

    where = " AND ".join(conditions)

    # Get all metric neighbors with their stmt_types
    cypher = f"""
    MATCH (e:Entity {{id: $eid}})-[r:RELATES]-(t:Entity)
    WHERE {where}
    RETURN t.id AS metric_id, t.name AS metric_name,
           collect({{text: r.text, stmt_type: r.stmt_type, source: r.source}}) AS statements
    """
    rows = run(cypher, params)

    divergences = []
    for row in rows:
        stmts = row["statements"]
        facts = [s for s in stmts if s["stmt_type"] == "Fact"]
        estimates = [s for s in stmts if s["stmt_type"] == "Estimate"]
        claims = [s for s in stmts if s["stmt_type"] == "Claim"]

        # Only report divergence if there's both Fact and Estimate
        if facts and estimates:
            divergences.append({
                "metric_id": row["metric_id"],
                "metric_name": row["metric_name"],
                "facts": facts,
                "estimates": estimates,
                "claims": claims,
                "gap": _compute_gap(facts, estimates),
            })

    return divergences


def _compute_gap(facts: list[dict], estimates: list[dict]) -> dict | None:
    """Attempt to compute numeric gap between Fact and Estimate values."""
    import re

    def _extract_value(text: str) -> float | None:
        match = re.search(r"([\d.]+)\s*(亿|万|%)", text)
        if match:
            return float(match.group(1))
        return None

    fact_val = _extract_value(facts[0]["text"]) if facts else None
    est_val = _extract_value(estimates[0]["text"]) if estimates else None

    if fact_val is not None and est_val is not None and fact_val != 0:
        gap_pct = ((est_val - fact_val) / fact_val) * 100
        direction = "bullish" if gap_pct > 0 else "bearish"
        return {
            "fact_value": fact_val,
            "estimate_value": est_val,
            "gap_pct": f"{gap_pct:+.0f}%",
            "direction": direction,
        }
    return None


def _aggregate_metrics(raw_metrics: list[dict]) -> dict[str, dict]:
    """Aggregate metric neighbors by entity_id, grouping by stmt_type."""
    aggregated: dict[str, dict] = {}
    for m in raw_metrics:
        mid = m["entity_id"]
        if mid not in aggregated:
            aggregated[mid] = {
                "name": m["name"],
                "facts": [],
                "claims": [],
                "estimates": [],
            }
        entry = {"text": m["text"], "weight": m["weight"]}
        stmt = m.get("stmt_type", "Fact")
        if stmt == "Fact":
            aggregated[mid]["facts"].append(entry)
        elif stmt == "Claim":
            aggregated[mid]["claims"].append(entry)
        elif stmt == "Estimate":
            aggregated[mid]["estimates"].append(entry)
    return aggregated


# ── expand tool ──────────────────────────────────────────────────────────


@tool("expand")
def expand(entity_id: str, select: list[str],
           filter: dict | None = None) -> dict:
    """受控展开图谱子图，按需选择查询字段和过滤条件。

    Args:
        entity_id: 已锚定的实体 ID（如 resolve 返回的 entity_id）
        select: 要获取的字段列表，可选值:
            properties, relations, metrics, products, companies,
            upstream, downstream, peers, divergence
        filter: 可选过滤条件:
            direction: "upstream"|"downstream"|"both"（产业链方向）
            relation_subtypes: 按关系子类型过滤
            stmt_types: 按陈述类型过滤 ["Fact","Claim","Estimate"]
            dimension: 按业务维度过滤
            depth: 遍历深度（默认1，最大5）
            limit: 返回数量限制（默认20）

    Returns:
        按 select 字段组合的子图结果
    """
    # Validate select fields
    invalid = set(select) - _SELECT_FIELDS
    if invalid:
        return {"error": f"Invalid select fields: {invalid}. Valid: {_SELECT_FIELDS}"}

    filter_ = filter or {}
    result: dict[str, Any] = {}

    for field in select:
        if field == "properties":
            entity = _fetch_entity(entity_id)
            if entity:
                result["entity"] = entity

        elif field == "relations":
            result["relations"] = _fetch_relations(entity_id, filter_)

        elif field == "metrics":
            raw = _fetch_typed_neighbors(entity_id, "Metric", filter_)
            result["metrics"] = _aggregate_metrics(raw)

        elif field == "products":
            raw = _fetch_typed_neighbors(entity_id, "Product", filter_)
            result["products"] = [
                {"entity_id": r["entity_id"], "name": r["name"],
                 "text": r["text"], "stmt_type": r["stmt_type"]}
                for r in raw
            ]

        elif field == "companies":
            raw = _fetch_typed_neighbors(entity_id, "Company", filter_)
            result["companies"] = [
                {"entity_id": r["entity_id"], "name": r["name"],
                 "text": r["text"], "stmt_type": r["stmt_type"]}
                for r in raw
            ]

        elif field == "upstream":
            direction = filter_.get("direction", "upstream")
            depth = min(filter_.get("depth", 2), 5)
            result["paths"] = _fetch_chain(entity_id, direction, depth)

        elif field == "downstream":
            direction = filter_.get("direction", "downstream")
            depth = min(filter_.get("depth", 2), 5)
            result["paths"] = _fetch_chain(entity_id, direction, depth)

        elif field == "peers":
            limit = filter_.get("limit", 10)
            result["peers"] = _fetch_peers(entity_id, limit)

        elif field == "divergence":
            result["divergences"] = _fetch_divergence(entity_id)

    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/lwm/code/QingshuiYanTou/backend && source .venv/bin/activate && python -m pytest tests/test_graph_navigator.py::TestExpand -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/reasoning/tools/knowledge/graph_navigator.py backend/tests/test_graph_navigator.py
git commit -m "feat(tools): add expand tool — declarative subgraph expansion with select + filter"
```

---

### Task 10: Export resolve/expand from knowledge tools __init__.py

**Files:**
- Modify: `backend/app/reasoning/tools/knowledge/__init__.py`

- [ ] **Step 1: Update exports**

Add to `backend/app/reasoning/tools/knowledge/__init__.py`:

```python
from app.reasoning.tools.knowledge.graph_navigator import resolve, expand
```

Ensure these are included in `__all__` if the file uses it.

- [ ] **Step 2: Verify import works**

Run: `cd /home/lwm/code/QingshuiYanTou/backend && source .venv/bin/activate && python -c "from app.reasoning.tools.knowledge import resolve, expand; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/app/reasoning/tools/knowledge/__init__.py
git commit -m "feat(tools): export resolve and expand from knowledge tools package"
```

---

### Task 11: Update Agent System Prompt with resolve/expand Instructions

**Files:**
- Modify: `backend/app/reasoning/prompts/lead_system_prompt.py` (or equivalent agent prompt file)

- [ ] **Step 1: Find the agent system prompt file**

Search for the file that defines the agent's system prompt containing the 4-layer knowledge navigation instructions (added in commit `847f663`).

- [ ] **Step 2: Update the knowledge navigation section**

Replace the existing 4-layer navigation instructions with resolve/expand based instructions. The key change: instead of listing individual tools per layer, teach the Agent the `resolve → expand` pattern:

```
【知识图谱查询】
使用 resolve + expand 进行受控图谱导航：

1. resolve("实体名") → 锚定实体，返回 entity_id
2. expand(entity_id, select=[...], filter={...}) → 受控展开子图

select 字段说明：
- properties: 实体属性（名称、类型、行业等）
- metrics: 关联指标（含 Fact/Claim/Estimate 聚合）
- products: 关联产品
- companies: 关联公司
- relations: 关联 RELATES 边（可用 filter 过滤）
- upstream/downstream: 产业链上下游路径
- peers: 竞争对手（共享产品的公司）
- divergence: 预期差视图（Fact vs Estimate 对比）

典型查询模式：
- 个股分析：resolve → expand(select=["properties","metrics"])
- 产业链分析：resolve → expand(select=["upstream"], filter={direction:"upstream",depth:3})
- 竞争分析：resolve → expand(select=["peers","metrics"])
- 预期差挖掘：resolve → expand(select=["divergence","metrics"])
- 证据追溯：fetch_evidence(evidence_id) → L1 原文

stmt_type 可信度：
- Fact: 直接采信
- Claim: 需交叉验证
- Estimate: 标注为预测
```

- [ ] **Step 3: Verify prompt renders correctly**

Run: `cd /home/lwm/code/QingshuiYanTou/backend && source .venv/bin/activate && python -c "from app.reasoning.prompts.lead_system_prompt import get_system_prompt; p = get_system_prompt(); assert 'resolve' in p; assert 'expand' in p; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add backend/app/reasoning/prompts/lead_system_prompt.py
git commit -m "feat(prompt): update agent system prompt with resolve/expand navigation pattern"
```

---

### Task 12: End-to-End Integration Test

**Files:**
- Create: `backend/tests/test_graph_navigator_integration.py`

- [ ] **Step 1: Write integration test**

Create `backend/tests/test_graph_navigator_integration.py`:

```python
"""Integration tests for resolve + expand graph navigation.

These tests require a running Neo4j instance with test data.
They are marked with @pytest.mark.integration and skipped by default.
"""
import pytest

pytestmark = pytest.mark.integration


@pytest.fixture
def ensure_test_data():
    """Ensure test entities exist in Neo4j. Skip if not available."""
    from app.reasoning.tools.knowledge.neo4j.neo4j import run

    rows = run("MATCH (e:Entity {id: 'C_新雷能'}) RETURN e.id AS id LIMIT 1")
    if not rows:
        pytest.skip("Test entity C_新雷能 not found in Neo4j")


class TestResolveIntegration:

    def test_resolve_company(self, ensure_test_data):
        from app.reasoning.tools.knowledge.graph_navigator import resolve
        result = resolve("新雷能")
        if result is None:
            pytest.skip("新雷能 not found in graph")
        assert result["type"] == "Company"
        assert result["entity_id"].startswith("C_")

    def test_resolve_nonexistent(self, ensure_test_data):
        from app.reasoning.tools.knowledge.graph_navigator import resolve
        result = resolve("绝对不存在的公司XYZ123")
        assert result is None


class TestExpandIntegration:

    def test_expand_properties(self, ensure_test_data):
        from app.reasoning.tools.knowledge.graph_navigator import resolve, expand
        entity = resolve("新雷能")
        if entity is None:
            pytest.skip("新雷能 not found")
        result = expand(entity["entity_id"], select=["properties"])
        assert "entity" in result
        assert result["entity"]["name"] == "新雷能"

    def test_expand_metrics(self, ensure_test_data):
        from app.reasoning.tools.knowledge.graph_navigator import resolve, expand
        entity = resolve("新雷能")
        if entity is None:
            pytest.skip("新雷能 not found")
        result = expand(entity["entity_id"], select=["metrics"])
        assert "metrics" in result

    def test_expand_peers(self, ensure_test_data):
        from app.reasoning.tools.knowledge.graph_navigator import resolve, expand
        entity = resolve("新雷能")
        if entity is None:
            pytest.skip("新雷能 not found")
        result = expand(entity["entity_id"], select=["peers"])
        assert "peers" in result

    def test_expand_divergence(self, ensure_test_data):
        from app.reasoning.tools.knowledge.graph_navigator import resolve, expand
        entity = resolve("新雷能")
        if entity is None:
            pytest.skip("新雷能 not found")
        result = expand(entity["entity_id"], select=["divergence"])
        assert "divergences" in result
```

- [ ] **Step 2: Run unit tests only (no Neo4j required)**

Run: `cd /home/lwm/code/QingshuiYanTou/backend && source .venv/bin/activate && python -m pytest tests/test_graph_navigator.py tests/test_v13_schema_unified.py -v`
Expected: All PASS

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_graph_navigator_integration.py
git commit -m "test: add integration tests for resolve + expand graph navigation"
```

---

## Summary

| Task | Phase | Description | Est. Steps |
|------|-------|-------------|------------|
| 1 | A | Unify rag_prompts.py — V1.3 prompt | 5 |
| 2 | A | Rename _parse_*_v4 in rag_extractor.py | 5 |
| 3 | A | Rename upsert_relates_v4 in relation_service.py | 5 |
| 4 | A | Update kg_extractor.py imports & calls | 4 |
| 5 | A | Update irm_extractor.py imports & calls | 4 |
| 6 | A | Update light_extractor.py prompt ref | 4 |
| 7 | A | Integration test for Phase A | 3 |
| 8 | B | Create resolve tool | 5 |
| 9 | B | Create expand tool | 5 |
| 10 | B | Export from __init__.py | 3 |
| 11 | B | Update Agent system prompt | 4 |
| 12 | B | End-to-end integration test | 3 |
| **Total** | | | **50 steps** |
