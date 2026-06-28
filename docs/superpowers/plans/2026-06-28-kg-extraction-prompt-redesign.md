# KG Extraction Prompt Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace text-based KG extraction (3 regex parsers + gleaning) with single-pass JSON output + Pydantic validation + generic name retry.

**Architecture:** LLM outputs `{"entities": [...], "relations": [...]}` JSON, validated by Pydantic, mapped to downstream `entity_name`/`entity_type`/`src_id`/`tgt_id` fields. Generic names ("公司"/"本行") trigger a full retry with augmented prompt.

**Tech Stack:** Python 3.11+, Pydantic v2, asyncio

**Spec:** `docs/superpowers/specs/2026-06-28-kg-extraction-prompt-redesign.md`

## Global Constraints

- All downstream consumer field names unchanged: `entity_name`, `entity_type`, `description`, `src_id`, `tgt_id`, `weight`, `stmt_type`, `metric` (dict)
- `extract_async(text, source_type, max_tokens)` signature unchanged
- `light_extractor.py` must continue to work (imports may change)
- No new dependencies beyond stdlib + Pydantic (already in project)

---

## File Structure

| File | Change | Responsibility |
|------|--------|---------------|
| `backend/app/knowledge/extraction/rag_prompts.py` | Rewrite | New JSON-output prompt + removed old prompts |
| `backend/app/knowledge/extraction/rag_extractor.py` | Major refactor | Pydantic models, JSON parsing, generic name detection, field mapping, remove old parsers/gleaning |
| `backend/app/knowledge/extraction/light_extractor.py` | Update imports | Adapt to new parser function signatures |
| `backend/scripts/test_new_prompt.py` | Update | Adapt to new output format |

---

### Task 1: Rewrite Prompt Template

**Files:**
- Modify: `backend/app/knowledge/extraction/rag_prompts.py` (entire file)

**Interfaces:**
- Consumes: nothing
- Produces: `EXTRACTION_PROMPT` string, `get_extraction_prompt(source_type, section_title) -> str`, `GENERIC_NAME_RETRY_PROMPT` string

- [ ] **Step 1: Read current file**

Read `backend/app/knowledge/extraction/rag_prompts.py`.

- [ ] **Step 2: Write new content**

Replace entire file with:

```python
"""
KG 抽取提示词模板 — JSON 输出版 (V2 Schema)
"""

from __future__ import annotations

# ── Prompt 模板（V2 — JSON 输出）─────────────────────────────────────────────

EXTRACTION_PROMPT = """你是一名专业的投资研究知识图谱抽取专家。

【实体类型】
- Company：公司（上市公司、子公司、重要客户、供应商、竞争对手、合作伙伴）
- Product：产品、材料、设备、服务、技术系统（如智能座舱、半固态电池）
- Metric：量化指标，必须包含数字+单位（如"营收120亿元"、"毛利率32%"）

【禁止行为】
- 使用"公司""本行""本公司""本集团""本企业"等泛称代替确切实体名称
- 输出白名单以外的实体类型
- 抽取页眉页脚、免责声明、URL、表格行、无意义的单字或碎片

【输出格式】
返回严格合法的 JSON 对象，格式如下：

{
  "entities": [
    {"name": "<实体名称>", "type": "Company|Product|Metric"}
  ],
  "relations": [
    {
      "entity1": "<主体实体名称>",
      "entity2": "<客体实体名称>",
      "description": "<关系描述，保留时间/方向/状态，100字以内>",
      "confidence": 1.0,
      "stmt_type": "Fact|Claim|Estimate",
      "source": "<原文相关句>",
      "metric_value": null,
      "metric_unit": null,
      "metric_period": null,
      "metric_period_type": null,
      "metric_sentiment": null
    }
  ]
}

【metric 字段说明】
- 仅当 entity2 类型为 Metric 时填写 metric_* 字段
- metric_period 格式：2024A(实际年), 2025E(预测年), 2024Q1(季度), 2024H1(半年度)
- metric_period_type: actual(已实现), forecast(预测), quarterly(季度), half-year(半年度)
- metric_sentiment: positive(正面), negative(负面), neutral(中性)

【关系规则】
- entity1 和 entity2 必须引用 entities 中声明的 name
- 同一对 (entity1, entity2) 如有多个不同事实，合并到一条关系中描述
- 只抽取文本中明确陈述的内容，不要推断未写明的事实

【陈述类型】
- Fact: 原文明确陈述的客观事实（如"2024年营收120亿元"）
- Claim: 公司/管理层的主张（如"管理层表示订单饱满"）
- Estimate: 预测、推测（如"预计2025年产能翻倍"）

【置信度规则】
- 1.0: 原文直接陈述
- 0.7: 基于上下文轻度推断，必须有来源句支撑

#####
{input_text}
#####
"""

GENERIC_NAME_RETRY_PROMPT = """【重要】你之前的输出中使用了"公司""本行"等模糊指代。
请重新抽取，必须从文本中提取确切的公司全称或简称。

例如"公司"应替换为文本中出现的实际名称（如"华域汽车""江苏银行"），
而不是使用"公司""本行"等泛称。

再次强调——禁止使用"公司""本行""本公司""本集团""本企业""该企业"等模糊指代。

{input_text}
"""

# ── 投资研究专用实体类型（3类）────────────────────────────────────────────

ENTITY_TYPES = ["Company", "Product", "Metric"]
DEFAULT_ENTITY_TYPES = ENTITY_TYPES


def get_extraction_prompt(source_type: str, section_title: str = "文档概述") -> str:
    """返回 KG 抽取 prompt。所有数据源统一使用 V2 JSON prompt。"""
    return EXTRACTION_PROMPT
```

- [ ] **Step 3: Verify**

Check the file syntax: `python -c "import ast; ast.parse(open('backend/app/knowledge/extraction/rag_prompts.py').read())"`

- [ ] **Step 4: Commit**

```bash
git add backend/app/knowledge/extraction/rag_prompts.py
git commit -m "refactor: rewrite extraction prompt to JSON-output format"
```

---

### Task 2: Add Pydantic Models + JSON Parser + Field Mapping

**Files:**
- Modify: `backend/app/knowledge/extraction/rag_extractor.py`

**Interfaces:**
- Consumes: `EXTRACTION_PROMPT`, `GENERIC_NAME_RETRY_PROMPT` from `rag_prompts`
- Produces: `_parse_json_output(raw_text) -> tuple[list[dict], list[dict]]`, `_detect_generic_names(entities) -> bool`, `_call_llm_with_retry(text, ...) -> tuple[list[dict], list[dict]]`
- Externally visible: `extract_async` signature unchanged

- [ ] **Step 1: Read current file head (lines 1-40) to understand imports**

Read `backend/app/knowledge/extraction/rag_extractor.py` lines 1-40.

- [ ] **Step 2: Add Pydantic models and new helper functions**

After the imports block (before the first class/function), add:

```python
# ── Pydantic 校验模型 ──────────────────────────────────────────────────────

from pydantic import BaseModel, Field
from typing import Literal, Optional

EntityType = Literal["Company", "Product", "Metric"]

class Entity(BaseModel):
    name: str = Field(min_length=1)
    type: EntityType

class Relation(BaseModel):
    entity1: str = Field(min_length=1)
    entity2: str = Field(min_length=1)
    description: str = ""
    confidence: float = 1.0
    stmt_type: Optional[Literal["Fact", "Claim", "Estimate"]] = None
    source: str = ""
    metric_value: Optional[float] = None
    metric_unit: Optional[str] = None
    metric_period: Optional[str] = None
    metric_period_type: Optional[Literal["actual", "forecast", "quarterly", "half-year"]] = None
    metric_sentiment: Optional[Literal["positive", "negative", "neutral"]] = None

class ExtractionOutput(BaseModel):
    entities: list[Entity] = []
    relations: list[Relation] = []
```

Then add the helper functions after the models:

```python
# ── JSON 解析 ──────────────────────────────────────────────────────────────

GENERIC_NAME_PATTERNS = re.compile(
    r'^(公司|本行|本公司|本集团|本企业|该企业|该(公|集)司|我们|我司|我公司)$'
)


def _parse_json_output(raw_text: str) -> tuple[list[dict], list[dict]] | None:
    """解析 LLM 返回的 JSON 字符串，返回 (entities, relations) 或 None。"""
    # 尝试从 ```json 块或纯 JSON 中提取
    text = raw_text.strip()
    if '```json' in text:
        text = text.split('```json', 1)[1].split('```', 1)[0].strip()
    elif '```' in text:
        text = text.split('```', 1)[1].split('```', 1)[0].strip()
    elif '{' not in text:
        logger.warning(f"No JSON found in LLM output: {raw_text[:200]}")
        return None

    try:
        parsed = ExtractionOutput.model_validate_json(text)
    except Exception as e:
        logger.warning(f"JSON validation failed: {e}, raw: {text[:200]}")
        return None

    # 去重 entities（同名只保留第一个）
    seen = set()
    deduped_entities = []
    for e in parsed.entities:
        if e.name not in seen:
            seen.add(e.name)
            deduped_entities.append({"entity_name": e.name, "entity_type": e.type})
    parsed.entities = deduped_entities

    # 过滤孤立关系：entity1/entity2 必须在 entities 中
    entity_names = set(e["entity_name"] for e in parsed.entities)
    valid_relations = []
    for r in parsed.relations:
        if r.entity1 in entity_names and r.entity2 in entity_names:
            valid_relations.append(r)

    # 映射为下游字段
    entities_out = list(parsed.entities)  # already as dicts from dedup
    relations_out = []
    for r in valid_relations:
        rel = {
            "src_id": r.entity1,
            "tgt_id": r.entity2,
            "description": r.description,
            "weight": r.confidence,
            "stmt_type": r.stmt_type or "Fact",
            "source_ids": [r.source] if r.source else [],
            "keywords": "",
            "direction": "neutral",
            "instance_count": 1,
            "descriptions": [r.description] if r.description else [],
            "has_direction_conflict": False,
        }
        # 把 metric 信息拼到对应 entity 的 metric 字段
        if r.entity2 in entity_names and r.metric_value is not None:
            for e in entities_out:
                if e["entity_name"] == r.entity2 and e["entity_type"] == "Metric":
                    e.setdefault("metric", {
                        "name": r.entity2,
                        "value": r.metric_value,
                        "unit": r.metric_unit,
                        "period": r.metric_period,
                        "period_type": r.metric_period_type,
                        "sentiment": r.metric_sentiment,
                    })
                    break
        relations_out.append(rel)

    # 为 entities 补全 description, source_ids 等字段（下游需要）
    for e in entities_out:
        e.setdefault("description", "")
        e.setdefault("source_ids", [])
        e.setdefault("instance_count", 1)

    return entities_out, relations_out


def _detect_generic_names(entities: list[dict]) -> bool:
    """检测 entities 中是否包含泛称。"""
    for e in entities:
        name = e.get("entity_name", "")
        if name and GENERIC_NAME_PATTERNS.match(name):
            return True
    return False
```

- [ ] **Step 3: Verify imports are consistent**

Check that `re` is imported at the top of the file. If not, the models block needs it.

- [ ] **Step 4: Commit**

```bash
git add backend/app/knowledge/extraction/rag_extractor.py
git commit -m "feat: add Pydantic models and JSON parser for extraction output"
```

---

### Task 3: Remove Old Parsers and Gleaning, Wire New Flow

**Files:**
- Modify: `backend/app/knowledge/extraction/rag_extractor.py`

**Interfaces:**
- Consumes: `_parse_json_output`, `_detect_generic_names` from Task 2
- Replaces: `_parse_entity_relation_blocks`, `_parse_relates`, `_parse_metrics`, `_parse_chunk_output`, gleaning loop
- Produces: Updated `_extract()` / `_extract_single_chunk()` / main extraction methods

- [ ] **Step 1: Read the full extraction flow**

Read all of `backend/app/knowledge/extraction/rag_extractor.py` to understand:
- `_extract()` method
- `_extract_single_chunk()` method
- `extract_async` function
- `_parse_entity_relation_blocks` (lines ~163-399)
- `_parse_relates` (lines ~402-480)
- `_parse_metrics` (lines ~483-512)
- `_parse_chunk_output` (lines ~515-551)
- gleaning loop

- [ ] **Step 2: Mark old parsers for deletion**

Add deprecation comment blocks above:
- `_parse_entity_relation_blocks`
- `_parse_relates`
- `_parse_metrics`
- `_parse_chunk_output`

- [ ] **Step 3: Rewrite the extraction entry point**

Find `extract_async` or `_extract` and replace its core logic to:

1. Call `_call_llm_async(prompt)` once (no gleaning loop)
2. Call `_parse_json_output(raw)` 
3. If None, retry once with same prompt
4. Call `_detect_generic_names(entities)`
5. If True, call LLM again with `GENERIC_NAME_RETRY_PROMPT` and parse again
6. Return `(entities, relations)`

The specific function to modify depends on what signature `kg_extractor.py` calls. Let me look at the relevant part more carefully.

- [ ] **Step 4: Find the exact call path**

Look at how `kg_extractor.py` calls the extraction — it likely calls `extract_async` or `rag_extract_async`. Check lines around the `extract_async` function.

- [ ] **Step 5: Implement the new flow**

Replace the body of `_extract_single_chunk()` (or equivalent) with:

```python
async def _extract_single_chunk(
    text: str,
    source_type: str,
    section_title: str = "文档概述",
    max_tokens: int = 1000,
) -> tuple[list[dict], list[dict]]:
    """单次 LLM 抽取（JSON 输出，无 gleaning）。"""
    prompt = get_extraction_prompt(source_type, section_title).format(
        input_text=text
    )

    # 首轮调用
    raw = await _call_llm_async(prompt, timeout=300)
    result = _parse_json_output(raw)

    # 首轮失败 → 重试一次
    if result is None:
        raw = await _call_llm_async(prompt, timeout=300)
        result = _parse_json_output(raw)

    if result is None:
        return [], []

    entities, relations = result

    # 泛称检测 → 全量重跑
    if _detect_generic_names(entities):
        logger.info("Detected generic names, retrying with augmented prompt")
        retry_prompt = GENERIC_NAME_RETRY_PROMPT.format(input_text=text)
        raw = await _call_llm_async(retry_prompt, timeout=300)
        result = _parse_json_output(raw)
        if result is not None:
            entities, relations = result

    return entities, relations
```

- [ ] **Step 6: Remove dead code**

Delete or comment out the body of:
- `_parse_entity_relation_blocks` (replace with `return {}, {}`)
- `_parse_relates` (replace with `return []`)
- `_parse_metrics` (replace with `return {}`)
- `_parse_chunk_output` (replace with call to `_parse_json_output`)
- gleaning loop (remove the while loop, keep only initial call)

- [ ] **Step 7: Update imports**

Remove imports of `CONTINUE_PROMPT`, `SUMMARIZE_PROMPT` etc. that are no longer used.

- [ ] **Step 8: Commit**

```bash
git add backend/app/knowledge/extraction/rag_extractor.py
git commit -m "refactor: replace gleaning loop with single-pass JSON extraction"
```

---

### Task 4: Update light_extractor.py

**Files:**
- Modify: `backend/app/knowledge/extraction/light_extractor.py`

**Interfaces:**
- Consumes: `_parse_json_output` (same signature as old parser functions)

- [ ] **Step 1: Read current file**

Read `backend/app/knowledge/extraction/light_extractor.py` lines 1-50 and the relevant parse section.

- [ ] **Step 2: Update imports**

Change:
```python
from app.knowledge.extraction.rag_extractor import (
    _parse_entity_relation_blocks,
    _parse_metrics,
    _parse_relates,
)
```
To:
```python
from app.knowledge.extraction.rag_extractor import (
    _parse_json_output,
)
```

- [ ] **Step 3: Update parse call sites**

In the `_parse_output` method (or equivalent), replace the three separate parse calls with a single `_parse_json_output(raw_response)` call and handle the result.

- [ ] **Step 4: Commit**

```bash
git add backend/app/knowledge/extraction/light_extractor.py
git commit -m "refactor: update light_extractor to use JSON parser"
```

---

### Task 5: Update Test Script

**Files:**
- Modify: `backend/scripts/test_new_prompt.py`

- [ ] **Step 1: Read current file**

Read `backend/scripts/test_new_prompt.py`.

- [ ] **Step 2: Update imports and parse calls**

Replace old parser imports with `_parse_json_output`, and update the `parse_output()` function similarly to `light_extractor.py`.

- [ ] **Step 3: Commit**

```bash
git add backend/scripts/test_new_prompt.py
git commit -m "refactor: update test script to use JSON parser"
```

---

### Task 6: Test with Sampled Evidence

**Files:**
- Test execution only (no code changes)

- [ ] **Step 1: Restart backend container**

```bash
docker compose up -d backend
```

- [ ] **Step 2: Run extraction on 5 diverse IRM evidence**

Use the 5 evidence IDs from the design session:
```
EV:55f797dcd1b77da8f6ad51e737a782667b61baeb01ec265423f1d7ff44642350  (华域汽车 501c)
EV:ecb14635bb468ef85c2706d4b9b0a3d41e18f0e86f18be9b179fd1b9ef2d7c31  (ST金顶 282c)
EV:b29916d177970542bc454db083774796837ee5e6d6616ad586aa7f3ad6c1a8ca  (江苏银行 231c)
EV:53fb72f1d038a468bdad7a7f83bde3e9ececd9b52457b28ffe624b5a7fb6f14a  (华域汽车 252c)
EV:92c59334a12441cf22d2859084b7d17456398ac199cd04dc19b7c1bc9ae4ff47  (华域汽车 195c)
```

Print: entities, relations, LLM raw output, timing.

- [ ] **Step 3: Verify results**

Check:
- All output is valid JSON
- No generic names ("公司"/"本行")
- All relations reference declared entities
- No duplication
- Timing is reasonable (expect 30-60s per call)
