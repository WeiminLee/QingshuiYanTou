# KG 抽取 Prompt 重构 — JSON 输出 + 三元组架构

> 日期：2026-06-28
> 范围：LLM 抽取输出格式从文本 regex 改为 JSON，解析器和 Prompt 联动重构
> 状态：设计稿

---

## 1. 背景与动机

当前 KG 抽取使用文本格式（Entity:/RELATES:/METRIC: + regex 解析），存在以下问题：

| 问题 | 表现 | 影响 |
|------|------|------|
| 格式不匹配 | Prompt 输出 `关系描述:`，V2 解析器找 `关系陈述:` | 实体关系丢失 |
| 冗余解析 | `_parse_entity_relation_blocks` / `_parse_relates` / `_parse_metrics` 三套重叠逻辑 | 维护成本高，bug 隐蔽 |
| 孤立节点 | 单独声明实体但无关系，在 KG 中无意义 | 浪费存储，噪音 |
| 泛称指代 | LLM 输出"公司"/"本行"代替实际公司名 | 实体无法映射 |
| 副作用残留 | `属性:`、`Relation:`、`weight:` 等旧 prompt 死代码 | 解析误匹配 |
| 嵌套数据弱 | Metric 的 value/unit/period/sentiment 跨解析器拼凑 | 数据不完整 |

### 设计原则

1. **三元组中心** — 实体只出现在关系中，孤立实体不产出
2. **JSON 输出** — LLM 输出结构化 JSON，Pydantic 校验
3. **单次调用** — 一次 LLM 调用完成抽取，去除 gleaning
4. **泛称重跑** — 检测泛称时全量重跑，不局部修复
5. **向后兼容** — 下游 consumer 字段名不变（`entity_name`, `entity_type`, `src_id`, `tgt_id`）

---

## 2. JSON Schema

### LLM 输出格式

```json
{
  "entities": [
    {"name": "华域汽车", "type": "Company"},
    {"name": "半固态电池", "type": "Product"},
    {"name": "核心一级资本率", "type": "Metric"}
  ],
  "relations": [
    {
      "entity1": "华域汽车",
      "entity2": "半固态电池",
      "description": "通过收购清陶动力布局半固态电池业务",
      "confidence": 1.0,
      "stmt_type": "Fact",
      "source": "公司所属延锋汽车饰件系统有限公司与华为进行联合创新产品开发...",
      "metric_value": null,
      "metric_unit": null,
      "metric_period": null,
      "metric_period_type": null,
      "metric_sentiment": null
    }
  ]
}
```

### 字段约束

#### Entity

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `name` | string | 是 | 实体名称，与文本中出现的全称/简称一致；禁止"公司""本行"等泛称 |
| `type` | `"Company" \| "Product" \| "Metric"` | 是 | 白名单以外的类型禁止输出 |

#### Relation

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `entity1` | string | 是 | 引用 entities 中的 name |
| `entity2` | string | 是 | 引用 entities 中的 name |
| `description` | string | 是 | 自然语言描述，保留时间/方向/状态变化 |
| `confidence` | float | 否 | 1.0=直接陈述，0.7=轻度推断 |
| `stmt_type` | `"Fact" \| "Claim" \| "Estimate"` | 否 | 陈述类型 |
| `source` | string | 是 | 原文相关句 |
| `metric_value` | float\|null | 否 | entity2 为 Metric 时有值 |
| `metric_unit` | string\|null | 否 | 如 "%", "亿元", "GWh" |
| `metric_period` | string\|null | 否 | 如 "2024A", "2025E", "2024Q1" |
| `metric_period_type` | `"actual" \| "forecast" \| "quarterly" \| "half-year" \| null` | 否 | 周期类型 |
| `metric_sentiment` | `"positive" \| "negative" \| "neutral" \| null` | 否 | 情感倾向 |

### Pydantic 校验模型

```python
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

### 后处理校验规则

1. **entity name 去重** — 同名实体只保留一个
2. **泛称检测** — 若任何 entity name 匹配 `公司|本行|本公司|本集团|本企业`，触发二次抽取
3. **孤立关系检测** — relation 引用的 entity1/entity2 必须在 entities 中存在，否则丢弃该 relation
4. **字段映射** — 将 LLM 输出字段映射为下游 consumer 字段

### 字段映射表

| LLM 输出字段 | 下游字段 | 说明 |
|-------------|---------|------|
| `entities[].name` | `entity_name` | 直接映射 |
| `entities[].type` | `entity_type` | 直接映射 |
| `relations[].entity1` | `src_id` | 源实体名称 |
| `relations[].entity2` | `tgt_id` | 目标实体名称 |
| `relations[].description` | `description` | 直接映射 |
| `relations[].confidence` | `weight` | float 转换 |
| `relations[].stmt_type` | `stmt_type` | 直接映射 |
| `relations[].source` | `source_ids` | 包装为 list |
| `relations[].metric_*` | `entities[].metric` | 拼入对应 Metric 实体的 metric 字段 |

---

## 3. 抽取流程

```
输入文本
    │
    ▼
[首轮 LLM 调用] ──────────────────────────────┐
    │ JSON 输出                               │
    ▼                                          │
[Pydantic 校验] ──失败──→ [重试 ×1] ──失败──→ [回退：提示重新输出]
    │ 通过                                       │
    ▼                                            │
[泛称检测] ──命中──→ [第二轮 LLM 调用] ────────→ 取第二轮结果
    │ 无泛称              (追加禁止泛称指令)       │
    ▼                                              │
[字段映射 → 下游] ◄──────────────────────────────┘
```

### 关键差异

| 维度 | 当前 | 新设计 |
|------|------|--------|
| LLM 输出 | 文本格式 (Entity:/RELATES:/METRIC:) | JSON |
| 解析方式 | 三套 regex 解析器 | Pydantic `model_validate_json()` |
| 调用次数 | 1 次 + gleaning (最多 3 次) | 1 次 (±1 次泛称重跑) |
| 实体与关系 | 分别输出，无关联校验 | entities + relations，关系引用实体名 |
| 泛称处理 | 无 | 检测后全量重跑 |
| Metric 结构 | 跨解析器拼凑 | relation 层直接携带 |

### 删除项

| 文件 | 函数/变量 | 原因 |
|------|----------|------|
| `rag_extractor.py` | `_parse_entity_relation_blocks` | 被 Pydantic 取代 |
| `rag_extractor.py` | `_parse_relates` | 被 Pydantic 取代 |
| `rag_extractor.py` | `_parse_metrics` | 被 Pydantic 取代 |
| `rag_extractor.py` | `_parse_chunk_output` | 逻辑内联 |
| `rag_extractor.py` | CONTINUE_PROMPT / LOOP_PROMPT / gleaning 循环 | 单次调用 |
| `rag_prompts.py` | `EXTRACTION_PROMPT` (旧版) | 统一为新版 JSON prompt |
| `rag_prompts.py` | `CONTINUE_PROMPT / SUMMARIZE_PROMPT` | 不再使用 |
| `rag_prompts.py` | `RELATES_EXTRACTION_PROMPT / METRIC_EXTRACTION_PROMPT` | 不再使用 |

### 保留项

| 文件 | 函数/变量 | 原因 |
|------|----------|------|
| `rag_extractor.py` | `_merge_single_entity` / `_merge_single_relation` | 下游依赖合并逻辑 |
| `rag_extractor.py` | `_filter_extraction_noise` | 通用的 entity name 过滤 |
| `rag_extractor.py` | `extract_async` | 入口签名不变 |
| `kg_extractor.py` | `upsert_entity` / `upsert_relates` | 字段映射后接口不变 |

---

## 4. Prompt 模板设计

### System Prompt

```
你是一名专业的投资研究知识图谱抽取专家。

【实体类型】
- Company：公司（上市公司、子公司、重要客户、供应商、竞争对手、合作伙伴）
- Product：产品、材料、设备、服务、技术系统（如智能座舱、半固态电池）
- Metric：量化指标，必须包含数字+单位（如"营收120亿元"、"毛利率32%"）

【禁止行为】
- 使用"公司""本行""本公司"等泛称代替确切实体名称
- 输出白名单以外的实体类型
- 抽取页眉页脚、免责声明、URL、表格行、无意义的单字

【输出格式】
返回 JSON 对象，格式如下：

{
  "entities": [
    {"name": "<实体名称>", "type": "Company|Product|Metric"}
  ],
  "relations": [
    {
      "entity1": "<主体实体名称>",
      "entity2": "<客体实体名称>",
      "description": "<关系描述，保留时间/方向/状态>",
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
- 当 entity2 类型为 Metric 时，须填写 metric_value / metric_unit / metric_period / metric_period_type / metric_sentiment
- metric_period 格式：2024A（实际年）、2025E（预测年）、2024Q1（季度）
- metric_period_type：actual（已实现）、forecast（预测）、quarterly（季度）、half-year（半年度）
- metric_sentiment：positive（正面）、negative（负面）、neutral（中性）

【关系规则】
- entity1 和 entity2 必须引用 entities 中声明的 name
- 同一对 (entity1, entity2) 如有多个不同事实，合并到一条关系中
- 只抽取文本中明确陈述的内容，不要推断未写明的事实

【陈述类型】
- Fact：原文明确陈述的客观事实（如"2024年营收120亿元"）
- Claim：公司/管理层的主张（如"管理层表示订单饱满"）
- Estimate：预测、推测（如"预计2025年产能翻倍"）

【置信度】
- 1.0 = 原文直接陈述
- 0.7 = 基于上下文轻度推断，必须有来源句支撑

{input_text}
```

---

## 5. 二次抽取（泛称重跑）

### 触发条件

entity name 匹配以下正则之一：

```
r'^(公司|本行|本公司|本集团|本企业|该[公司行])$'
r'^(我们|我公司|我司)$'
```

### 流程

1. 首轮 LLM 输出 → Pydantic 校验通过 → 泛称检测
2. 检测到泛称 → 用同一文本发起第二轮调用
3. 第二轮 prompt 在首轮基础上追加一条指令：
   ```
   【重要】禁止使用"公司""本行""本公司""本集团"等模糊指代。
   必须从文本中提取确切的公司全称或简称。例如"公司"应替换为文本中出现的实际名称。
   ```
4. 取第二轮结果（丢弃首轮结果）

---

## 6. 实施计划

### Phase 1 — 核心替换 (2-3h)

1. `rag_prompts.py` — 替换为新版 JSON prompt，删除旧版和废弃常量
2. `rag_extractor.py` — 添加 Pydantic models、`_parse_json_output()`、`_detect_generic_name()`、字段映射
3. `rag_extractor.py` — 删除三套旧 regex 解析器和新 gleaning 循环
4. `rag_extractor.py` — 重写 `_extract()` 核心逻辑为新流程

### Phase 2 — 清理与验证 (1h)

5. `light_extractor.py` — 更新 import，适配新解析函数
6. `scripts/test_new_prompt.py` — 更新测试脚本
7. 用 5 条 IRM evidence 做回归测试

### 不回改的

- `kg_extractor.py` — `extract_text_async()` / `extract_evidence_async()` 入口不变
- `irm_extractor.py` — field 映射后调用层不变
- 下游存储（Neo4j upsert 函数）不变
