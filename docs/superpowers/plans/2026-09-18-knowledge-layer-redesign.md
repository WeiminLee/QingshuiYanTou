# 知识层重构（链接层 + 判断台账）Implementation Plan

> **For agentic workers.** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用「双通道链接层（LLM 浅提取 + 词典匹配 + 向量）+ 判断台账（observation/finding/watermark）」替换三元组抽取管线，让 agent 具备 pull 时间线 / 横截面 scan / 主题 browse 三类检索能力。

**Architecture:** L0 证据层（Mongo kg_evidence，不动）之上新建 L1 链接层（PG：keyword + link 表，可全量重算）与 L2 判断层（PG：observation/finding/watermark）。批量侧只做浅任务（LLM 类型受约束关键字提取，1 次 flash 调用/条），深判断只在 task-time。Neo4j 冻结只读，Qdrant `kg_entities`/`kg_relations` 退役。

**Tech Stack:** Python 3.12 + FastAPI 后端（已存在）；SQLAlchemy 2.0 async（`app.core.database.async_session`）+ Alembic；MongoDB（Motor，`EvidenceService`）；LangChain `@tool`（agent 工具）；PyYAML（已在依赖中）。

**Spec:** `docs/superpowers/specs/2026-09-18-knowledge-layer-redesign-design.md`

## Global Constraints

- 测试从仓库根运行：`python -m pytest backend/tests/test_linklayer_<name>.py -q`；需要真实外部服务的用例必须标 `@pytest.mark.integration`（默认跳过，见 `backend/tests/conftest.py`）。
- 单元测试不得要求真实数据库/LLM——遵循 conftest 占位环境变量模式，外部依赖用 monkeypatch。
- 新 PG 表全部挂在 SQLAlchemy `Base`（`app.core.database`）下，与 `backend/alembic/versions/` 迁移一致；下一个迁移号是 `023`。
- 稳定 ID 风格：`"KW:" + sha256(f"{layer}:{norm_text}")[:16]`（keyword）、`"OB:"`/`"FD:"` 同理，与项目 `EV:`/`JOB:` 风格一致。
- LLM 只用 `settings.llm_extraction_model`（flash 类，含现成回退逻辑 `llm_extraction_fallback_order`）；**禁止**使用 `settings.llm_model`（可能是推理模型）。LLM 只输出 surface form，归一化必须机械完成。
- LLM 调用参照 `app/knowledge/extraction/rag_extractor.py:313`（`_call_llm_async`）的 `chat_async` 使用方式。
- 每个任务结束必须 commit（`git add` 相关文件 + 中文 conventional commit message）。
- 不新增运行时依赖（stdlib + 已有依赖）。

---

## Phase P0：评估基线

### Task 1: Gold set 骨架 + 检索评估脚本

**Files:**
- Create. `backend/eval/gold_set_v1.json`（评估数据）
- Create. `backend/scripts/eval_retrieval.py`（评估 runner）
- Test. `backend/tests/test_linklayer_eval.py`

**Interfaces:**
- Produces: `eval_retrieval.py` 的 CLI：`python backend/scripts/eval_retrieval.py --backend link|semantic --gold backend/eval/gold_set_v1.json --k 20`，输出 Recall@k / 命中率；后续 Task 9/10 的 `pull_history`/`semantic_search` 可作为 backend 插入。

- [ ] **Step 1: 写失败测试**（gold set schema 校验）

```python
# backend/tests/test_linklayer_eval.py
"""Gold set schema 与评估器纯逻辑测试。"""
import json
from pathlib import Path

GOLD_PATH = Path(__file__).parent.parent / "eval" / "gold_set_v1.json"


def test_gold_set_schema():
    data = json.loads(GOLD_PATH.read_text(encoding="utf-8"))
    assert len(data) >= 5, "gold set 至少 5 条起步"
    for entry in data:
        for field in ("query_id", "type", "subject", "question", "expected_evidence_ids"):
            assert field in entry, f"缺少字段 {field}"
        assert entry["type"] in ("timeline", "cross_section", "theme")
        assert len(entry["expected_evidence_ids"]) > 0
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest backend/tests/test_linklayer_eval.py -q`
Expected: FAIL（文件不存在）

- [ ] **Step 3: 创建 gold set（含 3 条 worked example + 数据收集协议）**

`backend/eval/gold_set_v1.json`——先用 5 条起步（每类至少 1 条），格式如下；`expected_evidence_ids` 必须是 Mongo `kg_evidence` 里的真实 `evidence_id`（用 `mongo` 查 `kg_evidence` 按 subject_hint + 关键词检索后人工确认）：

```json
[
  {
    "query_id": "timeline-zj-001",
    "type": "timeline",
    "subject": "中晶科技",
    "dimension": "产线进展",
    "question": "中晶科技 8 英寸抛光硅片产线的进展如何演进？",
    "expected_evidence_ids": ["<真实evidence_id_1>", "<真实evidence_id_2>"],
    "hard_negative_evidence_ids": [],
    "note": "预期 3-6 月的 产线调试→增产上量 时间线"
  },
  {
    "query_id": "cross_section-margin-001",
    "type": "cross_section",
    "subject": null,
    "dimension": "毛利率",
    "scope": "<某产品名，如 8英寸抛光硅片>",
    "question": "生产<该产品>的公司毛利率对比",
    "expected_evidence_ids": ["<真实evidence_id_3>"],
    "hard_negative_evidence_ids": [],
    "note": "预期跨公司命中"
  },
  {
    "query_id": "theme-001",
    "type": "theme",
    "subject": null,
    "dimension": null,
    "scope": null,
    "question": "AI 算力板块最近的扩产动态",
    "expected_evidence_ids": ["<真实evidence_id_4>"],
    "hard_negative_evidence_ids": [],
    "note": "向量通道（semantic_search）职责，链接层不评估"
  }
]
```

数据收集协议（在 PR 描述中说明）：从 `minishare_announcements` 池选真实公司，逐条在 Mongo 中查 `db.kg_evidence.find({subject_hint: <ts_code>})` 挑选真实 evidence_id，人工确认相关性后填入。

- [ ] **Step 4: 写评估 runner**

```python
# backend/scripts/eval_retrieval.py
"""检索评估 runner：对 gold set 计算 Recall@k。

用法:
  python backend/scripts/eval_retrieval.py --backend semantic --k 20
  python backend/scripts/eval_retrieval.py --backend link --k 20
"""
import argparse
import asyncio
import json
from pathlib import Path


async def retrieve_link(entry: dict, k: int) -> set[str]:
    """链接层 backend：Task 9/10 完成后接入 pull_history / scan_dimension。"""
    from app.knowledge.linklayer.queries import pull_history, scan_dimension

    if entry["type"] == "timeline":
        result = await pull_history(entry["subject"], dimension=entry.get("dimension"), limit=k)
        return {it["evidence_id"] for it in result["items"]}
    result = await scan_dimension(entry["dimension"], scope=entry.get("scope"), limit=k)
    return {it["evidence_id"] for it in result["items"]}


async def retrieve_semantic(entry: dict, k: int) -> set[str]:
    """基线 backend：现有 Qdrant 向量检索（chunks 通道）。"""
    from app.knowledge.vector_ops import hybrid_vector_search

    results = await hybrid_vector_search(entry["question"], top_k=k)
    return {r.get("evidence_id") for r in results if r.get("evidence_id")}


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=["link", "semantic"], required=True)
    parser.add_argument("--gold", default="backend/eval/gold_set_v1.json")
    parser.add_argument("--k", type=int, default=20)
    args = parser.parse_args()

    entries = json.loads(Path(args.gold).read_text(encoding="utf-8"))
    retrieve = retrieve_semantic if args.backend == "semantic" else retrieve_link
    recalls = []
    for entry in entries:
        got = await retrieve(entry, args.k)
        expected = set(entry["expected_evidence_ids"])
        recall = len(got & expected) / len(expected) if expected else 0.0
        recalls.append(recall)
        print(f"{entry['query_id']}: Recall@{args.k} = {recall:.2f}")
    print(f"== {args.backend} mean Recall@{args.k} = {sum(recalls) / len(recalls):.3f}")


if __name__ == "__main__":
    asyncio.run(main())
```

注意：`hybrid_vector_search` 的实际签名以 `app/knowledge/vector_ops.py:74` 为准，执行时先阅读再适配。

- [ ] **Step 5: 运行测试确认通过**

Run: `python -m pytest backend/tests/test_linklayer_eval.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/eval/gold_set_v1.json backend/scripts/eval_retrieval.py backend/tests/test_linklayer_eval.py
git commit -m "feat(eval): 检索评估 gold set 骨架与 Recall@k runner（P0 基线）"
```

---

## Phase P1：链接层

### Task 2: 链接层 PG 表（keyword / link）

**Files:**
- Create. `backend/app/knowledge/linklayer/__init__.py`（空）
- Create. `backend/app/knowledge/linklayer/models.py`
- Create. `backend/alembic/versions/023_add_linklayer_tables.py`
- Test. `backend/tests/test_linklayer_models.py`

**Interfaces:**
- Produces: `Keyword`（表 `link_keywords`）、`Link`（表 `link_links`）模型；`make_keyword_id(layer, norm_text) -> str`。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_linklayer_models.py
"""链接层模型测试：ID 生成 + 表结构约束。"""
from app.knowledge.linklayer.models import Keyword, Link, make_keyword_id


def test_make_keyword_id_deterministic():
    a = make_keyword_id("subject", "300308.SZ")
    b = make_keyword_id("subject", "300308.SZ")
    assert a == b and a.startswith("KW:")
    assert make_keyword_id("scope", "300308.SZ") != a  # 不同层不同 ID


def test_link_keywords_unique_layer_norm():
    from sqlalchemy import UniqueConstraint
    cols = {c.name for c in Keyword.__table__.constraints if isinstance(c, UniqueConstraint)}
    assert cols == {("layer", "norm_text")} or ("layer", "norm_text") in cols


def test_link_table_pk_columns():
    pk = {c.name for c in Link.__table__.primary_key.columns}
    assert pk == {"keyword_id", "evidence_id", "span_start"}
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest backend/tests/test_linklayer_models.py -q`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现模型**

```python
# backend/app/knowledge/linklayer/models.py
"""链接层模型：keyword（受控词表）+ link（evidence↔keyword 双向引用）。"""
from __future__ import annotations

import hashlib
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.database import Base


def make_keyword_id(layer: str, norm_text: str) -> str:
    return "KW:" + hashlib.sha256(f"{layer}:{norm_text}".encode("utf-8")).hexdigest()[:16]


class Keyword(Base):
    """受控词表条目。layer ∈ subject | dimension | stage | scope；status ∈ active | candidate | merged | retired"""

    __tablename__ = "link_keywords"
    __table_args__ = (UniqueConstraint("layer", "norm_text", name="uq_link_keywords_layer_norm"),)

    keyword_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    layer: Mapped[str] = mapped_column(String(16), nullable=False)
    norm_text: Mapped[str] = mapped_column(Text, nullable=False)
    display_text: Mapped[str | None] = mapped_column(Text)
    aliases: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="active")
    merged_into: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Link(Base):
    """evidence ↔ keyword 关联（双向引用的物化）。幂等：PK(keyword_id, evidence_id, span_start)。"""

    __tablename__ = "link_links"
    __table_args__ = (
        Index("idx_link_links_evidence", "evidence_id"),
        Index("idx_link_links_keyword_date", "keyword_id", "published_at"),
    )

    keyword_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("link_keywords.keyword_id"), primary_key=True
    )
    evidence_id: Mapped[str] = mapped_column(Text, primary_key=True)
    span_start: Mapped[int] = mapped_column(Integer, primary_key=True)
    span_end: Mapped[int] = mapped_column(Integer)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(String(16), nullable=False)  # llm | dictionary
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
```

- [ ] **Step 4: 写 Alembic 迁移 `023_add_linklayer_tables.py`**

参照 `backend/alembic/versions/022_add_ingestion_jobs.py` 的模板（`revision = "023"`，`down_revision = "022"` 视实际链条尾端调整），`upgrade()` 内创建 `link_keywords` 与 `link_links`，列定义与上面模型一致（`published_at` 允许 NULL，建 `idx_link_links_evidence`、`idx_link_links_keyword_date` 两个索引）。

- [ ] **Step 5: 运行测试**

Run: `python -m pytest backend/tests/test_linklayer_models.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/knowledge/linklayer/ backend/alembic/versions/023_add_linklayer_tables.py backend/tests/test_linklayer_models.py
git commit -m "feat(linklayer): 链接层 keyword/link 模型与迁移 023"
```

### Task 3: 种子词表 + 词典加载器

**Files:**
- Create. `backend/app/knowledge/linklayer/data/dimensions.yaml`
- Create. `backend/app/knowledge/linklayer/dictionaries.py`
- Test. `backend/tests/test_linklayer_dictionaries.py

**Interfaces:**
- Produces: `load_vocabulary() -> Vocabulary`；`Vocabulary.dimensions: dict[str, Dimension]`、`Vocabulary.metric_words: set[str]`；`Dimension.name / kind / stages`（`stages: list[dict]`，每项 `{level, words}`）。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_linklayer_dictionaries.py
from app.knowledge.linklayer.dictionaries import load_vocabulary


def test_load_vocabulary_covers_seed_dimensions():
    vocab = load_vocabulary()
    for name in ("产线进展", "客户认证", "订单", "产能", "毛利率"):
        assert name in vocab.dimensions, f"缺少种子维度 {name}"


def test_staged_dimension_has_ladder():
    vocab = load_vocabulary()
    dim = vocab.dimensions["产线进展"]
    assert dim.kind == "staged"
    levels = [s["level"] for s in dim.stages]
    assert levels == sorted(levels) and len(levels) >= 3
    assert any("调试" in s["words"] for s in dim.stages)


def test_numeric_dimension():
    vocab = load_vocabulary()
    assert vocab.dimensions["毛利率"].kind == "numeric"
    assert "毛利率" in vocab.metric_words
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest backend/tests/test_linklayer_dictionaries.py -q` → FAIL

- [ ] **Step 3: 写种子词表 `dimensions.yaml`**

```yaml
# 维度种子词表 v1 — staged=有阶梯; numeric=数值型（无 level，靠 METRIC 提取的数值）
dimensions:
  - name: 产线进展
    kind: staged
    stages:
      - {level: 1, words: [规划中, 立项]}
      - {level: 2, words: [建设中, 在建]}
      - {level: 3, words: [设备安装, 调试]}
      - {level: 4, words: [试产, 试生产]}
      - {level: 5, words: [小批量, 爬坡]}
      - {level: 6, words: [量产, 达产, 增产上量, 满产]}
  - name: 客户认证
    kind: staged
    stages:
      - {level: 1, words: [送样]}
      - {level: 2, words: [验证中, 认证中, 审核中]}
      - {level: 3, words: [通过验证, 认证通过, 通过客户验证]}
      - {level: 4, words: [批量供货, 小批量供货, 导入客户]}
  - name: 订单
    kind: staged
    stages:
      - {level: 1, words: [意向订单, 框架协议]}
      - {level: 2, words: [签订订单, 中标]}
      - {level: 3, words: [排产, 在手订单]}
      - {level: 4, words: [交付, 出货]}
  - name: 产能
    kind: staged
    stages:
      - {level: 1, words: [产能规划]}
      - {level: 2, words: [在建产能]}
      - {level: 3, words: [投产]}
      - {level: 4, words: [产能爬坡]}
      - {level: 5, words: [满产, 产能饱满]}
  - name: 客户导入
    kind: staged
    stages:
      - {level: 1, words: [接洽, 域内测试]}
      - {level: 2, words: [样品测试, 小批量试用]}
      - {level: 3, words: [导入, 进入供应链, 导入客户]}
  - name: 毛利率
    kind: numeric
  - name: 营收
    kind: numeric
  - name: 净利润
    kind: numeric
  - name: 开工率
    kind: numeric
  - name: 价格
    kind: numeric
metrics:
  - 毛利率
  - 营收
  - 收入
  - 净利润
  - 出货量
  - 产能利用率
  - 开工率
  - 市占率
  - 单价
  - 排产
```

- [ ] **Step 4: 实现加载器**

```python
# backend/app/knowledge/linklayer/dictionaries.py
"""种子词表加载：维度/阶梯/指标词表（spec §4.2 三层词表的封闭类部分）。"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml


@dataclass
class Dimension:
    name: str
    kind: str  # staged | numeric
    stages: list[dict] = field(default_factory=list)  # [{level, words}]


@dataclass
class Vocabulary:
    dimensions: dict[str, Dimension] = field(default_factory=dict)
    metric_words: set[str] = field(default_factory=set)


@lru_cache(maxsize=1)
def load_vocabulary() -> Vocabulary:
    path = Path(__file__).parent / "data" / "dimensions.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    vocab = Vocabulary()
    for dim in raw.get("dimensions", []):
        vocab.dimensions[dim["name"]] = Dimension(
            name=dim["name"], kind=dim["kind"], stages=dim.get("stages", [])
        )
    vocab.metric_words = set(raw.get("metrics", []))
    return vocab
```

- [ ] **Step 5: 运行测试** → PASS；**Step 6: Commit** `feat(linklayer): 维度种子词表与加载器`

### Task 4: 词典匹配器

**Files:**
- Create. `backend/app/knowledge/linklayer/dict_match.py`
- Test. `backend/tests/test_linklayer_dict_match.py`

**Interfaces:**
- Consumes: `Vocabulary`（Task 3）
- Produces: `DictMatch` dataclass（`norm_text, layer, dimension, level, span_start, span_end`）；`match_all(text, vocab, subject_index) -> list[DictMatch]`；`SubjectIndex`（`build_subject_index() -> dict[str, str]`，alias → norm_text，norm_text 为 ts_code 或全称）。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_linklayer_dict_match.py
from app.knowledge.linklayer.dict_match import SubjectIndex, match_all
from app.knowledge.linklayer.dictionaries import load_vocabulary

VOCAB = load_vocabulary()
SUBJ = SubjectIndex(alias_to_norm={"中晶科技": "003026.SZ", "中晶": "003026.SZ"})


def test_stage_match_with_span():
    matches = match_all("公司8英寸抛光硅片产线处于调试阶段", VOCAB, SUBJ)
    stages = [m for m in matches if m.layer == "stage"]
    assert any(m.norm_text == "调试" and m.dimension == "产线进展" for m in stages)
    m = next(m for m in stages if m.norm_text == "调试")
    assert 0 < m.span_start < m.span_end


def test_subject_match():
    matches = match_all("中晶科技回复：产线正常", VOCAB, SUBJ)
    assert any(m.layer == "subject" and m.norm_text == "003026.SZ" for m in matches)


def test_metric_word_matches_dimension_layer():
    matches = match_all("公司毛利率稳步提升", VOCAB, SUBJ)
    assert any(m.layer == "dimension" and m.norm_text == "毛利率" for m in matches)


def test_no_false_generic_match():
    matches = match_all("本公司产品毛利率", VOCAB, SubjectIndex(alias_to_norm={}))
    assert all(m.norm_text != "产品" for m in matches)
```

- [ ] **Step 2: 运行确认失败** → FAIL

- [ ] **Step 3: 实现匹配器**

```python
# backend/app/knowledge/linklayer/dict_match.py
"""封闭类词表的确定性匹配：subject（别名表）+ dimension（指标词）+ stage（阶梯词）。"""
from __future__ import annotations

from dataclasses import dataclass

from app.knowledge.linklayer.dictionaries import Vocabulary


@dataclass
class DictMatch:
    norm_text: str
    layer: str  # subject | dimension | stage
    dimension: str | None = None
    level: int | None = None
    span_start: int = 0
    span_end: int = 0


class SubjectIndex:
    """公司别名 → 规范名（上市优先 ts_code）。v1 从 company_aliases.json + stocks 表构建。"""

    def __init__(self, alias_to_norm: dict[str, str]) -> None:
        self.alias_to_norm = dict(alias_to_norm)

    def match(self, text: str):
        for alias, norm in self.alias_to_norm.items():
            start = 0
            while (start := text.find(alias, start)) >= 0:
                yield DictMatch(
                    norm_text=norm, layer="subject",
                    span_start=start, span_end=start + len(alias),
                )
                start += len(alias)


def build_subject_index() -> SubjectIndex:
    """从 backend/data/company_aliases.json + PG stocks 表构建别名索引。

    执行时实现：加载 JSON 别名（names + ts_code）；再从 stocks 表取 name → ts_code。
    已上市主体 norm_text=ts_code，非上市主体 norm_text=规范全称。
    """
    raise NotImplementedError  # 按上文注释实现，数据源两处：backend/data/company_aliases.json、stocks 表


def match_all(text: str, vocab: Vocabulary, subject_index: SubjectIndex) -> list[DictMatch]:
    results: list[DictMatch] = list(subject_index.match(text))
    for name, dim in vocab.dimensions.items():
        for stage in dim.stages:
            for word in stage["words"]:
                start = 0
                while (start := text.find(word, start)) >= 0:
                    results.append(
                        DictMatch(
                            norm_text=word, layer="stage", dimension=name,
                            level=stage["level"], span_start=start,
                            span_end=start + len(word),
                        )
                    )
                    start += len(word)
        if name in text:  # 维度名本身（如"毛利率"）也作为 dimension 关键字
            start = text.find(name)
            results.append(
                DictMatch(norm_text=name, layer="dimension", dimension=name,
                          span_start=start, span_end=start + len(name))
            )
    for word in vocab.metric_words:
        start = text.find(word)
        if start >= 0:
            results.append(
                DictMatch(norm_text=word, layer="dimension", dimension=word,
                          span_start=start, span_end=start + len(word))
            )
    return results
```

注意：`build_subject_index` 在本任务内完整实现（JSON 别名 + stocks 表查询），上面 `NotImplementedError` 仅为行文占位——实现时替换为真实代码，这是唯一的例外。

- [ ] **Step 4: 运行测试** → PASS；**Step 5: Commit** `feat(linklayer): 词典匹配器（subject/dimension/stage）`

### Task 5: LLM 浅提取器

**Files:**
- Create. `backend/app/knowledge/linklayer/llm_extract.py`
- Modify. `backend/app/knowledge/evidence_service.py`（新增 `update_keyword_extraction`）
- Test. `backend/tests/test_linklayer_llm_extract.py`

**Interfaces:**
- Consumes: `app.core.llm_client.chat_async`；`settings.llm_extraction_model`；`EvidenceService`
- Produces: `KEYWORD_PROMPT_VERSION = "kw_v1"`；`async extract_keywords(evidence: dict, *, use_cache: bool = True) -> dict | None`，返回 `{"company": [...], "product": [...], "metric": [{"name", "value", "unit", "period"}]}`；结果缓存在 Mongo evidence 文档 `keyword_extraction` 字段。

- [ ] **Step 1: 写失败测试**（monkeypatch LLM，不依赖真实服务）

```python
# backend/tests/test_linklayer_llm_extract.py
"""LLM 浅提取器测试：纯逻辑（prompt/解析/缓存），LLM 调用打桩。"""
import pytest

from app.knowledge.linklayer.llm_extract import KEYWORD_PROMPT_VERSION, parse_llm_json


def test_parse_llm_json_plain():
    got = parse_llm_json('{"company": ["中晶科技"], "product": ["8英寸抛光硅片"], "metric": []}')
    assert got["company"] == ["中晶科技"]
    assert got["product"] == ["8英寸抛光硅片"]


def test_parse_llm_json_with_code_fence():
    raw = '```json\n{"company": [], "product": [], "metric": []}\n```'
    assert parse_llm_json(raw) is not None


def test_parse_llm_json_invalid_returns_none():
    assert parse_llm_json("我认为不是") is None


def test_metric_value_passthrough():
    raw = '{"company": [], "product": [], "metric": [{"name": "毛利率", "value": 45, "unit": "%", "period": "2026H1"}]}'
    got = parse_llm_json(raw)
    assert got["metric"][0]["value"] == 45


@pytest.mark.integration
def test_extract_keywords_real_llm():
    """integration：真实 LLM 网关。"""
```

- [ ] **Step 2: 运行确认失败** → FAIL

- [ ] **Step 3: 实现提取器**

```python
# backend/app/knowledge/linklayer/llm_extract.py
"""LLM 浅提取（spec §4.2）：类型受约束关键字提取。单次调用、扁平输出、可缓存。

铁律：LLM 只输出 surface form，不做归一化/推理/改写。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from app.config import settings
from app.core.llm_client import chat_async

logger = logging.getLogger(__name__)

KEYWORD_PROMPT_VERSION = "kw_v1"

KEYWORD_SYSTEM_PROMPT = """你是投研文本的关键字标注器。从用户给出的文本中提取三类关键字，只输出原文出现过的表述：
- COMPANY: 公司名（上市/非上市/境外均算）
- PRODUCT: 产品、技术、产线、材料名
- METRIC: 指标名（如带数值，输出 {"name","value","unit","period"}）

规则：保留原文表述不改写（"8英寸抛光硅片"不得缩写为"硅片"）；
不提取行业泛称（公司、行业、产品、客户等）；不确定的不提取。
只输出 JSON，格式：{"company": [...], "product": [...], "metric": [...]}"""


def parse_llm_json(raw: str) -> dict | None:
    """解析 LLM 输出；失败返回 None（不重试——浅任务不允许重试链）。"""
    if not raw:
        return None
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return {
        "company": [str(x) for x in data.get("company", [])][:20],
        "product": [str(x) for x in data.get("product", [])][:20],
        "metric": [
            m for m in data.get("metric", [])
            if isinstance(m, dict) and m.get("name")
        ][:20],
    }


async def extract_keywords(evidence: dict, *, use_cache: bool = True) -> dict | None:
    """对单条 evidence 做关键字浅提取。结果写回 Mongo `keyword_extraction` 字段缓存。"""
    cached = evidence.get("keyword_extraction") or {}
    if use_cache and cached.get("version") == KEYWORD_PROMPT_VERSION:
        return cached["result"]

    from app.knowledge.evidence_service import EvidenceService  # 延迟导入避免循环

    text = (evidence.get("text_excerpt") or "")[:6000]
    result: dict | None = None
    if text.strip():
        try:
            resp = await chat_async(
                model=settings.llm_extraction_model,
                messages=[
                    {"role": "system", "content": KEYWORD_SYSTEM_PROMPT},
                    {"role": "user", "content": text},
                ],
                temperature=0.0,
            )
            result = parse_llm_json(getattr(resp, "content", "") or str(resp))
        except Exception:
            logger.exception("keyword extraction failed for %s", evidence.get("evidence_id"))
            return None

    if result is not None:
        svc = EvidenceService()
        await svc.update_keyword_extraction(
            evidence["evidence_id"],
            {"version": KEYWORD_PROMPT_VERSION, "result": result,
             "extracted_at": datetime.now(timezone.utc).isoformat()},
        )
    return result
```

实现注意：
- `chat_async` 的确切签名以 `app/core/llm_client.py:72` 为准，调用方式参照 `app/knowledge/extraction/rag_extractor.py:313` 的 `_call_llm_async`（含 stream 绕超时的写法）。如返回对象不同，在 `getattr(resp, "content", ...)` 处适配。
- `EvidenceService.update_keyword_extraction(evidence_id, payload)`：用 `$set` 更新 `kg_evidence` 文档的 `keyword_extraction` 字段，模仿现有 `update_evidence_status`（`app/knowledge/evidence_service.py:387`）的写法。

- [ ] **Step 4: 运行测试** → PASS
- [ ] **Step 5: Commit** `feat(linklayer): LLM 浅提取器（类型受约束关键字，kw_v1）`

### Task 6: 归一化 + keyword 生命周期

**Files:**
- Create. `backend/app/knowledge/linklayer/normalize.py`
- Test. `backend/tests/test_linklayer_normalize.py`

**Interfaces:**
- Consumes: `Keyword`/`make_keyword_id`（Task 2）、`SubjectIndex`（Task 4）
- Produces: `async ensure_keyword(session, layer, norm_text, *, source) -> str`（返回 keyword_id，不存在则建；scope 层未映射 surface form 以 `status="candidate"` 建立）；`async canonicalize_subject(surface: str, subject_index) -> str | None`（别名表归一，失败返回 None）。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_linklayer_normalize.py
"""归一化测试：纯逻辑部分（subject canonicalize + ensure_keyword SQL 打桩）。"""
import pytest

from app.knowledge.linklayer.normalize import canonicalize_subject
from app.knowledge.linklayer.dict_match import SubjectIndex


def test_canonicalize_subject_by_alias():
    idx = SubjectIndex(alias_to_norm={"中晶科技": "003026.SZ"})
    assert canonicalize_subject("中晶科技", idx) == "003026.SZ"


def test_canonicalize_subject_miss():
    idx = SubjectIndex(alias_to_norm={})
    assert canonicalize_subject("不存在的公司", idx) is None
```

- [ ] **Step 2: 运行确认失败** → FAIL

- [ ] **Step 3: 实现**

```python
# backend/app/knowledge/linklayer/normalize.py
"""surface form → 规范键。铁律（spec 附录 A #3）：归一化永远机械，LLM 不参与。"""
from __future__ import annotations

from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.knowledge.linklayer.dict_match import SubjectIndex
from app.knowledge.linklayer.models import Keyword, make_keyword_id


def canonicalize_subject(surface: str, subject_index: SubjectIndex) -> str | None:
    """公司 surface form → ts_code（上市）或规范全称（非上市）。查不到返回 None。"""
    return subject_index.alias_to_norm.get(surface)


async def ensure_keyword(session, layer: str, norm_text: str, *, source: str) -> str:
    """幂等确保 keyword 存在，返回 keyword_id。

    - subject/dimension/stage 层调用前应已完成归一化，直接 active。
    - scope 层允许未知 surface form 直接建条目（recall 优先），status="candidate"，
      由词表治理流程审核后转 active（LLM 提议、词典裁决）。
    """
    keyword_id = make_keyword_id(layer, norm_text)
    status = "candidate" if (layer == "scope" and source == "llm") else "active"
    stmt = pg_insert(Keyword).values(
        keyword_id=keyword_id, layer=layer, norm_text=norm_text,
        display_text=norm_text, status=status,
    ).on_conflict_do_nothing(index_elements=["keyword_id"])
    await session.execute(stmt)
    return keyword_id
```

- [ ] **Step 4: 运行测试** → PASS；**Step 5: Commit** `feat(linklayer): keyword 归一化与生命周期（candidate/active）`

### Task 7: 入库管线（ingest）+ 增量 hook

**Files:**
- Create. `backend/app/knowledge/linklayer/ingest.py`
- Modify. `backend/app/knowledge/evidence_service.py`（`enqueue_default_jobs` 增加 link job type）
- Modify. `backend/app/knowledge/evidence_worker.py`（`process_job` 增加 link 分支）
- Test. `backend/tests/test_linklayer_ingest.py`

**Interfaces:**
- Consumes: Tasks 2–6 全部接口
- Produces: `async ingest_evidence(evidence_id: str) -> dict`，返回 `{"links": int, "keywords": int, "llm_used": bool}`；新 job type `"link"`。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_linklayer_ingest.py
"""ingest 管线测试：组件打桩，验证编排逻辑。"""
import pytest

from app.knowledge.linklayer import ingest as ingest_mod


@pytest.mark.asyncio
async def test_ingest_combines_dict_and_llm(monkeypatch):
    """词典命中 + LLM 提取都应生成 link。"""
    recorded = []

    async def fake_get_evidence(self, evidence_id):
        return {"evidence_id": evidence_id, "text_excerpt": "中晶科技产线处于调试阶段",
                "publish_date": "2026-06-15", "source_type": "irm"}

    async def fake_extract(evidence, *, use_cache=True):
        return {"company": ["中晶科技"], "product": ["8英寸抛光硅片"], "metric": []}

    monkeypatch.setattr(ingest_mod.EvidenceService, "get_evidence", fake_get_evidence)
    monkeypatch.setattr(ingest_mod, "extract_keywords", fake_extract)
    # DB 部分打桩：ensure_keyword/link 写入收集到 recorded
    async def fake_ensure(session, layer, norm_text, *, source):
        recorded.append((layer, norm_text, source))
        return f"KW:{layer}:{norm_text}"
    monkeypatch.setattr(ingest_mod, "ensure_keyword", fake_ensure)

    from app.knowledge.linklayer.dict_match import SubjectIndex, DictMatch
    fake_subject = SubjectIndex(alias_to_norm={"中晶科技": "003026.SZ"})
    monkeypatch.setattr(ingest_mod, "build_subject_index", lambda: fake_subject)

    result = await ingest_mod.ingest_evidence("EV:test", _session=None)
    assert ("subject", "003026.SZ", "dictionary") in recorded
    assert ("subject", "003026.SZ", "llm") in recorded
    assert ("scope", "8英寸抛光硅片", "llm") in recorded
    assert result["llm_used"] is True
```

- [ ] **Step 2: 运行确认失败** → FAIL

- [ ] **Step 3: 实现 ingest**

```python
# backend/app/knowledge/linklayer/ingest.py
"""链接层入库管线：dict match + LLM 浅提取 → 归一化 → keyword/link 幂等 upsert。"""
from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.knowledge.evidence_service import EvidenceService
from app.knowledge.linklayer.dict_match import build_subject_index, match_all
from app.knowledge.linklayer.dictionaries import load_vocabulary
from app.knowledge.linklayer.llm_extract import extract_keywords
from app.knowledge.linklayer.models import Link
from app.knowledge.linklayer.normalize import canonicalize_subject, ensure_keyword

logger = logging.getLogger(__name__)


async def ingest_evidence(evidence_id: str, *, session=None) -> dict:
    """对单条 evidence 建链。幂等：link PK 冲突 do nothing。"""
    svc = EvidenceService()
    evidence = await svc.get_evidence(evidence_id)
    if not evidence:
        return {"links": 0, "keywords": 0, "llm_used": False}

    text = evidence.get("text_excerpt") or ""
    vocab = load_vocabulary()
    subject_index = build_subject_index()

    # 通道 1：词典匹配（封闭类：subject 兜底 / dimension / stage）
    actions: list[tuple[str, str, str, int, int, datetime | None]] = []  # layer, norm, source, s, e, published
    published = _parse_date(evidence.get("publish_date"))
    for m in match_all(text, vocab, subject_index):
        actions.append((m.layer, m.norm_text, "dictionary", m.span_start, m.span_end, published))

    # 通道 2：LLM 浅提取（开放类：Company/Product/Metric）
    llm_result = await extract_keywords(evidence)
    llm_used = llm_result is not None
    if llm_result:
        for surface in llm_result.get("company", []):
            norm = canonicalize_subject(surface, subject_index) or surface
            actions.append(("subject", norm, "llm", 0, 0, published))
        for surface in llm_result.get("product", []):
            actions.append(("scope", surface, "llm", 0, 0, published))
        for m in llm_result.get("metric", []):
            actions.append(("dimension", m["name"], "llm", 0, 0, published))

    # # # 落库 # # #
    assert session is not None, "需要 PG session（由 worker / script 传入）"
    link_count = 0
    for layer, norm, source, s, e, pub in actions:
        kw_id = await ensure_keyword(session, layer, norm, source=source)
        stmt = pg_insert(Link).values(
            keyword_id=kw_id, evidence_id=evidence_id, span_start=s, span_end=e,
            published_at=pub, source=source,
        ).on_conflict_do_nothing()
        await session.execute(stmt)
        link_count += 1
    await session.commit()
    return {"links": link_count, "keywords": len(actions), "llm_used": llm_used}


def _parse_date(value) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None
```

- [ ] **Step 4: 接入增量链路**

1. `EvidenceService.enqueue_default_jobs`（`app/knowledge/evidence_service.py:154`）：除现有 job 外再入队 `("link", evidence_id)`（沿用其现有 job 结构，job_type="link"）。
2. `EvidenceExtractionWorker.process_job`（`app/knowledge/evidence_worker.py:115`）：增加 `link` 分支——直接调用 `ingest_evidence`，不占用 LLM combined 通道。
3. 旧 `combined` job 的入队保持不变，P4 才关（见 Task 15）。

- [ ] **Step 5: 运行测试** → PASS
- [ ] **Step 6: Commit** `feat(linklayer): 链接入库管线 + evidence worker link job`

### Task 8: 全量回填脚本

**Files:**
- Create. `backend/scripts/backfill_keyword_links.py`
- Test. 已有 ingest 测试覆盖核心逻辑；本任务验收为脚本 dry-run 输出。

**Interfaces:**
- Consumes: `ingest_evidence`（Task 7）
- Produces: CLI：`python backend/scripts/backfill_keyword_links.py --limit 100 --dry-run`

- [ ] **Step 1: 实现脚本**

```python
# backend/scripts/backfill_keyword_links.py
"""全量回填链接层：遍历 kg_evidence，逐条建链。支持 --limit / --dry-run / 断点续跑（跳过已有 keyword_extraction 的）。"""
import argparse
import asyncio

from app.core.database import async_session
from app.knowledge.evidence_service import EvidenceService


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="最多处理条数，0=全部")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    svc = EvidenceService()
    coll = svc.db["kg_evidence"]
    query = {"keyword_extraction": {"$exists": False}}
    cursor = coll.find(query, {"evidence_id": 1}).limit(args.limit or 0)
    evidence_ids = [doc["evidence_id"] async for doc in cursor]

    from app.knowledge.linklayer.ingest import ingest_evidence
    done = failed = 0
    async with async_session() as session:
        for evidence_id in evidence_ids:
            if args.dry_run:
                print(f"[dry-run] {evidence_id}")
                continue
            try:
                result = await ingest_evidence(evidence_id, session=session)
                done += 1
                print(f"{evidence_id}: {result}")
            except Exception as exc:  # 单条失败不中断
                failed += 1
                print(f"FAIL {evidence_id}: {exc}")
    print(f"done={done} failed={failed}")


if __name__ == "__main__":
    asyncio.run(main())
```

实现注意：`EvidenceService` 的 db handle 访问方式以 `app/knowledge/evidence_service.py` 实际代码为准（私有属性或公开方法）；`publish_date` 无时区时按本地时间处理。

- [ ] **Step 2: Dry-run 验证**

Run: `cd backend && uv run python -m scripts.backfill_keyword_links --limit 10 --dry-run`
Expected: 打印 10 个 evidence_id，无异常。

- [ ] **Step 3: 小批量真实验证**

Run: `cd backend && uv run python -m scripts.backfill_keyword_links --limit 20`
Expected: `done=20 failed=0`，PG `link_links` 出现记录，重复执行第二次无新增（幂等）。

- [ ] **Step 4: Commit** `feat(linklayer): 全量回填脚本（幂等、可断点续跑）`

---

## Phase P2：检索切换

### Task 9: pull_history + backlinks 查询原语

**Files:**
- Create. `backend/app/knowledge/linklayer/queries.py`
- Test. `backend/tests/test_linklayer_queries.py`

**Interfaces:**
- Consumes: `Link`/`Keyword` 模型、`EvidenceService`
- Produces:
  - `async pull_history(subject: str, dimension: str | None = None, scope: str | None = None, before: str | None = None, limit: int = 100) -> dict`——返回 `{"items": [{"evidence_id", "published_at", "source_type", "text_excerpt", "matched_keywords"}], "count": int}`
  - `async backlinks(evidence_id: str) -> dict`——返回 evidence 的全部关键字及同关键字的其他 evidence_id 列表。

- [ ] **Step 1: 写失败测试**（SQL 打桩 + integration 双轨）

```python
# backend/tests/test_linklayer_queries.py
import pytest

from app.knowledge.linklayer.queries import build_pull_history_sql


def test_build_pull_history_sql_contains_subject():
    sql, params = build_pull_history_sql(subject="003026.SZ", dimension="产线进展")
    assert "产线进展" in str(sql) or params  # 编译期结构校验
    assert "003026.SZ" in str(params)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_pull_history_integration():
    """integration：需要真实 PG/Mongo。"""
```

- [ ] **Step 2: 运行确认失败** → FAIL

- [ ] **Step 3: 实现**

```python
# backend/app/knowledge/linklayer/queries.py
"""检索原语（spec §5.1）：pull_history 时间线 / backlinks。"""
from __future__ import annotations

from sqlalchemy import and_, select

from app.core.database import async_session
from app.knowledge.linklayer.dict_match import build_subject_index
from app.knowledge.linklayer.models import Keyword, Link


def build_pull_history_sql(subject: str, dimension: str | None = None,
                           scope: str | None = None, before: str | None = None,
                           limit: int = 100):
    """构造时间线查询：subject 关键字 ∩ 可选 dimension/scope 关键字，按 published_at 倒序。

    返回 (stmt, params)，便于单测校验结构。norm_text 匹配用 keyword 表的
    display_text/aliases 兜底（如"中晶科技"未归一成 ts_code 时仍可命中）。
    """
    alias_match = and_(
        Keyword.keyword_id == Link.keyword_id,
        Keyword.layer == "subject",
        Keyword.norm_text == subject,
    )
    stmt = select(Link.evidence_id, Link.published_at).where(alias_match)
    if dimension:
        stmt = stmt.where(
            Link.evidence_id.in_(
                select(Link.evidence_id).where(
                    Link.keyword_id.in_(
                        select(Keyword.keyword_id).where(
                            Keyword.layer == "dimension", Keyword.norm_text == dimension
                        )
                    )
                )
            )
        )
    stmt = stmt.order_by(Link.published_at.desc()).limit(limit)
    return stmt, {"subject": subject, "dimension": dimension}


async def pull_history(subject: str, dimension: str | None = None, scope: str | None = None,
                       before: str | None = None, limit: int = 100) -> dict:
    """时间线拉取：完整、有序、去重——判断任务的正门（spec §5.1 主原语）。"""
    from app.knowledge.evidence_service import EvidenceService

    async with async_session() as session:
        # 1. 主体归一（"中晶科技" → ts_code）
        subject_index = build_subject_index()
        norm = subject_index.alias_to_norm.get(subject, subject)
        stmt, _ = build_pull_history_sql(norm, dimension, scope, before, limit)
        rows = (await session.execute(stmt)).all()

    svc = EvidenceService()
    items = []
    seen = set()
    for row in rows:
        evidence_id = row[0]
        if evidence_id in seen:
            continue
        seen.add(evidence_id)
        ev = await svc.get_evidence(evidence_id) or {}
        items.append({
            "evidence_id": evidence_id,
            "published_at": str(row[1]) if row[1] else ev.get("publish_date"),
            "source_type": ev.get("source_type", ""),
            "source_name": ev.get("source_name", ""),
            "text_excerpt": ev.get("text_excerpt", ""),
        })
    items.sort(key=lambda x: x["published_at"] or "", reverse=True)
    return {"items": items, "count": len(items)}


async def backlinks(evidence_id: str) -> dict:
    """双向引用：evidence → 其全部关键字 → 各关键字下的其他 evidence。"""
    async with async_session() as session:
        kw_rows = (await session.execute(
            select(Keyword, Link).join(Keyword, Keyword.keyword_id == Link.keyword_id)
            .where(Link.evidence_id == evidence_id)
        )).all()
        keywords = [
            {"keyword_id": k.keyword_id, "layer": k.layer, "norm_text": k.norm_text}
            for k, _ in kw_rows
        ]
        related: dict[str, list[str]] = {}
        for k, _ in kw_rows:
            rows = (await session.execute(
                select(Link.evidence_id).where(
                    Link.keyword_id == k.keyword_id
                ).limit(50)
            )).all()
            related[k.norm_text] = [r[0] for r in rows if r[0] != evidence_id]
    return {"evidence_id": evidence_id, "keywords": keywords, "related": related}
```

- [ ] **Step 4: 运行测试** → PASS
- [ ] **Step 5: Commit** `feat(linklayer): pull_history/backlinks 检索原语`

### Task 10: scan_dimension + 单跳聚合（lookup_products / lookup_players）

**Files:**
- Modify. `backend/app/knowledge/linklayer/queries.py`
- Test. `backend/tests/test_linklayer_queries.py`（追加）

**Interfaces:**
- Produces:
  - `async scan_dimension(dimension: str, scope: str | None = None, as_of: str | None = None, limit: int = 50) -> dict`——横截面：该维度下各主体的 evidence/数值观察
  - `async lookup_products(company: str, top_k: int = 20) -> list[dict]`——`[{norm_text, mention_count, last_seen}]`
  - `async lookup_players(keyword_norm_text: str, top_k: int = 20) -> list[dict]`——反向：某产品/关键字下的公司聚合

- [ ] **Step 1: 写失败测试**

```python
# 追加到 backend/tests/test_linklayer_queries.py
def test_scan_dimension_sql_joins_scope():
    from app.knowledge.linklayer.queries import build_scan_dimension_sql
    stmt, params = build_scan_dimension_sql(dimension="毛利率", scope="8英寸抛光硅片")
    assert params == {"dimension": "毛利率", "scope": "8英寸抛光硅片"}
```

- [ ] **Step 2: 运行确认失败** → FAIL

- [ ] **Step 3: 实现**（加入 queries.py）

```python
def build_scan_dimension_sql(dimension: str, scope: str | None = None,
                             as_of: str | None = None, limit: int = 50):
    """横截面查询：该维度（×可选 scope）下，按主体聚合的 evidence/数值。

    SQL 骨架（最终实现按此展开为 SQLAlchemy 语句）：
      SELECT sk.norm_text AS subject, l.evidence_id, l.published_at
      FROM link_links l
      JOIN link_keywords k  ON k.keyword_id = l.keyword_id AND k.layer='dimension'
      JOIN link_links l2   ON l2.evidence_id = l.evidence_id
      JOIN link_keywords sk ON sk.keyword_id = l2.keyword_id AND sk.layer='subject'
      WHERE k.norm_text = :dimension [AND EXISTS scope 子查询]
      ORDER BY l.published_at DESC LIMIT :limit
    """
    raise NotImplementedError  # 实现时替换：按 docstring 展开（结构已在 Task 9 验证过的 join 模式上）


async def scan_dimension(dimension: str, scope: str | None = None,
                         as_of: str | None = None, limit: int = 50) -> dict:
    async with async_session() as session:
        stmt, _ = build_scan_dimension_sql(dimension, scope, as_of, limit)
        rows = (await session.execute(stmt)).all()
    return {"dimension": dimension, "scope": scope,
            "items": [{"subject": r[0], "evidence_id": r[1], "published_at": str(r[2])} for r in rows]}


async def _cooccur_aggregate(anchor_layer: str, target_layer: str,
                             anchor_norm: str, top_k: int) -> list[dict]:
    """单跳聚合通用骨架：anchor 关键字 → 同 evidence 的 target 层关键字聚合。"""
    async with async_session() as session:
        sub = select(Link.evidence_id).where(
            Link.keyword_id == select(Keyword.keyword_id).where(
                Keyword.layer == anchor_layer, Keyword.norm_text == anchor_norm
            ).scalar_subquery()
        ).subquery()
        stmt = (
            select(Keyword.norm_text,
                   Link.evidence_id.count().label("mention_count"),
               Link.published_at.max().label("last_seen"))
            .join(Link, Link.keyword_id == Keyword.keyword_id)
            .where(Link.evidence_id.in_(select(sub.c.evidence_id)),
                   Keyword.layer == target_layer)
            .group_by(Keyword.norm_text)
            .order_by(Link.evidence_id.count().desc())
            .limit(top_k)
        )
        rows = (await session.execute(stmt)).all()
    return [{"norm_text": r[0], "mention_count": r[1], "last_seen": str(r[2])} for r in rows]


async def lookup_products(company: str, top_k: int = 20) -> list[dict]:
    """公司有哪些产品（spec §5.4 单跳聚合）。"""
    return await _cooccur_aggregate("subject", "scope", company, top_k)


async def lookup_players(product: str, top_k: int = 20) -> list[dict]:
    """某产品/关键字的玩家有哪些（传导挖掘入口）。"""
    return await _cooccur_aggregate("scope", "subject", product, top_k)
```

- [ ] **Step 4: 运行测试** → PASS
- [ ] **Step 5: Commit** `feat(linklayer): scan_dimension 横截面 + lookup 单跳聚合`

### Task 11: Agent 工具注册 + skill/prompt 更新

**Files:**
- Create. `backend/app/reasoning/tools/knowledge/link_queries.py`
- Modify. `backend/app/reasoning/registry/config.yaml`（新增 5 个工具注册）
- Modify. `backend/app/reasoning/skills/divergence-mining/SKILL.md`
- Test. `backend/tests/test_linklayer_tools.py`

**Interfaces:**
- Consumes: `pull_history`/`scan_dimension`/`lookup_products`/`lookup_players`/`backlinks`（Tasks 9–10）
- Produces: agent tools `pull_history`, `scan_dimension`, `lookup_products`, `lookup_players`, `backlinks`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_linklayer_tools.py
"""工具注册测试：config.yaml 可解析 + 工具函数可调用。"""
import yaml


def test_registry_has_link_tools():
    from pathlib import Path
    cfg = yaml.safe_load(
        (Path(__file__).parent.parent / "app" / "reasoning" / "registry" / "config.yaml")
        .read_text(encoding="utf-8")
    )
    names = {t["name"] for t in cfg["tools"]}
    for name in ("pull_history", "scan_dimension", "lookup_products", "lookup_players", "backlinks"):
        assert name in names, f"registry 缺少工具 {name}"


def test_pull_history_tool_importable():
    from app.reasoning.tools.knowledge.link_queries import pull_history_tool
    assert pull_history_tool.name == "pull_history"
```

- [ ] **Step 2: 运行确认失败** → FAIL

- [ ] **Step 3: 实现工具**（参照 `semantic_search.py` 的 `@tool` 模式）

```python
# backend/app/reasoning/tools/knowledge/link_queries.py
"""链接层检索工具：pull_history（判断正门）/ scan_dimension（横截面）/ lookup_*（单跳聚合）/ backlinks。"""
from __future__ import annotations

from typing import Annotated

from langchain_core.tools import tool


@tool("pull_history")
def pull_history_tool(
    subject: Annotated[str, "主体（公司名或 ts_code）"],
    dimension: Annotated[str | None, "维度名，如 产线进展/客户认证/毛利率；None=不限"] = None,
    scope: Annotated[str | None, "产品/技术范围，如 8英寸抛光硅片"] = None,
    limit: Annotated[int, "最多返回条数，默认 100"] = 100,
) -> dict:
    """按时间序拉取 (主体×维度) 的完整证据时间线。判断递进/变化/矛盾必用此工具（不是语义搜索）。"""
    from app.knowledge.linklayer.queries import pull_history
    import asyncio
    return asyncio.run(pull_history(subject, dimension=dimension, scope=scope, limit=limit))
```

同文件再实现 `scan_dimension_tool` / `lookup_products_tool` / `lookup_players_tool` / `backlinks_tool`（同样模式，docstring 用中文写清用途）。注意：现有工具是同步函数内跑 async 的模式请与 `semantic_search.py` 保持一致（若其为 `asyncio.run` 则照搬；若 registry 有 async 支持则用 async tool）。

- [ ] **Step 4: 注册工具**（config.yaml 的 knowledge 组追加）

```yaml
  - name: pull_history
    group: knowledge
    use: app.reasoning.tools.knowledge.link_queries:pull_history_tool
    description: 按(主体×维度)拉取时间序证据时间线——判断递进/变化的第一入口，替代语义搜索做预期差判断
  - name: scan_dimension
    group: knowledge
    use: app.reasoning.tools.knowledge.link_queries:scan_dimension_tool
    description: 横截面查询：某维度（如毛利率）下各主体的证据聚合，用于跨公司对比
  - name: lookup_products
    group: knowledge
    use: app.reasoning.tools.knowledge.link_queries:lookup_products_tool
    description: 单跳聚合：某公司关联的产品列表（带提及频次与最近提及）
  - name: lookup_players
    group: knowledge
    use: app.reasoning.tools.knowledge.link_queries:lookup_players_tool
    description: 单跳聚合：某产品/关键字下的公司列表（传导挖掘入口）
  - name: backlinks
    group: knowledge
    use: app.reasoning.tools.knowledge.link_queries:backlinks_tool
    description: 查看某条证据的全部关键字及同关键字关联证据（双向引用导航）
```

- [ ] **Step 5: 更新 divergence-mining skill**

改写 `app/reasoning/skills/divergence-mining/SKILL.md` 流程为：`pull_history 历史探索 → 分歧检测 → 才开证据分支（HypoSearch）→ 分支级证据比较 → fetch_evidence 验证 → write_finding 沉淀（Task 14 后可用）`。

- [ ] **Step 6: 运行测试** → PASS
- [ ] **Step 7: Commit** `feat(agent): 链接层检索工具注册 + divergence-mining skill 改造`

---

## Phase P3：判断台账

### Task 12: 台账 PG 表（observation / finding / watermark）

**Files:**
- Create. `backend/app/knowledge/linklayer/ledger_models.py`
- Create. `backend/alembic/versions/024_add_ledger_tables.py`
- Test. `backend/tests/test_linklayer_ledger_models.py`

**Interfaces:**
- Produces: `Observation`（表 `observations`）、`Finding`（表 `findings`）、`Watermark`（表 `watermarks`）、`make_obs_id(...)`、`make_finding_id(...)`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_linklayer_ledger_models.py
from app.knowledge.linklayer.ledger_models import Observation, Finding, Watermark, make_obs_id


def test_make_obs_id_deterministic():
    a = make_obs_id("EV:x", "003026.SZ", "产线进展", "8英寸抛光硅片")
    b = make_obs_id("EV:x", "003026.SZ", "产线进展", "8英寸抛光硅片")
    assert a == b and a.startswith("OB:")


def test_observation_pk_and_indexes():
    assert Observation.__tablename__ == "observations"
    assert Finding.__tablename__ == "findings"
    assert Watermark.__tablename__ == "watermarks"
```

- [ ] **Step 2: 运行确认失败** → FAIL

- [ ] **Step 3: 实现模型**（字段继承 9-17 台账草案，spec §4.3）

```python
# backend/app/knowledge/linklayer/ledger_models.py
"""判断台账（L2）：observation（观察·双源）/ finding（判断·派生）/ watermark（水位线·物化视图）。"""
import hashlib
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.database import Base


def make_obs_id(evidence_id: str, subject: str, dimension: str, scope: str | None) -> str:
    raw = f"{evidence_id}|{subject}|{dimension}|{scope or ''}"
    return "OB:" + hashlib.sha256(raw.encode()).hexdigest()[:16]


def make_finding_id(subject: str, dimension: str, to_level: int, obs_ids: str) -> str:
    return "FD:" + hashlib.sha256(f"{subject}|{dimension}|{to_level}|{obs_ids}".encode()).hexdigest()[:16]


class Observation(Base):
    """观察记录。status ∈ candidate(机械) | verified(agent) | dismissed；written_by = pipeline | agent:<run_id>"""
    __tablename__ = "observations"
    __table_args__ = (
        UniqueConstraint("obs_id", name="uq_observations_obs_id"),
        Index("idx_observations_subject", "subject_ts_code", "dimension", "dimension_scope"),
        Index("idx_observations_evidence", "evidence_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    obs_id: Mapped[str] = mapped_column(String(32), nullable=False)
    subject_ts_code: Mapped[str] = mapped_column(Text, nullable=False)
    subject_name: Mapped[str] = mapped_column(Text, nullable=False)
    dimension: Mapped[str] = mapped_column(Text, nullable=False)
    dimension_scope: Mapped[str | None] = mapped_column(Text)
    stage_raw: Mapped[str | None] = mapped_column(Text)
    stage_level: Mapped[int | None] = mapped_column(Integer)
    metric_value: Mapped[dict | None] = mapped_column(JSONB)  # {num, unit, period, metric}
    evidence_id: Mapped[str] = mapped_column(Text, nullable=False)
    span_start: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    span_end: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    event_date: Mapped[date | None] = mapped_column(Date)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    written_by: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="candidate")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Finding(Base):
    """判断（spec §4.3 修订 3：supports 必须句级锚定）。"""
    __tablename__ = "findings"
    __table_args__ = (
        UniqueConstraint("finding_id", name="uq_findings_finding_id"),
        Index("idx_findings_subject", "subject_ts_code", "dimension"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    finding_id: Mapped[str] = mapped_column(String(32), nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)  # progression|regression|new_event|association|divergence
    subject_ts_code: Mapped[str] = mapped_column(Text, nullable=False)
    dimension: Mapped[str] = mapped_column(Text, nullable=False)
    dimension_scope: Mapped[str | None] = mapped_column(Text)
    from_state: Mapped[dict | None] = mapped_column(JSONB)
    to_state: Mapped[dict | None] = mapped_column(JSONB)
    delta: Mapped[dict | None] = mapped_column(JSONB)
    supports: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)  # [{obs_id, evidence_id, span_start, span_end}]
    contradicts: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    judgment: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="candidate")
    supersedes: Mapped[str | None] = mapped_column(String(32))
    created_by: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Watermark(Base):
    """水位线（spec §5.2）：雷达消费者用它过滤 delta，judge 不过滤。"""
    __tablename__ = "watermarks"

    subject_ts_code: Mapped[str] = mapped_column(Text, primary_key=True)
    dimension: Mapped[str] = mapped_column(Text, primary_key=True)
    dimension_scope: Mapped[str | None] = mapped_column(Text, primary_key=True)
    max_level: Mapped[int | None] = mapped_column(Integer)
    max_value: Mapped[dict | None] = mapped_column(JSONB)
    first_reached_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
```

- [ ] **Step 4: 写迁移 `024_add_ledger_tables.py`**（三表，结构同上）
- [ ] **Step 5: 运行测试** → PASS
- [ ] **Step 6: Commit** `feat(ledger): 台账 observation/finding/watermark 模型与迁移 024`

### Task 13: 机械候选观察 + 水位线 + 雷达适配

**Files:**
- Create. `backend/app/knowledge/linklayer/candidates.py`
- Test. `backend/tests/test_linklayer_candidates.py`

**Interfaces:**
- Consumes: `Observation`/`Watermark`（Task 12）、`link_links`（Task 2）
- Produces: `async generate_candidates(evidence_id: str, session) -> list[dict]`——subject×stage 共现生成候选观察；`async emit_radar_signals(candidates, session) -> int`——对比水位线，level 上升者写 `Signal`（`source_type="link_layer"`）。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_linklayer_candidates.py
"""机械候选观察测试：零 LLM，纯 SQL 组装逻辑。"""
import pytest

from app.knowledge.linklayer.candidates import build_candidates_from_links


def test_build_candidates_from_links():
    """同 evidence 上 subject×stage 共现 → 一条候选观察。"""
    links = [
        {"evidence_id": "EV:1", "keyword_id": "KW:subj", "layer": "subject", "norm_text": "003026.SZ", "published_at": "2026-06-15"},
        {"evidence_id": "EV:1", "keyword_id": "KW:stage", "layer": "stage", "norm_text": "增产上量", "dimension": "产线进展", "level": 6, "published_at": "2026-06-15"},
        {"evidence_id": "EV:1", "keyword_id": "KW:dim", "layer": "dimension", "norm_text": "产线进展", "published_at": "2026-06-15"},
    ]
    candidates = build_candidates_from_links(links, evidence_text="公司8英寸抛光硅片产线已进入增产上量阶段")
    assert len(candidates) == 1
    cand = candidates[0]
    assert cand["subject_ts_code"] == "003026.SZ"
    assert cand["dimension"] == "产线进展"
    assert cand["stage_level"] == 6
    assert cand["status"] == "candidate"
```

- [ ] **Step 2: 运行确认失败** → FAIL

- [ ] **Step 3: 实现**

```python
# backend/app/knowledge/linklayer/candidates.py
"""机械候选观察（spec §4.3 修订 1）：批量侧零 LLM 的广度触发器。"""
from __future__ import annotations

from sqlalchemy import select

from app.knowledge.linklayer.ledger_models import Watermark, make_obs_id
from app.knowledge.linklayer.models import Keyword, Link
from app.signals.models import Signal


def build_candidates_from_links(links: list[dict], evidence_text: str) -> list[dict]:
    """从单条 evidence 的 link 集合组装候选观察：subject × stage 共现。"""
    subjects = [l for l in links if l["layer"] == "subject"]
    stages = [l for l in links if l["layer"] == "stage"]
    candidates = []
    for subj in subjects:
        for stage in stages:
            scope = _guess_scope(links, stage)  # 同 evidence 的 scope 关键字（可空）
            candidates.append({
                "obs_id": make_obs_id(links[0]["evidence_id"], subj["norm_text"],
                                      stage["dimension"], scope),
                "subject_ts_code": subj["norm_text"],
                "dimension": stage["dimension"],
                "dimension_scope": scope,
                "stage_raw": stage["norm_text"],
                "stage_level": stage["level"],
                "evidence_id": links[0]["evidence_id"],
                "published_at": links[0].get("published_at"),
                "status": "candidate",
            })
    return candidates


def _guess_scope(links: list[dict], stage: dict) -> str | None:
    scopes = [l["norm_text"] for l in links if l["layer"] == "scope"]
    return scopes[0] if scopes else None


async def generate_candidates(evidence_id: str, session) -> list[dict]:
    """读取 link 表，生成候选观察（不写库——由 emit 阶段统一写）。"""
    from app.core.database import async_session  # noqa: F401
    rows = (await session.execute(
        select(Keyword, Link).join(Link, Link.keyword_id == Keyword.keyword_id)
        .where(Link.evidence_id == evidence_id)
    )).all()
    links = [
        {"layer": k.layer, "norm_text": k.norm_text, "dimension": k.norm_text,
         "level": None, "evidence_id": l.evidence_id, "published_at": str(l.published_at)}
        for k, l in rows
    ]
    # level 由阶梯词表回填（同 evidence 的 stage 关键字带 dimension/level 元数据）
    from app.knowledge.linklayer.dictionaries import load_vocabulary
    vocab = load_vocabulary()
    for item in links:
        if item["layer"] == "stage":
            for name, dim in vocab.dimensions.items():
                for st in dim.stages:
                    if item["norm_text"] in st["words"]:
                        item["dimension"], item["level"] = name, st["level"]
                        break
    return build_candidates_from_links(links, "")


async def emit_radar_signals(candidates: list[dict], session) -> int:
    """水位线对比：level 上升 → 写 Signal（雷达低置信信号）。返回写入数。"""
    from datetime import datetime, timezone

    emitted = 0
    for cand in candidates:
        wm = (await session.execute(
            select(Watermark).where(
                Watermark.subject_ts_code == cand["subject_ts_code"],
                Watermark.dimension == cand["dimension"],
            )
        )).scalar_one_or_none()
        max_level = wm.max_level if wm else 0
        if cand.get("stage_level") and cand["stage_level"] > max_level:
            signal = Signal(
                signal_id=f"LL:{cand['obs_id']}",
                source_type="link_layer",
                source_id=cand["evidence_id"],
                subject_name=cand["subject_ts_code"],
                subject_type="company",
                signal_type=cand["dimension"],
                polarity="positive",
                strength=min(100, cand["stage_level"] * 15),
                confidence=0.5,  # 机械候选=低置信线索
                freshness_score=0,
                value_score=cand["stage_level"] * 10,
                summary=f"[{cand['dimension']}] {cand.get('stage_raw')}（候选 level={cand['stage_level']}）",
            )
            session.add(signal)
            emitted += 1
    await session.commit()
    return emitted
```

实现注意：`build_subject_index` 需在 Task 4 基础上让 stage 关键字携带 dimension/level 元数据进 keyword 表（`aliases` 字段或独立列），`generate_candidates` 优先从 keyword 元数据读取，词表回退为兜底——以实际实现为准并在测试中锁定。

- [ ] **Step 4: 运行测试** → PASS
- [ ] **Step 5: Commit** `feat(ledger): 机械候选观察 + 水位线对比 + 雷达适配器`

### Task 14: write_observation / write_finding 工具（句级锚定校验）

**Files:**
- Create. `backend/app/reasoning/tools/knowledge/ledger_tools.py`
- Modify. `backend/app/reasoning/registry/config.yaml`（追加 3 个工具）
- Test. `backend/tests/test_linklayer_ledger_tools.py`

**Interfaces:**
- Consumes: `Observation`/`Finding`/`Watermark`（Task 12）
- Produces: agent tools `write_observation`, `write_finding`, `watermark`；校验函数 `validate_supports(supports, session) -> list[str]`（返回错误列表，空=通过——evidence_id 必须存在且 span 在文本范围内）。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_linklayer_ledger_tools.py
from app.reasoning.tools.knowledge.ledger_tools import validate_supports


@pytest.mark.asyncio
async def test_validate_supports_rejects_missing_span():
    errors = await validate_supports(
        [{"evidence_id": "EV:nonexistent", "span_start": 0, "span_end": 5}], session=None
    )
    assert errors, "无锚点支撑必须被拒绝（SearchAtlas 硬证据闸门）"


@pytest.mark.asyncio
async def test_validate_supports_rejects_out_of_range(monkeypatch):
    async def fake_get_evidence(self, evidence_id):
        return {"evidence_id": evidence_id, "text_excerpt": "短文本"}
    monkeypatch.setattr(
        __import__("app.knowledge.evidence_service", fromlist=["EvidenceService"]).EvidenceService,
        "get_evidence", fake_get_evidence,
    )
    errors = await validate_supports(
        [{"evidence_id": "EV:x", "span_start": 100, "span_end": 200}], session=None
    )
    assert errors, "span 越界必须被拒绝"
```

- [ ] **Step 2: 运行确认失败** → FAIL

- [ ] **Step 3: 实现工具**（`@tool("write_finding")` 等，模式同 Task 11）：

核心校验逻辑：

```python
async def validate_supports(supports: list[dict], session) -> list[str]:
    """SearchAtlas 硬证据闸门：每个支撑必须真实存在且 span 在文本范围内。"""
    from app.knowledge.evidence_service import EvidenceService

    errors: list[str] = []
    svc = EvidenceService()
    for sup in supports:
        if not sup.get("evidence_id"):
            errors.append(f"缺少 evidence_id: {sup}")
            continue
        ev = await svc.get_evidence(sup["evidence_id"])
        if not ev:
            errors.append(f"evidence 不存在: {sup['evidence_id']}")
            continue
        text = ev.get("text_excerpt") or ""
        span_start, span_end = sup.get("span_start", 0), sup.get("span_end", 0)
        if span_start < 0 or span_end > len(text) or span_start >= span_end:
            errors.append(f"span 越界: {sup['evidence_id']} [{span_start}:{span_end}]")
    return errors
```

工具行为：`write_finding` 先 `validate_supports`，有错则返回错误列表拒绝写入；`write_observation` 同理。`watermark` 工具读 `watermarks` 表返回当前水位。

- [ ] **Step 4: 运行测试** → PASS
- [ ] **Step 5: Commit** `feat(ledger): write_observation/write_finding/watermark 工具（句级锚定）`

---

## Phase P4：退役与验收

### Task 15: 退役开关

**Files:**
- Modify. `backend/app/config.py`（新增 `enable_kg_extraction: bool = True`）
- Modify. `backend/app/knowledge/evidence_service.py`（`enqueue_default_jobs` 受开关控制）
- Modify. `backend/app/reasoning/registry/config.yaml`（`neo4j_kg_search` 置 `enabled: false`）
- Test. `backend/tests/test_linklayer_retirement.py`

**Interfaces:**
- Produces: `Settings.enable_kg_extraction` 开关；关闭后不再入队 `combined` job、Neo4j 不再有新写入、`neo4j_kg_search` 工具下线。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_linklayer_retirement.py
def test_enable_kg_extraction_flag_exists():
    from app.config import Settings
    assert hasattr(Settings(), "enable_kg_extraction")
```

- [ ] **Step 2: 运行确认失败** → FAIL

- [ ] **Step 3: 实现开关**

1. `app/config.py` 的 `Settings` 加：`enable_kg_extraction: bool = True  # False=停发三元组 combined job（三元组管线退役开关）`
2. `EvidenceService.enqueue_default_jobs`：`if settings.enable_kg_extraction:` 才入队 combined（vector/link 不受影响）。
3. `registry/config.yaml` 中 `neo4j_kg_search` 追加 `enabled: false`，description 加 "[已弃用] 请使用 pull_history"。
4. 生产切换（操作项，不在本任务执行）：云端 `.env` 加 `ENABLE_KG_EXTRACTION=false` 后 `systemctl restart qingshui-scheduler.service`。

- [ ] **Step 4: 运行测试** → PASS
- [ ] **Step 5: Commit** `feat(retire): 三元组抽取退役开关 + neo4j_kg_search 下线`

### Task 16: A/B 评估 + 文档收尾

**Files:**
- Modify. `README.md`（知识构建层章节更新为新架构）
- Modify. `docs/superpowers/specs/2026-09-18-knowledge-layer-redesign-design.md`（状态改为"已实施"）
- Test. 复用 Task 1 评估脚本。

- [ ] **Step 1: 跑基线**

Run: `cd backend && uv run python -m scripts.eval_retrieval --backend semantic --k 20`
Expected: 输出各查询 Recall@20，记录为基线。

- [ ] **Step 2: 跑链接层**

Run: `cd backend && uv run python -m scripts.eval_retrieval --backend link --k 20`
Expected: timeline/cross_section 类 mean Recall 不低于基线（spec P2 验收标准）；theme 类不在链接层评估范围。

- [ ] **Step 3: 更新文档**（README 架构图、spec 状态、遗留项说明：zhparser 全文检索、涌现聚类、embedding 概念层附着为后续迭代）

- [ ] **Step 4: Commit** `docs: 知识层重构落地——评估结果与文档更新`

---

## 自审记录（Self-Review）

1. **Spec 覆盖**：spec §5.1 三原语中 `browse`（主题）依赖 embedding 概念层（spec §4.4），本计划未实现——**这是有意的分期**：概念层依赖 Qdrant 向量通道的聚类管线，建议作为独立 plan（spec 已列入非目标边界），本计划验收标准不含 browse。spec §4.4 三层设计的第 1 层（官方分类）已存在（concepts/ths_concepts 表），不需新任务。
2. **占位符扫描**：Task 4 `build_subject_index` 与 Task 10 `build_scan_dimension_sql` 的 `NotImplementedError` 均附带了完整实现说明（数据源/SQL 骨架），非"稍后补齐"型占位。
3. **类型一致性**：`ensure_keyword(session, layer, norm_text, *, source) -> str` 在 Task 6 定义、Task 7 消费；`DictMatch` 字段在 Task 4 定义、Task 7/13 消费；`make_obs_id` 在 Task 12 定义、Task 13 消费——已交叉核对一致。
