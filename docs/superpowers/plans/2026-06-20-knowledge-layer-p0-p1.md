# Knowledge Layer P0/P1 Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 4-layer knowledge navigation instructions to the Agent prompt, create a fetch_evidence tool for L1 traceback, add stmt_type (Fact/Claim/Estimate) tagging to L3 relations, and materialize semantic_tags as relation_subtype on Neo4j RELATES edges.

**Architecture:** Four independent changes, each self-contained: (1) prompt-only change to teach the Agent knowledge navigation, (2) a new LangChain tool wrapping existing EvidenceService, (3) extending the LLM extraction prompt + parse + upsert pipeline to carry stmt_type, (4) writing infer_relation_type() results to Neo4j at upsert time.

**Tech Stack:** Python, LangChain tools, Neo4j Cypher, existing RAG extraction pipeline

---

## File Structure

| File | Role | Action |
|------|------|--------|
| `backend/app/reasoning/langchain_agent/prompts/lead_system_prompt.py` | Agent system prompt | Modify — add `<knowledge_navigation>` section |
| `backend/app/reasoning/tools/knowledge/evidence.py` | fetch_evidence LangChain tool | Create |
| `backend/app/reasoning/tools/knowledge/__init__.py` | Tool exports | Create |
| `backend/app/reasoning/registry/loader.py` | Tool registration | Modify — register fetch_evidence |
| `backend/app/knowledge/extraction/rag_prompts.py` | Extraction prompts | Modify — add stmt_type to RELATES output |
| `backend/app/knowledge/extraction/rag_extractor.py` | Relation parsing | Modify — parse stmt_type from LLM output |
| `backend/app/knowledge/relation_service.py` | Relation upsert | Modify — accept stmt_type + relation_subtype params |
| `backend/app/knowledge/kg_extractor.py` | KG extraction orchestration | Modify — pass stmt_type + relation_subtype through pipeline |

---

### Task 1: Add Knowledge Navigation Instructions to Agent Prompt

**Files:**
- Modify: `backend/app/reasoning/langchain_agent/prompts/lead_system_prompt.py:76-91`

- [x] **Step 1: Add `<knowledge_navigation>` section after `<instructions>` block**

Insert the following block between the `</instructions>` tag (line 91) and `<thinking_style>` (line 93):

```python
# In SYSTEM_PROMPT_TEMPLATE, after </instructions> and before <thinking_style>:

<knowledge_navigation>
**四层知识导航体系**：

你拥有从模糊概念到原始证据的完整知识访问能力。按以下层级逐步深入：

L4 — 认知抽象层（行业主题/技术路线/投资逻辑）：
- 接到问题，先判断属于哪个"行业主题"或"投资逻辑"
- 用 `neo4j_industry_state` 了解行业生命周期阶段分布
- 用 `get_concept_hot` 判断市场情绪和板块热度

L3 — 叙事逻辑层（自然语言关系网）：
- 用 `neo4j_traverse` 和 `neo4j_path` 在关系网中寻找逻辑链条
- 关注 RELATES 边的 weight（置信度）和 direction（方向性）
- 留意 stmt_type 标签：Fact（事实陈述）vs Claim（断言）vs Estimate（预测）
- 发现叙事矛盾（如"已量产"vs"还在中试"）时，主动标注预期差

L2 — 结构化索引层（实体属性/时序索引）：
- 用 `neo4j_entity_info` 快速获取实体属性（行业状态、信号、置信度）
- 用 `get_stock_profile` 获取公司基本面和主营业务
- 用 `get_kline` 获取技术面数据，验证基本面逻辑

L1 — 证据原子层（原始公告/研报/互动易）：
- **任何定量结论（财务数据、产能数字、订单金额）必须通过 `fetch_evidence` 追溯到 L1 原始文本**
- 用 `get_announcement` 获取官方公告原文
- 用 `get_research_report` 获取研报摘要
- 用 `get_irm` 获取互动易问答记录

**导航原则**：
- 自上而下穿透：L4 确定方向 → L3 寻找逻辑 → L2 精确定位 → L1 结算证据
- 严禁仅凭 L3 的叙事文本下定量结论（如"营收 130 亿"），必须回到 L1 确认
- 发现 Fact 与 Estimate 矛盾时，标注为预期差信号
</knowledge_navigation>
```

- [x] **Step 2: Verify the prompt template still formats correctly**

Run a quick syntax check:

```bash
cd backend && python -c "from app.reasoning.langchain_agent.prompts.lead_system_prompt import apply_prompt_template; prompt = apply_prompt_template(); assert '<knowledge_navigation>' in prompt; print('OK')"
```

Expected: `OK`

- [x] **Step 3: Commit**

```bash
git add backend/app/reasoning/langchain_agent/prompts/lead_system_prompt.py
git commit -m "feat(prompt): add 4-layer knowledge navigation instructions to agent system prompt"
```

---

### Task 2: Create fetch_evidence LangChain Tool

**Files:**
- Create: `backend/app/reasoning/tools/knowledge/evidence.py`
- Create: `backend/app/reasoning/tools/knowledge/__init__.py`
- Modify: `backend/app/reasoning/registry/loader.py:80-85`

- [x] **Step 1: Create the fetch_evidence tool file**

```python
"""
fetch_evidence — L1 evidence retrieval tool.

Allows the Agent to trace any conclusion back to the original
source text stored in MongoDB's kg_evidence collection.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Annotated

from langchain_core.tools import tool

logger = logging.getLogger(__name__)


@tool("fetch_evidence")
def fetch_evidence(
    evidence_id: Annotated[
        str,
        "证据 ID，格式为 EV:xxxx（来自知识图谱关系的 evidence_id 属性）",
    ],
) -> str:
    """
    追溯知识图谱中任意结论的原始证据（L1 证据原子层）。

    使用场景：
    - Agent 从 L3 叙事层得到一个定量结论（如"中际旭创 2024 年营收 130 亿"）
    - 需要验证这个结论来自哪份公告/研报的哪一段原文
    - 调用本工具，传入关系的 evidence_id，获取原始文本+来源元数据

    Returns:
        格式化的证据文本，包含原始内容、来源类型、发布时间、置信度
    """
    try:
        from app.knowledge.evidence_service import EvidenceService

        svc = EvidenceService()
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(svc.get_evidence(evidence_id))
            loop.close()
            return _format_evidence(result)

        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(
                lambda: loop.run_until_complete(svc.get_evidence(evidence_id))
            )
            result = future.result(timeout=10)
        return _format_evidence(result)
    except Exception as e:
        logger.warning("fetch_evidence 失败 [%s]: %s", evidence_id, e)
        return f"证据查询失败: {e}"


def _format_evidence(doc: dict | None) -> str:
    """格式化证据文档为 Agent 可读文本。"""
    if not doc:
        return "未找到该证据记录（可能 evidence_id 无效或数据已过期）。"

    lines = [
        f"证据 ID: {doc.get('evidence_id', 'N/A')}",
        f"来源类型: {doc.get('source_type', 'N/A')}",
        f"来源名称: {doc.get('source_name', 'N/A')}",
        f"发布时间: {doc.get('publish_date', 'N/A')}",
        f"置信度: {doc.get('confidence', 'N/A')}",
        f"--- 原始文本 ---",
        doc.get("text_excerpt", "(无文本内容)"),
    ]

    subject = doc.get("subject_hint") or {}
    if subject.get("ts_code"):
        lines.insert(2, f"关联股票: {subject['ts_code']}")

    return "\n".join(lines)
```

- [x] **Step 2: Create the knowledge tools __init__.py**

```python
from app.reasoning.tools.knowledge.evidence import fetch_evidence

__all__ = ["fetch_evidence"]
```

- [x] **Step 3: Register fetch_evidence in the tool registry**

Add after the `neo4j_kg_search` config entry (after line 85 in loader.py):

```python
        ToolConfig(
            name="fetch_evidence",
            group=ToolGroup.KNOWLEDGE,
            use="app.reasoning.tools.knowledge:fetch_evidence",
            description="追溯知识图谱结论的原始证据（L1原子层），传入evidence_id获取公告/研报/互动易原文",
        ),
```

- [x] **Step 4: Verify the tool loads correctly**

```bash
cd backend && python -c "
from app.reasoning.tools.knowledge import fetch_evidence
print('Tool name:', fetch_evidence.name)
print('Tool description:', fetch_evidence.description[:80])
"
```

Expected: `Tool name: fetch_evidence` with description.

- [x] **Step 5: Commit**

```bash
git add backend/app/reasoning/tools/knowledge/evidence.py backend/app/reasoning/tools/knowledge/__init__.py backend/app/reasoning/registry/loader.py
git commit -m "feat(tools): add fetch_evidence tool for L1 evidence traceback"
```

---

### Task 3: Add stmt_type Tag to RELATES Extraction

**Files:**
- Modify: `backend/app/knowledge/extraction/rag_prompts.py:158-212` (EXTRACTION_PROMPT_V4)
- Modify: `backend/app/knowledge/extraction/rag_prompts.py:214-230` (RELATES_EXTRACTION_PROMPT)
- Modify: `backend/app/knowledge/extraction/rag_extractor.py:384-455` (_parse_relates_v4)
- Modify: `backend/app/knowledge/extraction/rag_extractor.py:490-514` (_parse_chunk_output_v4)

- [x] **Step 1: Add stmt_type to EXTRACTION_PROMPT_V4**

In `rag_prompts.py`, in `EXTRACTION_PROMPT_V4`, add a `陈述类型` line to the RELATES output format specification. Change the RELATES section from:

```
RELATES: 实体A → 实体B
  关系描述: "100字以内，保留时间、方向、状态变化"
  置信度: 1.0
  来源: "原文相关句"
```

To:

```
RELATES: 实体A → 实体B
  关系描述: "100字以内，保留时间、方向、状态变化"
  置信度: 1.0
  陈述类型: Fact / Claim / Estimate
  来源: "原文相关句"

陈述类型规则：
- Fact: 原文明确陈述的客观事实（如"2024年营收120亿元"、"公司已实现800G光模块量产"）
- Claim: 公司/管理层的主张或声明（如"公司认为技术领先行业"、"管理层表示订单饱满"）
- Estimate: 预测、推测、目标（如"预计2025年产能翻倍"、"券商预测营收增长30%"）
```

Also update the example in the prompt to include `陈述类型: Fact`:

```
示例：
输入：宁德时代在储能领域生产销售三元锂电池，预计2025年产能增长。
输出：
Entity: 宁德时代(Company)
Entity: 三元锂电池(Product)
Entity: 储能(Application)
Entity: 产能(Metric)
RELATES: 宁德时代 → 三元锂电池
  关系描述: "在储能领域生产销售三元锂电池产品"
  置信度: 1.0
  陈述类型: Fact
  来源: "宁德时代在储能领域生产销售三元锂电池"
```

- [x] **Step 2: Add stmt_type to RELATES_EXTRACTION_PROMPT**

In `RELATES_EXTRACTION_PROMPT`, add the same `陈述类型` field. Change:

```
只输出以下格式：
RELATES: 实体A → 实体B
  关系描述: "自然语言描述，100字以内"
  置信度: 1.0 或 0.7
  来源: "原文相关句"
```

To:

```
只输出以下格式：
RELATES: 实体A → 实体B
  关系描述: "自然语言描述，100字以内"
  置信度: 1.0 或 0.7
  陈述类型: Fact / Claim / Estimate
  来源: "原文相关句"

陈述类型: Fact=客观事实, Claim=管理层主张, Estimate=预测推测
```

- [x] **Step 3: Parse stmt_type in _parse_relates_v4**

In `rag_extractor.py`, modify `_parse_relates_v4` to parse the new `陈述类型` field. Add a pattern after the existing `source_pattern`:

```python
# Add this pattern alongside the existing ones (after source_pattern):
stmt_type_pattern = re.compile(r"^\s*陈述类型\s*[:：]\s*(Fact|Claim|Estimate)\s*$", re.IGNORECASE)
```

In the line-by-line parsing loop, add a handler for stmt_type after the source_match handler (around line 453):

```python
        stmt_match = stmt_type_pattern.match(line)
        if stmt_match:
            current["stmt_type"] = stmt_match.group(1).capitalize()
```

Also initialize `stmt_type` with a default in the `current` dict creation blocks (lines 413 and 430):

```python
# In the first current = {...} block (line 413), add:
    "stmt_type": "Fact",
# In the second current = {...} block (line 430), add:
    "stmt_type": "Fact",
```

- [x] **Step 4: Pass stmt_type through _parse_chunk_output_v4**

In `_parse_chunk_output_v4` (line 490), add `stmt_type` to the edge dict:

```python
    for rel in _parse_relates_v4(raw_text):
        key = (rel["from_entity"], rel["to_entity"])
        edges.setdefault(key, []).append({
            "src_id": rel["from_entity"],
            "tgt_id": rel["to_entity"],
            "description": rel.get("text", ""),
            "keywords": "",
            "direction": "neutral",
            "weight": rel.get("weight", 1.0),
            "source": rel.get("source", ""),
            "stmt_type": rel.get("stmt_type", "Fact"),   # <-- NEW
        })
```

- [x] **Step 5: Verify parsing with a unit test**

```bash
cd backend && python -c "
from app.knowledge.extraction.rag_extractor import _parse_relates_v4

sample = '''RELATES: 宁德时代 → 三元锂电池
  关系描述: \"在储能领域生产销售\"
  置信度: 1.0
  陈述类型: Fact
  来源: \"原文句子\"
'''
result = _parse_relates_v4(sample)
assert len(result) == 1
assert result[0]['stmt_type'] == 'Fact'
assert result[0]['from_entity'] == '宁德时代'
print('PASS')
"
```

Expected: `PASS`

- [x] **Step 6: Commit**

```bash
git add backend/app/knowledge/extraction/rag_prompts.py backend/app/knowledge/extraction/rag_extractor.py
git commit -m "feat(extraction): add stmt_type (Fact/Claim/Estimate) to RELATES extraction prompts and parser"
```

---

### Task 4: Store stmt_type and relation_subtype in upsert_relates_v4

**Files:**
- Modify: `backend/app/knowledge/relation_service.py:779-928` (upsert_relates_v4)
- Modify: `backend/app/knowledge/kg_extractor.py:1002-1037` (extract_text_async relation creation)
- Modify: `backend/app/knowledge/kg_extractor.py:617-648` (extract_text relation creation)

- [x] **Step 1: Add stmt_type and relation_subtype parameters to upsert_relates_v4**

In `relation_service.py`, modify the `upsert_relates_v4` function signature to add two new parameters. Change:

```python
def upsert_relates_v4(
    from_entity: str,
    to_entity: str,
    text: str,
    weight: float = 1.0,
    source_chunk: str | None = None,
    source_file: str | None = None,
    source_type: str = "unknown",
    source_name: str = "unknown",
    valid_from: date | None = None,
    valid_to: date | None = None,
    direction: str = "neutral",
    llm_client: Any | None = None,
    evidence_id: str | None = None,
    evidence_ids: list[str] | None = None,
) -> tuple[dict, bool]:
```

To:

```python
def upsert_relates_v4(
    from_entity: str,
    to_entity: str,
    text: str,
    weight: float = 1.0,
    source_chunk: str | None = None,
    source_file: str | None = None,
    source_type: str = "unknown",
    source_name: str = "unknown",
    valid_from: date | None = None,
    valid_to: date | None = None,
    direction: str = "neutral",
    llm_client: Any | None = None,
    evidence_id: str | None = None,
    evidence_ids: list[str] | None = None,
    stmt_type: str = "Fact",
    relation_subtype: str | None = None,
) -> tuple[dict, bool]:
```

- [x] **Step 2: Store stmt_type and relation_subtype in the MERGE properties**

In the `if existing:` branch of `upsert_relates_v4`, add stmt_type handling (after the direction handling block, around line 897):

```python
        # stmt_type: keep the highest-confidence type (Fact > Claim > Estimate)
        _stmt_rank = {"Fact": 3, "Claim": 2, "Estimate": 1}
        old_stmt = merged.get("stmt_type", "Fact")
        if _stmt_rank.get(stmt_type, 0) > _stmt_rank.get(old_stmt, 0):
            merged["stmt_type"] = stmt_type

        # relation_subtype: first-write-wins (same as direction)
        if relation_subtype and not merged.get("relation_subtype"):
            merged["relation_subtype"] = relation_subtype
```

In the `else` (new relation) branch, find the `run_write` call that creates the new relation (around line 928). The SET clause already uses `$props` — we need to ensure `stmt_type` and `relation_subtype` are included in the props dict passed to that write. Add them to the properties dict that gets passed to the CREATE query.

Find the CREATE block (around line 960-990) and add `stmt_type` and `relation_subtype` to the properties dict:

```python
        props = {
            "text": text,
            "weight": weight,
            "direction": direction,
            "descriptions": [new_desc_str],
            "source_type": source_type,
            "source_name": source_name,
            "source_chunk": source_chunk or "",
            "source_file": source_file or "",
            "valid_from": valid_from_str,
            "valid_to": valid_to_str,
            "stmt_type": stmt_type,              # <-- NEW
            "relation_subtype": relation_subtype or "",  # <-- NEW
            "created_at": now,
            "updated_at": now,
        }
```

- [x] **Step 3: Pass stmt_type and relation_subtype from kg_extractor (async path)**

In `kg_extractor.py`, modify the `extract_text_async` function's relation creation loop (around line 1017) to pass `stmt_type` and `relation_subtype`. 

Add `stmt_type` extraction from the relation dict:

```python
    for r in merged_relations:
        src_name = r.get("src_id", "").strip()
        tgt_name = r.get("tgt_id", "").strip()
        rel_desc = r.get("description", "").strip()
        direction = r.get("direction", "neutral")
        has_conflict = r.get("has_direction_conflict", False)
        stmt_type = r.get("stmt_type", "Fact")           # <-- NEW
```

Then compute `relation_subtype` using `infer_relation_type`:

```python
        # Infer relation_subtype from description text
        relation_subtype = infer_relation_type(rel_desc)  # <-- NEW
```

Then pass both to `upsert_relates_v4`:

```python
        try:
            _, is_new = upsert_relates_v4(
                from_entity=src_eid,
                to_entity=tgt_eid,
                text=rel_desc,
                weight=v2_weight,
                source_file=source_file,
                source_type=source_type,
                source_name=source_name,
                direction=direction,
                valid_from=today,
                stmt_type=stmt_type,              # <-- NEW
                relation_subtype=relation_subtype, # <-- NEW
            )
```

- [x] **Step 4: Pass stmt_type and relation_subtype from kg_extractor (sync path)**

Apply the same changes to the `extract_text` function's relation creation loop (around line 633):

```python
    for r in merged_relations:
        ...
        stmt_type = r.get("stmt_type", "Fact")           # <-- NEW
        relation_subtype = infer_relation_type(rel_desc)  # <-- NEW
        ...
        try:
            _, is_new = upsert_relates_v4(
                ...
                stmt_type=stmt_type,              # <-- NEW
                relation_subtype=relation_subtype, # <-- NEW
            )
```

- [x] **Step 5: Verify the import chain**

```bash
cd backend && python -c "
from app.knowledge.relation_service import upsert_relates_v4, infer_relation_type
import inspect
sig = inspect.signature(upsert_relates_v4)
assert 'stmt_type' in sig.parameters
assert 'relation_subtype' in sig.parameters
print('PASS: upsert_relates_v4 has new parameters')
print('infer_relation_type test:', infer_relation_type('中际旭创向华为交付800G光模块'))
"
```

Expected: `PASS` and a relation type like `SUPPLIES_TO` or `PRODUCES`.

- [x] **Step 6: Commit**

```bash
git add backend/app/knowledge/relation_service.py backend/app/knowledge/kg_extractor.py
git commit -m "feat(knowledge): store stmt_type and relation_subtype on RELATES edges in Neo4j"
```

---

### Task 5: Integration Verification

**Files:**
- None (verification only)

- [x] **Step 1: Run existing tests to ensure no regressions**

```bash
cd backend && python -m pytest tests/ -x -q --tb=short 2>&1 | tail -20
```

- [x] **Step 2: Verify the full pipeline end-to-end**

```bash
cd backend && python -c "
from app.knowledge.extraction.rag_prompts import EXTRACTION_PROMPT_V4
# Verify stmt_type is in the prompt
assert '陈述类型' in EXTRACTION_PROMPT_V4
print('PASS: stmt_type in EXTRACTION_PROMPT_V4')

from app.knowledge.relation_service import infer_relation_type
# Verify infer_relation_type works
assert infer_relation_type('中际旭创向华为交付800G光模块') in ('SUPPLIES_TO', 'PRODUCES', 'DIRECTLY_SUPPLIES_TO')
print('PASS: infer_relation_type works')

from app.reasoning.tools.knowledge import fetch_evidence
print('PASS: fetch_evidence tool loaded:', fetch_evidence.name)
"
```

Expected: All three PASS.

- [x] **Step 3: Commit verification**

```bash
git add -A
git commit -m "verify: integration check for P0/P1 knowledge layer improvements"
```

---

## Self-Review Checklist

1. **Spec coverage:** All four P0/P1 items are covered — prompt instructions (Task 1), fetch_evidence tool (Task 2), stmt_type (Task 3), relation_subtype (Task 4). Integration verification (Task 5).
2. **Placeholder scan:** No TBD/TODO. All code blocks show actual implementation. All file paths are exact. All verification commands include expected output.
3. **Type consistency:** `stmt_type` is consistently `"Fact"` (default) across all tasks. `relation_subtype` is `str | None` consistently. The `_stmt_rank` dict uses the same three values (Fact/Claim/Estimate) in both prompt and code.