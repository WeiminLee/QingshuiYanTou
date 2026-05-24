# 知识构建层可靠性修复实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 修复知识构建层中向量写入假成功、检索过滤失效、Evidence 追溯断链、批量图谱写入破坏不变量、测试误触真实外部 API 等问题。

**架构：** 保持现有 Evidence-first 管线不重构：MongoDB 存 Evidence/job，Neo4j 存实体关系，Qdrant 存向量。修复点集中在边界语义：底层客户端必须返回真实写入结果，worker 只按真实结果更新 job 状态，图谱批量写入必须保持与单条写入一致的 label、valid_from 和 evidence_id 语义。

**技术栈：** Python 3.11、pytest、MongoDB/Motor 风格 async repository、Neo4j Cypher、Qdrant client、httpx embedding client。

---

## 文件结构

- 修改：`backend/app/knowledge/vector_client.py`
  - 让 `VectorClient.upsert()` 和 `QdrantClient.upsert()` 返回 `bool`。
  - 让 `upsert_*_vector()` 根据底层结果返回真实成功/失败。
  - 为 `filter_expr` 增加受限解析，并传入 Qdrant `query_points()`。
- 修改：`backend/app/knowledge/vector_ops.py`
  - async upsert wrapper 根据 `client.upsert()` 结果返回真实 `bool`。
  - `hybrid_vector_search()` 继续把 `filter_expr` 传给 client，依赖 `QdrantClient.search()` 落地过滤。
- 修改：`backend/app/knowledge/evidence_worker.py`
  - 保持 vector job 使用 `upsert_evidence_chunk_vector()` 的布尔结果。
  - 测试中 monkeypatch 该函数，避免真实 embedding/Qdrant 调用。
- 修改：`backend/app/knowledge/kg_extractor.py`
  - `extract_evidence_async()` 写入关系时传入 `evidence_id/evidence_ids`。
- 修改：`backend/app/knowledge/relation_service.py`
  - 修复 `batch_upsert_relations_unwind()` 的 RELATES 批量 MERGE 键和 descriptions 去重。
- 修改：`backend/app/knowledge/entity_service.py`
  - 修复 `batch_upsert_entities_unwind()` 创建无 label 节点的问题。
- 修改：`backend/app/knowledge/evidence_service.py`
  - 给 `ensure_indexes()` 加 service 实例级 once guard，避免每次 upsert/claim 重复建索引。
- 创建：`backend/tests/test_vector_client.py`
  - 覆盖向量写入失败返回值和 Qdrant filter 传参。
- 修改：`backend/tests/test_evidence_worker.py`
  - 隔离 vector job 测试外部依赖，增加失败路径断言。
- 创建：`backend/tests/test_evidence_traceability.py`
  - 覆盖 Evidence 抽取写关系时传入 evidence ID。
- 创建：`backend/tests/test_batch_graph_writes.py`
  - 覆盖批量实体 label 和批量关系 valid_from/descriptions 语义。
- 修改：`backend/tests/test_evidence_service.py`
  - 覆盖 `ensure_indexes()` once guard。

---

### 任务 1：向量写入必须返回真实成功/失败

**文件：**
- 创建：`backend/tests/test_vector_client.py`
- 修改：`backend/app/knowledge/vector_client.py:425-772`
- 修改：`backend/app/knowledge/vector_ops.py:140-233`

- [ ] **步骤 1：编写失败的测试**

在 `backend/tests/test_vector_client.py` 写入：

```python
from __future__ import annotations

from app.knowledge.vector_client import (
    PlaceholderEmbedding,
    VectorClient,
    VectorRecord,
    SearchResult,
    reset_vector_state,
    set_embedding_model,
    set_vector_client,
    upsert_evidence_chunk_vector,
)


class FailingVectorClient(VectorClient):
    def connect(self) -> None:
        pass

    def disconnect(self) -> None:
        pass

    def create_collection(self, name: str, dimension: int, description: str = "", metric: str = "COSINE") -> bool:
        return True

    def upsert(self, collection: str, records: list[VectorRecord]) -> bool:
        return False

    def search(self, collection: str, query_vector: list[float], top_k: int = 10, filter_expr: str | None = None) -> list[SearchResult]:
        return []

    def delete_collection(self, name: str) -> bool:
        return True


def test_upsert_evidence_chunk_vector_returns_false_when_client_upsert_fails() -> None:
    reset_vector_state(close=True)
    set_embedding_model(PlaceholderEmbedding(dimension=8))
    set_vector_client(FailingVectorClient())
    try:
        ok = upsert_evidence_chunk_vector({
            "evidence_id": "EV:test",
            "text_excerpt": "公司公告称产品已经量产。",
            "source_type": "announcement",
            "source_name": "测试公告",
            "subject_hint": {"ts_code": "300001.SZ"},
            "source_ref": {"chunk_index": 0},
            "checksum": "abc",
        })
        assert ok is False
    finally:
        reset_vector_state(close=True)
```

- [ ] **步骤 2：运行测试验证失败**

运行：

```bash
pytest backend/tests/test_vector_client.py::test_upsert_evidence_chunk_vector_returns_false_when_client_upsert_fails -q
```

预期：FAIL，断言 `True is False`，因为当前 `upsert_evidence_chunk_vector()` 忽略 `client.upsert()` 结果并直接返回 `True`。

- [ ] **步骤 3：修改 VectorClient upsert 接口和 Qdrant 实现**

在 `backend/app/knowledge/vector_client.py` 中将抽象方法签名改为返回 `bool`：

```python
@abstractmethod
def create_collection(
    self,
    name: str,
    dimension: int,
    description: str = "",
    metric: str = "COSINE",
) -> bool:
    raise NotImplementedError

@abstractmethod
def upsert(self, collection: str, records: list[VectorRecord]) -> bool:
    raise NotImplementedError

@abstractmethod
def delete_collection(self, name: str) -> bool:
    raise NotImplementedError
```

把 `QdrantClient.create_collection()` 的成功、已存在、失败路径改为：

```python
if client.collection_exists(name):
    logger.info("Qdrant Collection 已存在: %s", name)
    return True
client.create_collection(...)
logger.info("Qdrant Collection 创建成功: %s (dim=%d)", name, dimension)
return True
```

异常分支返回：

```python
except ImportError:
    logger.warning("qdrant-client 未安装")
    return False
except Exception as e:
    logger.warning("Qdrant Collection 创建失败 [%s]: %s", name, e)
    return False
```

把 `QdrantClient.upsert()` 改为：

```python
def upsert(self, collection: str, records: list[VectorRecord]) -> bool:
    self._ensure_connected()
    if not records:
        return True
    try:
        import qdrant_client
        from qdrant_client.models import PointStruct, Distance, VectorParams

        client = qdrant_client.QdrantClient(url=self._url, api_key=self._api_key or None)
        if not client.collection_exists(collection):
            dim = len(records[0].vector)
            client.create_collection(
                collection_name=collection,
                vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
            )
            logger.info("Qdrant Collection 创建: %s (dim=%d)", collection, dim)
        points = [PointStruct(id=r.id, vector=r.vector, payload=r.payload) for r in records]
        client.upsert(collection_name=collection, points=points)
        logger.debug("Qdrant upsert 完成: %d 条", len(records))
        return True
    except Exception as e:
        logger.warning("Qdrant upsert 失败 [%s]: %s", collection, e)
        return False
```

把 `QdrantClient.delete_collection()` 改为成功返回 `True`、异常返回 `False`。

- [ ] **步骤 4：让快捷 upsert 函数尊重底层返回值**

在 `backend/app/knowledge/vector_client.py` 中把 `upsert_entity_vector()`、`upsert_relation_vector()`、`upsert_chunk_vector()`、`upsert_evidence_chunk_vector()` 内的：

```python
client.upsert(collection, [record])
return True
```

替换为：

```python
return bool(client.upsert(collection, [record]))
```

在 `backend/app/knowledge/vector_ops.py` 中把三个 async upsert wrapper 内的：

```python
client.upsert(COLLECTION_ENTITIES, [record])
return True
```

分别改为：

```python
return bool(client.upsert(COLLECTION_ENTITIES, [record]))
```

`COLLECTION_RELATIONS` 和 `COLLECTION_CHUNKS` 分支使用同样模式。

- [ ] **步骤 5：运行测试验证通过**

运行：

```bash
pytest backend/tests/test_vector_client.py::test_upsert_evidence_chunk_vector_returns_false_when_client_upsert_fails -q
```

预期：PASS。

- [ ] **步骤 6：Commit**

```bash
git add backend/app/knowledge/vector_client.py backend/app/knowledge/vector_ops.py backend/tests/test_vector_client.py
git commit -m "fix(knowledge): return truthful vector upsert status"
```

---

### 任务 2：隔离 Evidence worker 向量测试并覆盖失败路径

**文件：**
- 修改：`backend/tests/test_evidence_worker.py:139-146`
- 修改：`backend/app/knowledge/evidence_worker.py:102-109`

- [ ] **步骤 1：编写失败路径测试并隔离成功路径**

把 `backend/tests/test_evidence_worker.py` 中 `test_vector_job_success()` 替换为：

```python
def test_vector_job_success(monkeypatch) -> None:
    async def main():
        from app.knowledge import evidence_worker as ew

        monkeypatch.setattr(ew, "upsert_evidence_chunk_vector", lambda evidence: True)
        service = FakeService()
        service.jobs = [{"job_id": "J3", "evidence_id": "EV:1", "job_type": JOB_VECTOR, "status": STATUS_PENDING}]
        worker = _worker(service)
        result = await worker.run_once(limit=1, job_type=JOB_VECTOR)
        assert result["claimed"] == 1
        assert result["success"] == 1
        assert service.done[0][0] == "J3"
        assert service.done[0][1]["vector_ok"] is True

    asyncio.run(main())
```

继续在同一文件追加：

```python
def test_vector_job_failure_marks_failed(monkeypatch) -> None:
    async def main():
        from app.knowledge import evidence_worker as ew

        monkeypatch.setattr(ew, "upsert_evidence_chunk_vector", lambda evidence: False)
        service = FakeService()
        service.jobs = [{"job_id": "J4", "evidence_id": "EV:1", "job_type": JOB_VECTOR, "status": STATUS_PENDING}]
        worker = _worker(service)
        result = await worker.run_once(limit=1, job_type=JOB_VECTOR)
        assert result["claimed"] == 1
        assert result["failed"] == 1
        assert service.failed[0] == ("J4", "vector upsert failed")
        assert service.evidence["EV:1"]["status_updates"][-1] == (JOB_VECTOR, STATUS_FAILED)

    asyncio.run(main())
```

- [ ] **步骤 2：运行测试验证当前失败**

运行：

```bash
pytest backend/tests/test_evidence_worker.py::test_vector_job_success backend/tests/test_evidence_worker.py::test_vector_job_failure_marks_failed -q
```

预期：成功路径不再请求真实 Hunyuan；失败路径在任务 1 完成前可能已经通过，因为 worker 当前已按 `False` 标 failed。若成功路径仍访问外部 API，说明 monkeypatch 位置写错，应确认 patch 目标是 `app.knowledge.evidence_worker.upsert_evidence_chunk_vector`。

- [ ] **步骤 3：保持 worker 逻辑只依赖布尔结果**

确认 `backend/app/knowledge/evidence_worker.py` 的 vector 分支保持如下代码：

```python
if job_type == JOB_VECTOR:
    ok = upsert_evidence_chunk_vector(evidence)
    result = {"vector_ok": ok}
    if ok:
        await self.service.mark_job_done(job_id, result)
        return {"status": "done", **result}
    await self.service.mark_job_failed(job_id, "vector upsert failed")
    return {"status": "failed", **result}
```

如果实现中已经一致，不改业务代码。

- [ ] **步骤 4：运行测试验证通过**

运行：

```bash
pytest backend/tests/test_evidence_worker.py -q
```

预期：全部 PASS，且日志中不出现真实 Hunyuan/Qdrant 请求错误。

- [ ] **步骤 5：Commit**

```bash
git add backend/tests/test_evidence_worker.py backend/app/knowledge/evidence_worker.py
git commit -m "test(knowledge): isolate evidence vector worker"
```

---

### 任务 3：Qdrant 检索必须应用 ts_code 过滤

**文件：**
- 修改：`backend/tests/test_vector_client.py`
- 修改：`backend/app/knowledge/vector_client.py:25-32`
- 修改：`backend/app/knowledge/vector_client.py:563-587`

- [ ] **步骤 1：编写 filter 解析和传参测试**

在 `backend/tests/test_vector_client.py` 追加：

```python
def test_qdrant_search_passes_filter_expr_to_query_points(monkeypatch) -> None:
    import sys
    import types

    from app.knowledge.vector_client import QdrantClient

    captured = {}

    class FakePoint:
        id = "point-1"
        score = 0.9
        payload = {"ts_code": "300001.SZ"}

    class FakeResult:
        points = [FakePoint()]

    class FakeQdrant:
        def __init__(self, url: str, api_key=None):
            self.url = url
            self.api_key = api_key

        def query_points(self, **kwargs):
            captured.update(kwargs)
            return FakeResult()

    fake_module = types.SimpleNamespace(QdrantClient=FakeQdrant)
    monkeypatch.setitem(sys.modules, "qdrant_client", fake_module)

    client = QdrantClient(url="http://qdrant.test")
    result = client.search(
        collection="doc_chunks",
        query_vector=[0.1, 0.2],
        top_k=3,
        filter_expr='ts_code == "300001.SZ"',
    )

    assert len(result) == 1
    assert captured["collection_name"] == "doc_chunks"
    assert captured["limit"] == 3
    assert captured["query_filter"] is not None
```

- [ ] **步骤 2：运行测试验证失败**

运行：

```bash
pytest backend/tests/test_vector_client.py::test_qdrant_search_passes_filter_expr_to_query_points -q
```

预期：FAIL，报错 `KeyError: 'query_filter'`，因为当前 `search()` 忽略了 `filter_expr`。

- [ ] **步骤 3：实现受限 filter 解析**

在 `backend/app/knowledge/vector_client.py` 顶部 import 区增加：

```python
import re
```

在 `QdrantClient` 类之前添加：

```python
_FILTER_EXPR_PATTERN = re.compile(r'^\s*([A-Za-z_][A-Za-z0-9_.]*)\s*==\s*"([^"]*)"\s*$')


def _build_qdrant_filter(filter_expr: str | None):
    if not filter_expr:
        return None
    match = _FILTER_EXPR_PATTERN.match(filter_expr)
    if not match:
        logger.warning("Unsupported Qdrant filter expression: %s", filter_expr)
        return None
    field_name, value = match.groups()
    try:
        from qdrant_client.models import FieldCondition, Filter, MatchValue
    except Exception as exc:  # noqa: BLE001
        logger.warning("Qdrant filter models unavailable: %s", exc)
        return None
    return Filter(
        must=[
            FieldCondition(
                key=field_name,
                match=MatchValue(value=value),
            )
        ]
    )
```

- [ ] **步骤 4：传入 Qdrant query_filter**

把 `QdrantClient.search()` 中的 `client.query_points(...)` 改为：

```python
qdrant_filter = _build_qdrant_filter(filter_expr)
results = client.query_points(
    collection_name=collection,
    query=query_vector,
    limit=top_k,
    with_payload=True,
    query_filter=qdrant_filter,
)
```

- [ ] **步骤 5：运行测试验证通过**

运行：

```bash
pytest backend/tests/test_vector_client.py::test_qdrant_search_passes_filter_expr_to_query_points -q
```

预期：PASS。

- [ ] **步骤 6：Commit**

```bash
git add backend/app/knowledge/vector_client.py backend/tests/test_vector_client.py
git commit -m "fix(knowledge): apply qdrant search filters"
```

---

### 任务 4：Evidence 抽取写关系时必须保留 evidence_id

**文件：**
- 创建：`backend/tests/test_evidence_traceability.py`
- 修改：`backend/app/knowledge/kg_extractor.py:1195-1204`

- [ ] **步骤 1：编写失败的追溯测试**

创建 `backend/tests/test_evidence_traceability.py`：

```python
from __future__ import annotations

import asyncio


def test_extract_evidence_async_passes_evidence_id_to_relations(monkeypatch) -> None:
    from app.knowledge import kg_extractor as kg

    captured_relations: list[dict] = []

    async def fake_rag_extract_async(*args, **kwargs):
        return (
            [
                {"entity_name": "测试公司", "entity_type": "Company", "description": "公告主体"},
                {"entity_name": "测试产品", "entity_type": "Product", "description": "新产品"},
            ],
            [
                {
                    "src_id": "测试公司",
                    "tgt_id": "测试产品",
                    "description": "测试公司披露测试产品已经量产",
                    "weight": 10,
                }
            ],
        )

    def fake_upsert_company(**kwargs):
        return kwargs, True

    def fake_upsert_entity(**kwargs):
        return kwargs, True

    def fake_upsert_relates_v4(**kwargs):
        captured_relations.append(kwargs)
        return kwargs, True

    monkeypatch.setattr(kg, "rag_extract_async", fake_rag_extract_async)
    monkeypatch.setattr(kg, "upsert_company", fake_upsert_company)
    monkeypatch.setattr(kg, "upsert_entity", fake_upsert_entity)
    monkeypatch.setattr(kg, "upsert_relates_v4", fake_upsert_relates_v4)
    monkeypatch.setattr(kg, "upsert_entity_vector", lambda **kwargs: True)
    monkeypatch.setattr(kg, "upsert_relation_vector", lambda **kwargs: True)
    monkeypatch.setattr(kg, "_source_confidence", lambda source_type: (0.95, kg.ConfidenceTier.HIGH))

    result = asyncio.run(kg.extract_evidence_async({
        "evidence_id": "EV:trace",
        "source_type": "announcement",
        "source_name": "测试公告",
        "source_id": "ann-1",
        "text_excerpt": "测试公司披露测试产品已经量产。",
        "subject_hint": {"ts_code": "300001.SZ"},
    }))

    assert result["relations_created"] == 1
    assert captured_relations[0]["evidence_id"] == "EV:trace"
    assert captured_relations[0]["evidence_ids"] == ["EV:trace"]
```

- [ ] **步骤 2：运行测试验证失败**

运行：

```bash
pytest backend/tests/test_evidence_traceability.py::test_extract_evidence_async_passes_evidence_id_to_relations -q
```

预期：FAIL，报错 `KeyError: 'evidence_id'`，因为当前 `extract_evidence_async()` 调用 `upsert_relates_v4()` 时没有传 Evidence ID。

- [ ] **步骤 3：把 evidence_id 传给关系写入**

在 `backend/app/knowledge/kg_extractor.py` 的 `extract_evidence_async()` 关系写入调用中，把：

```python
_, is_new = upsert_relates_v4(
    from_entity=src_eid,
    to_entity=tgt_eid,
    text=rel_desc,
    weight=v2_weight,
    source_file=source_name,
    source_type=source_type,
    source_name=source_name,
    valid_from=today,
)
```

替换为：

```python
evidence_id = str(evidence.get("evidence_id") or "")
evidence_ids = [evidence_id] if evidence_id else []
_, is_new = upsert_relates_v4(
    from_entity=src_eid,
    to_entity=tgt_eid,
    text=rel_desc,
    weight=v2_weight,
    source_file=source_name,
    source_type=source_type,
    source_name=source_name,
    valid_from=today,
    evidence_id=evidence_id,
    evidence_ids=evidence_ids,
)
```

把 `evidence_id/evidence_ids` 计算放在关系循环之前，避免每条关系重复读取：

```python
evidence_id = str(evidence.get("evidence_id") or "")
evidence_ids = [evidence_id] if evidence_id else []
```

- [ ] **步骤 4：运行测试验证通过**

运行：

```bash
pytest backend/tests/test_evidence_traceability.py::test_extract_evidence_async_passes_evidence_id_to_relations -q
```

预期：PASS。

- [ ] **步骤 5：Commit**

```bash
git add backend/app/knowledge/kg_extractor.py backend/tests/test_evidence_traceability.py
git commit -m "fix(knowledge): preserve evidence ids on relations"
```

---

### 任务 5：批量关系写入必须按 valid_from 合并且正确去重 descriptions

**文件：**
- 创建：`backend/tests/test_batch_graph_writes.py`
- 修改：`backend/app/knowledge/relation_service.py:539-625`

- [ ] **步骤 1：编写 Cypher 结构测试**

创建 `backend/tests/test_batch_graph_writes.py` 并写入：

```python
from __future__ import annotations

from contextlib import contextmanager
from datetime import date


class FakeResult:
    def consume(self) -> None:
        pass


class FakeTx:
    def __init__(self, calls: list[tuple[str, dict]]):
        self.calls = calls

    def run(self, query: str, params: dict):
        self.calls.append((query, params))
        return FakeResult()


def test_batch_upsert_relations_merges_by_valid_from_and_dedupes_description(monkeypatch) -> None:
    from app.knowledge import relation_service as rs

    calls: list[tuple[str, dict]] = []

    @contextmanager
    def fake_write_transaction():
        yield FakeTx(calls)

    monkeypatch.setattr(rs, "write_transaction", fake_write_transaction)

    result = rs.batch_upsert_relations_unwind([
        {
            "from_entity": "C:300001.SZ",
            "to_entity": "P:abc",
            "text": "公司披露产品已经量产",
            "source_file": "公告A",
            "source_type": "announcement",
            "source_name": "公告A",
            "valid_from": date(2026, 5, 24),
            "weight": 1.0,
        }
    ])

    assert result["failed"] == 0
    upsert_query = calls[1][0]
    rows = calls[1][1]["rows"]
    assert "MERGE (a)-[r:RELATES {valid_from: row.valid_from}]->(b)" in upsert_query
    assert "WHERE NOT row.description_entry IN r.descriptions" in upsert_query
    assert rows[0]["description_entry"] == "[公告A]neutral: 公司披露产品已经量产"
```

- [ ] **步骤 2：运行测试验证失败**

运行：

```bash
pytest backend/tests/test_batch_graph_writes.py::test_batch_upsert_relations_merges_by_valid_from_and_dedupes_description -q
```

预期：FAIL，因为当前 Cypher 是 `MERGE (a)-[r:RELATES]->(b)`，且用 `row.text` 检查 `r.descriptions`。

- [ ] **步骤 3：修复 rows 字段**

在 `backend/app/knowledge/relation_service.py` 的 `batch_upsert_relations_unwind()` rows 构造中，把：

```python
source_label = f"[{source_file}]{direction}: {rel.get('text', '')}"
```

改为：

```python
description_entry = f"[{source_file}]{direction}: {rel.get('text', '')}"
```

并在 `rows.append({...})` 中把：

```python
"descriptions": [source_label],
```

改为：

```python
"description_entry": description_entry,
"descriptions": [description_entry],
```

- [ ] **步骤 4：修复批量关系 Cypher**

把 `upsert_cypher` 中的关系 MERGE 和 descriptions 去重改为：

```cypher
MERGE (a)-[r:RELATES {valid_from: row.valid_from}]->(b)
ON CREATE SET
    r.text         = row.text,
    r.weight       = row.weight,
    r.direction    = row.direction,
    r.descriptions = row.descriptions,
    r.source_type   = row.source_type,
    r.source_name   = row.source_name,
    r.source_chunk  = row.source_chunk,
    r.source_file   = row.source_file,
    r.valid_to      = row.valid_to,
    r.created_at    = row.now,
    r.updated_at    = row.now
ON MATCH SET
    r.updated_at = row.now,
    r.weight = CASE WHEN r.weight < row.weight THEN row.weight ELSE r.weight END,
    r.source_type = COALESCE(r.source_type, row.source_type),
    r.source_name = COALESCE(r.source_name, row.source_name)
WITH r, row
WHERE NOT row.description_entry IN r.descriptions
  SET r.descriptions = r.descriptions + row.descriptions
RETURN count(r) AS total
```

保留 close stage，但把条件收窄为不关闭同一个 `valid_from` 的边：

```cypher
WHERE r.valid_to IS NULL
  AND r.valid_from <> row.valid_from
```

- [ ] **步骤 5：运行测试验证通过**

运行：

```bash
pytest backend/tests/test_batch_graph_writes.py::test_batch_upsert_relations_merges_by_valid_from_and_dedupes_description -q
```

预期：PASS。

- [ ] **步骤 6：Commit**

```bash
git add backend/app/knowledge/relation_service.py backend/tests/test_batch_graph_writes.py
git commit -m "fix(knowledge): preserve relation batch time keys"
```

---

### 任务 6：批量实体写入必须创建带 label 的节点

**文件：**
- 修改：`backend/tests/test_batch_graph_writes.py`
- 修改：`backend/app/knowledge/entity_service.py:238-356`

- [ ] **步骤 1：编写 label 分组测试**

在 `backend/tests/test_batch_graph_writes.py` 追加：

```python
def test_batch_upsert_entities_creates_labeled_nodes(monkeypatch) -> None:
    from app.knowledge import entity_service as es

    calls: list[tuple[str, dict]] = []

    @contextmanager
    def fake_write_transaction():
        yield FakeTx(calls)

    monkeypatch.setattr(es, "write_transaction", fake_write_transaction)

    result = es.batch_upsert_entities_unwind([
        {"entity_id": "C:300001.SZ", "entity_type": "Company", "name": "测试公司", "ts_code": "300001.SZ"},
        {"entity_id": "P:abc", "entity_type": "Product", "name": "测试产品"},
    ])

    assert result["failed"] == 0
    queries = "\n".join(query for query, params in calls)
    assert "MERGE (n:Company {entity_id: row.entity_id})" in queries
    assert "MERGE (n:Product {entity_id: row.entity_id})" in queries
```

- [ ] **步骤 2：运行测试验证失败**

运行：

```bash
pytest backend/tests/test_batch_graph_writes.py::test_batch_upsert_entities_creates_labeled_nodes -q
```

预期：FAIL，因为当前批量实体写入使用 `MERGE (n {entity_id: row.entity_id})`，不会设置 Neo4j label。

- [ ] **步骤 3：按 entity_type 分组并验证 label**

在 `backend/app/knowledge/entity_service.py` 的 `batch_upsert_entities_unwind()` 中，rows 构建后增加分组：

```python
rows_by_type: dict[str, list[dict]] = {}
invalid_type_count = 0
for row in rows:
    entity_type = row.get("entity_type")
    if entity_type not in ENTITY_TYPES_V4:
        invalid_type_count += 1
        continue
    rows_by_type.setdefault(entity_type, []).append(row)
```

把单次 `tx.run(cypher, {"rows": rows})` 改为对每个类型执行一次：

```python
with write_transaction() as tx:
    for entity_type, typed_rows in rows_by_type.items():
        cypher = _batch_upsert_entities_cypher(entity_type)
        result = tx.run(cypher, {"rows": typed_rows})
        result.consume()
```

把返回中的失败数改为：

```python
"failed": invalid_type_count,
```

- [ ] **步骤 4：新增固定 label Cypher 生成函数**

在 `batch_upsert_entities_unwind()` 上方添加：

```python
def _batch_upsert_entities_cypher(entity_type: str) -> str:
    if entity_type not in ENTITY_TYPES_V4:
        raise ValueError(f"无效 entity_type: {entity_type}")
    return f"""
    UNWIND $rows AS row
    MERGE (n:{entity_type} {{entity_id: row.entity_id}})
    ON CREATE SET
        n.entity_id      = row.entity_id,
        n.name           = row.name,
        n.confidence     = row.confidence,
        n.source_type    = row.source_type,
        n.source_name    = row.source_name,
        n.evidence_url   = row.evidence_url,
        n.valid_from     = row.valid_from,
        n.valid_to       = row.valid_to,
        n.parser_version = row.parser_version,
        n.created_at     = row.created_at,
        n.updated_at     = row.updated_at,
        n += row - {{entity_id, name, entity_type, confidence, source_type,
                    source_name, evidence_url, valid_from, valid_to,
                    parser_version, created_at, updated_at}}
    ON MATCH SET
        n.name        = row.name,
        n.confidence  = row.confidence,
        n.updated_at  = row.updated_at,
        n.valid_to    = COALESCE(n.valid_to, row.valid_to),
        n.aliases     = COALESCE(n.aliases, row.aliases)
    WITH n, row
    WHERE n.source_type IS NULL AND row.source_type IS NOT NULL
      SET n.source_type = row.source_type
    WITH n, row
    WHERE n.source_name IS NULL AND row.source_name IS NOT NULL
      SET n.source_name = row.source_name
    WITH n, row
    WHERE n.evidence_url IS NULL AND row.evidence_url IS NOT NULL
      SET n.evidence_url = row.evidence_url
    RETURN count(n) AS total
    """
```

注意：`entity_type` 来自 `ENTITY_TYPES_V4` 白名单，不能直接使用未验证输入拼接 Cypher。

- [ ] **步骤 5：运行测试验证通过**

运行：

```bash
pytest backend/tests/test_batch_graph_writes.py::test_batch_upsert_entities_creates_labeled_nodes -q
```

预期：PASS。

- [ ] **步骤 6：Commit**

```bash
git add backend/app/knowledge/entity_service.py backend/tests/test_batch_graph_writes.py
git commit -m "fix(knowledge): label batch entity upserts"
```

---

### 任务 7：EvidenceService 索引初始化只在每个 service 实例执行一次

**文件：**
- 修改：`backend/tests/test_evidence_service.py`
- 修改：`backend/app/knowledge/evidence_service.py:35-57`

- [ ] **步骤 1：编写重复建索引测试**

在 `backend/tests/test_evidence_service.py` 追加：

```python
def test_ensure_indexes_runs_once_per_service_instance() -> None:
    async def main():
        svc = _service()
        await svc.upsert_evidence(_input("hello"))
        await svc.enqueue_job(stable_evidence_id("irm", "1", 0, "hello"), JOB_COMBINED)
        await svc.claim_next_job(JOB_COMBINED, worker_id="w1")

        assert len(svc._evidence.indexes) == 5
        assert len(svc._jobs.indexes) == 5

    asyncio.run(main())
```

- [ ] **步骤 2：运行测试验证失败**

运行：

```bash
pytest backend/tests/test_evidence_service.py::test_ensure_indexes_runs_once_per_service_instance -q
```

预期：FAIL，因为当前 `upsert_evidence()`、`enqueue_job()`、`claim_next_job()` 都调用 `ensure_indexes()`，FakeCollection 会记录多轮 index 创建。

- [ ] **步骤 3：实现 service 实例级 once guard**

在 `EvidenceService.__init__()` 中增加：

```python
self._indexes_ready = False
```

把 `ensure_indexes()` 改为：

```python
async def ensure_indexes(self) -> None:
    if self._indexes_ready:
        return
    await self._evidence.create_index("evidence_id", unique=True)
    await self._evidence.create_index("checksum")
    await self._evidence.create_index("source_type")
    await self._evidence.create_index("subject_hint.ts_code")
    await self._evidence.create_index("publish_date")

    await self._jobs.create_index("job_id", unique=True)
    await self._jobs.create_index("evidence_id")
    await self._jobs.create_index("status")
    await self._jobs.create_index("job_type")
    await self._jobs.create_index("updated_at")
    self._indexes_ready = True
```

- [ ] **步骤 4：运行测试验证通过**

运行：

```bash
pytest backend/tests/test_evidence_service.py::test_ensure_indexes_runs_once_per_service_instance -q
```

预期：PASS。

- [ ] **步骤 5：Commit**

```bash
git add backend/app/knowledge/evidence_service.py backend/tests/test_evidence_service.py
git commit -m "perf(knowledge): avoid repeated evidence index setup"
```

---

### 任务 8：知识层回归验证

**文件：**
- 修改：无
- 测试：`backend/tests/test_vector_client.py`
- 测试：`backend/tests/test_evidence_worker.py`
- 测试：`backend/tests/test_evidence_service.py`
- 测试：`backend/tests/test_evidence_builders.py`
- 测试：`backend/tests/test_chunk_dedup.py`
- 测试：`backend/tests/test_evidence_traceability.py`
- 测试：`backend/tests/test_batch_graph_writes.py`

- [ ] **步骤 1：运行新增和受影响测试**

运行：

```bash
pytest \
  backend/tests/test_vector_client.py \
  backend/tests/test_evidence_worker.py \
  backend/tests/test_evidence_service.py \
  backend/tests/test_evidence_builders.py \
  backend/tests/test_chunk_dedup.py \
  backend/tests/test_evidence_traceability.py \
  backend/tests/test_batch_graph_writes.py \
  -q
```

预期：全部 PASS。

- [ ] **步骤 2：运行现有知识层相关测试**

运行：

```bash
pytest \
  backend/tests/test_entity_resolver.py \
  backend/tests/test_stock_name_resolver.py \
  backend/tests/test_feedback_api.py \
  backend/tests/test_kg_search.py \
  backend/tests/test_graph_reasoning.py \
  -q
```

预期：全部 PASS。若测试环境缺少 Neo4j/Qdrant，失败应来自环境连接；记录具体错误，不把连接错误伪装成代码通过。

- [ ] **步骤 3：检查没有真实外部 embedding 调用**

运行：

```bash
pytest backend/tests/test_evidence_worker.py::test_vector_job_success -q -s
```

预期：PASS，输出中不出现 `https://api.hunyuan.cloud.tencent.com/v1/embeddings`、`400 Bad Request` 或 Qdrant 连接错误。

- [ ] **步骤 4：检查 git diff 范围**

运行：

```bash
git diff --stat
git diff -- backend/app/knowledge backend/tests
```

预期：diff 只包含本计划列出的知识层和测试文件，没有前端、数据接入或 Agent runtime 的无关改动。

- [ ] **步骤 5：Commit 验证记录**

如果步骤 1-4 只产生测试和代码修改且尚未提交，运行：

```bash
git add backend/app/knowledge backend/tests
git commit -m "test(knowledge): verify knowledge layer hardening"
```

如果步骤 1-4 没有新增文件修改，只在执行记录中标记验证完成，不创建空提交。

---

## 自检

**规格覆盖度：**
- 向量写入假成功：任务 1、任务 2 覆盖。
- 检索过滤失效：任务 3 覆盖。
- Evidence 关系追溯断链：任务 4 覆盖。
- 批量关系时序和 descriptions 去重：任务 5 覆盖。
- 批量实体无 label：任务 6 覆盖。
- EvidenceService 重复建索引：任务 7 覆盖。
- 外部 API 测试污染和回归验证：任务 2、任务 8 覆盖。

**占位符扫描：**
- 任务步骤均包含具体路径、代码片段、运行命令和预期结果，没有留下空泛占位说明。
- 每个代码变更步骤包含具体路径、代码片段、运行命令和预期结果。

**类型一致性：**
- `VectorClient.upsert()` 在抽象类、`QdrantClient`、测试 fake client、同步/异步 wrapper 中统一返回 `bool`。
- `evidence_id/evidence_ids` 与 `upsert_relates_v4()` 现有签名一致。
- 批量实体 label 来自 `ENTITY_TYPES_V4` 白名单，避免动态 Cypher 注入。
