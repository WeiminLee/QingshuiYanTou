# chemagent Worker API 解耦（P2）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `vector` / `link` 两类 evidence 任务在**无云数据库访问**的 worker 上完成——计算留在 worker，落库经云端 Knowledge API。

**Architecture:** 把现有"计算与落库耦合在一个同步 DB 调用里"的路径拆成两段：worker 侧产生结构化行集合（`LinkAction[]` / `VectorRecord`），云端新增写入端点负责落 Qdrant / PG。落库端点幂等，沿用现有 PK 语义。`combined` 已有远端分支（`/kg/ingest`），本计划不涉及。

**Tech Stack:** Python 3.11+、FastAPI、Pydantic v2、SQLAlchemy 2.x async、pytest、httpx、Qdrant client。

**Spec:** `docs/superpowers/specs/2026-09-23-chemagent-worker-deployment-design.md`（§5 接口契约、§5.3 改造点）

## Global Constraints

- 不新增第三方依赖（`backend/requirements.txt` 不改）。
- 远端模式判定沿用现有约定：`KNOWLEDGE_API_URL` 与 `KNOWLEDGE_API_KEY` 同时存在即远端。
- **不改动本地（直连 DB）路径的现有行为**：所有重构必须保持 `ingest_evidence` / `upsert_evidence_chunk_vector` / `ingest_evidence_signals` 的既有签名与返回值语义，现有测试必须继续通过。
- 写入端点鉴权复用现有 `X-API-Key`（`settings.knowledge_api_key or settings.api_key`）。
- 幂等：link 冲突 `do nothing`（`source == "hint"` 仍 `on_conflict_do_update` 转正）；vector 用 `uuid5(NAMESPACE_DNS, evidence_id)` 作 point id；observation `obs_id` 冲突 `do nothing`。
- 测试命令：`cd backend && .venv/bin/python -m pytest <path> -v`。
- 每个 Task 结束提交一次。

## 范围说明

- **含**：`vector`、`link` 的云端写入端点 + worker 远端分支。
- **不含**：`signal`。生产已 `ENABLE_KG_EXTRACTION=false`，活动任务只有 `vector` + `link`（见 spec §2 P6 / §11）；`signal` 的计算依赖 Neo4j 读取（`KGPathProvider`），无法在断网 worker 本地完成，需单独设计，列为后续计划。

## File Structure

| 文件 | 职责 |
|---|---|
| `backend/app/knowledge/api/_auth.py`（新建） | 抽出 `require_api_key`，供各 worker 端点复用 |
| `backend/app/knowledge/api/worker_writes.py`（新建） | 云端写入端点：`/vector/upsert`、`/link/upsert` |
| `backend/app/knowledge/vector_client.py`（改） | 拆出 `build_evidence_vector_record` / `write_chunk_vector` |
| `backend/app/knowledge/linklayer/ingest.py`（改） | 拆出 `compute_link_actions` / `persist_link_actions` |
| `backend/app/knowledge/linklayer/link_pipeline.py`（新建） | 云端 link 落库后的机械台账管线（候选→观察→雷达→水位） |
| `backend/app/knowledge/worker_api_client.py`（改） | 增 `upsert_vector` / `upsert_links` |
| `backend/app/knowledge/evidence_worker.py`（改） | `JOB_VECTOR` / `JOB_LINK` 远端分支 |
| `backend/app/knowledge/linklayer/dict_match.py`（改） | `build_subject_index(use_db=True)`，远端跳过 PG |
| `backend/app/main.py`（改） | 注册 `worker_writes` 路由 |
| `backend/tests/test_worker_writes_api.py`（新建） | 端点测试 |
| `backend/tests/test_link_pipeline.py`（新建） | 台账管线测试 |
| `backend/tests/test_vector_client_split.py`（新建） | 向量拆分测试 |
| `backend/tests/test_evidence_worker.py`（改） | 远端分支测试 |

---

### Task 1: 向量计算/写入拆分（云端与 worker 共用）

**Files:**
- Modify: `backend/app/knowledge/vector_client.py:954-994`
- Test: `backend/tests/test_vector_client_split.py`

**Interfaces:**
- Consumes: 无（首任务）
- Produces:
  - `build_evidence_vector_record(evidence: dict) -> VectorRecord | None`
  - `write_chunk_vector(record: VectorRecord, collection: str = COLLECTION_CHUNKS) -> bool`
  - `upsert_evidence_chunk_vector(evidence: dict, collection: str = COLLECTION_CHUNKS) -> bool`（行为不变）

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_vector_client_split.py
from __future__ import annotations

from unittest.mock import patch

from app.knowledge.vector_client import (
    VectorRecord,
    build_evidence_vector_record,
    upsert_evidence_chunk_vector,
    write_chunk_vector,
)

EV = {
    "evidence_id": "EV:1",
    "text_excerpt": "公司公告称量产。",
    "source_type": "irm",
    "source_name": "互动易:1",
    "subject_hint": {"ts_code": "300001.SZ"},
}


def test_build_record_returns_none_on_empty_evidence():
    assert build_evidence_vector_record({"evidence_id": "", "text_excerpt": "x"}) is None
    assert build_evidence_vector_record({"evidence_id": "EV:1", "text_excerpt": "   "}) is None


def test_build_record_embeds_and_keeps_payload():
    with patch("app.knowledge.vector_client.get_embedding_model") as m:
        m.return_value.embed.return_value = [0.1, 0.2, 0.3]
        rec = build_evidence_vector_record(EV)
    assert isinstance(rec, VectorRecord)
    assert rec.vector == [0.1, 0.2, 0.3]
    assert rec.payload["evidence_id"] == "EV:1"
    assert rec.payload["source_type"] == "irm"


def test_write_chunk_vector_swallows_errors():
    rec = VectorRecord(id="p1", vector=[0.1], payload={"evidence_id": "EV:1"})
    with patch("app.knowledge.vector_client.get_vector_client") as m:
        m.return_value.upsert.side_effect = RuntimeError("boom")
        assert write_chunk_vector(rec) is False


def test_upsert_evidence_chunk_vector_delegates_to_split_functions():
    with patch(
        "app.knowledge.vector_client.build_evidence_vector_record",
        return_value=VectorRecord(id="p1", vector=[0.1], payload={"evidence_id": "EV:1"}),
    ) as b, patch("app.knowledge.vector_client.write_chunk_vector", return_value=True) as w:
        assert upsert_evidence_chunk_vector(EV) is True
    b.assert_called_once()
    w.assert_called_once()
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_vector_client_split.py -v`
Expected: FAIL — `ImportError: cannot import name 'build_evidence_vector_record'`

- [ ] **Step 3: 实现拆分**

把 `vector_client.py:954-994` 的 `upsert_evidence_chunk_vector` 整体替换为：

```python
def build_evidence_vector_record(evidence: dict[str, Any]) -> VectorRecord | None:
    """生成 doc_chunks 向量记录（含 embedding 计算）。输入无效返回 None。"""
    evidence_id = str(evidence.get("evidence_id") or "")
    text = str(evidence.get("text_excerpt") or "")
    if not evidence_id or not text.strip():
        logger.warning("build_evidence_vector_record 输入无效: evidence_id=%s", evidence_id)
        return None

    # bge-m3 上下文窗口 8192 tokens，截断到 7000 字避免超限
    MAX_EMBED_CHARS = 7000
    if len(text) > MAX_EMBED_CHARS:
        text = text[:MAX_EMBED_CHARS]

    vec = get_embedding_model().embed(text)
    return VectorRecord(
        id=str(uuid.uuid5(uuid.NAMESPACE_DNS, evidence_id)),
        vector=vec,
        payload={
            "evidence_id": evidence_id,
            "content": text,
            "source_type": evidence.get("source_type", ""),
            "source_name": evidence.get("source_name", ""),
            "subject_hint": evidence.get("subject_hint") or {},
            "source_ref": evidence.get("source_ref") or {},
            "publish_date": evidence.get("publish_date"),
            "observed_at": evidence.get("observed_at"),
            "checksum": evidence.get("checksum", ""),
        },
    )


def write_chunk_vector(record: VectorRecord, collection: str = COLLECTION_CHUNKS) -> bool:
    """把已构造好的向量记录写入 Qdrant。"""
    try:
        get_vector_client().upsert(collection, [record])
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning("write_chunk_vector 失败: %s", e)
        return False


def upsert_evidence_chunk_vector(
    evidence: dict[str, Any],
    collection: str = COLLECTION_CHUNKS,
) -> bool:
    """将 Evidence 片段写入向量库（计算 + 写入一体，保持原行为）。"""
    record = build_evidence_vector_record(evidence)
    if record is None:
        return False
    return write_chunk_vector(record, collection)
```

- [ ] **Step 4: 运行确认通过 + 回归**

Run: `cd backend && .venv/bin/python -m pytest tests/test_vector_client_split.py -v`
Expected: PASS（4 passed）
Run: `cd backend && .venv/bin/python -m pytest tests/test_evidence_worker.py -v`
Expected: PASS（既有 vector job 测试不回归）

- [ ] **Step 5: 提交**

```bash
git add backend/app/knowledge/vector_client.py backend/tests/test_vector_client_split.py
git commit -m "refactor(knowledge): split vector compute from Qdrant write"
```

---

### Task 2: 云端端点 `/api/v1/knowledge/vector/upsert`

**Files:**
- Create: `backend/app/knowledge/api/_auth.py`
- Create: `backend/app/knowledge/api/worker_writes.py`
- Modify: `backend/app/knowledge/api/worker_jobs.py:15-18`（改用共享 `require_api_key`）
- Modify: `backend/app/main.py:202-203`（注册新路由）
- Test: `backend/tests/test_worker_writes_api.py`

**Interfaces:**
- Consumes: Task 1 的 `write_chunk_vector`、`VectorRecord`
- Produces:
  - `require_api_key(x_api_key: str | None) -> None`（`app.knowledge.api._auth`）
  - `POST /api/v1/knowledge/vector/upsert`，请求 `{evidence_id, vector, payload, collection?}`，响应 `{"ok": true}`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_worker_writes_api.py
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app

HEADERS = {"X-API-Key": "test-key"}


@pytest.fixture(autouse=True)
def _api_key(monkeypatch):
    monkeypatch.setattr(settings, "knowledge_api_key", "test-key", raising=False)
    monkeypatch.setattr(settings, "api_key", "", raising=False)


@pytest.fixture()
def client():
    return TestClient(app)


def test_vector_upsert_requires_api_key(client):
    r = client.post(
        "/api/v1/knowledge/vector/upsert",
        json={"evidence_id": "EV:1", "vector": [0.1], "payload": {}},
    )
    assert r.status_code == 401


def test_vector_upsert_writes_record(client):
    captured = {}

    def fake_write(record, collection):
        captured["record"] = record
        captured["collection"] = collection
        return True

    with patch("app.knowledge.api.worker_writes.write_chunk_vector", side_effect=fake_write):
        r = client.post(
            "/api/v1/knowledge/vector/upsert",
            headers=HEADERS,
            json={
                "evidence_id": "EV:1",
                "vector": [0.1, 0.2],
                "payload": {"content": "x", "source_type": "irm"},
            },
        )
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    assert captured["record"].vector == [0.1, 0.2]
    assert captured["record"].payload["evidence_id"] == "EV:1"


def test_vector_upsert_reports_write_failure(client):
    with patch("app.knowledge.api.worker_writes.write_chunk_vector", return_value=False):
        r = client.post(
            "/api/v1/knowledge/vector/upsert",
            headers=HEADERS,
            json={"evidence_id": "EV:1", "vector": [0.1], "payload": {}},
        )
    assert r.status_code == 502
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_worker_writes_api.py -v`
Expected: FAIL — `404 Not Found`（路由未注册）

- [ ] **Step 3: 抽出鉴权**

新建 `backend/app/knowledge/api/_auth.py`：

```python
"""Worker 端点的共享鉴权。"""
from __future__ import annotations

from fastapi import HTTPException

from app.config import settings


def require_api_key(key: str | None) -> None:
    expected = settings.knowledge_api_key or settings.api_key
    if not expected or key != expected:
        raise HTTPException(401, "无效 API 密钥")
```

`backend/app/knowledge/api/worker_jobs.py` 第 15-18 行的 `_auth` 定义替换为导入：

```python
from app.knowledge.api._auth import require_api_key as _auth
```

（其余 `_auth(...)` 调用点不变。）

- [ ] **Step 4: 实现端点**

新建 `backend/app/knowledge/api/worker_writes.py`：

```python
"""HTTPS 写入边界：worker 侧算好的结果落 Qdrant / PG。"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from app.knowledge.api._auth import require_api_key
from app.knowledge.vector_client import COLLECTION_CHUNKS, VectorRecord, write_chunk_vector

router = APIRouter(prefix="/api/v1/knowledge", tags=["知识 Worker 写入"])


class VectorUpsertRequest(BaseModel):
    evidence_id: str = Field(min_length=1, max_length=200)
    vector: list[float] = Field(min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)
    collection: str = Field(default=COLLECTION_CHUNKS, max_length=100)


@router.post("/vector/upsert")
async def vector_upsert(req: VectorUpsertRequest, x_api_key: str | None = Header(default=None)):
    require_api_key(x_api_key)
    payload = dict(req.payload)
    payload.setdefault("evidence_id", req.evidence_id)
    record = VectorRecord(
        id=str(uuid.uuid5(uuid.NAMESPACE_DNS, req.evidence_id)),
        vector=req.vector,
        payload=payload,
    )
    if not write_chunk_vector(record, req.collection):
        raise HTTPException(502, "vector write failed")
    return {"ok": True}
```

`backend/app/main.py` 在 `app.include_router(evidence_router)`（第 203 行）之后加：

```python
app.include_router(worker_writes_router)
```

并在文件顶部的 knowledge 路由导入处加入 `worker_writes_router`（与 `worker_jobs_router` 同一组）：

```python
from app.knowledge.api.worker_writes import router as worker_writes_router
```

- [ ] **Step 5: 运行确认通过 + 回归**

Run: `cd backend && .venv/bin/python -m pytest tests/test_worker_writes_api.py -v`
Expected: PASS（3 passed）
Run: `cd backend && .venv/bin/python -m pytest tests/test_evidence_worker.py tests/test_ingestion_job_worker.py -v`
Expected: PASS（鉴权抽取未破坏既有行为）

- [ ] **Step 6: 提交**

```bash
git add backend/app/knowledge/api/_auth.py backend/app/knowledge/api/worker_writes.py \
        backend/app/knowledge/api/worker_jobs.py backend/app/main.py \
        backend/tests/test_worker_writes_api.py
git commit -m "feat(knowledge): add cloud vector upsert endpoint for remote workers"
```

---

### Task 3: 客户端 `upsert_vector` + worker 向量远端分支

**Files:**
- Modify: `backend/app/knowledge/worker_api_client.py`
- Modify: `backend/app/knowledge/evidence_worker.py:185-192`
- Test: `backend/tests/test_evidence_worker.py`（追加）

**Interfaces:**
- Consumes: Task 1 `build_evidence_vector_record`；Task 2 端点
- Produces:
  - `KnowledgeApiClient.upsert_vector(evidence_id: str, vector: list[float], payload: dict) -> bool`
  - `EvidenceExtractionWorker` 在远端模式下 `JOB_VECTOR` 返回 `{"status": "done", "vector_ok": True}`

- [ ] **Step 1: 写失败测试**

追加到 `backend/tests/test_evidence_worker.py`：

```python
def test_vector_job_remote_uses_api(monkeypatch) -> None:
    from app.knowledge.vector_client import VectorRecord

    service = FakeService()
    service.jobs = [
        {"job_id": "JV", "evidence_id": "EV:1", "job_type": JOB_VECTOR, "status": STATUS_PENDING}
    ]
    worker = EvidenceExtractionWorker(service=service)
    posted = {}

    class FakeApi:
        async def upsert_vector(self, evidence_id, vector, payload):
            posted["evidence_id"] = evidence_id
            posted["vector"] = vector
            posted["payload"] = payload
            return True

    def fake_build(evidence):
        return VectorRecord(id="p1", vector=[9.9], payload={"evidence_id": evidence["evidence_id"]})

    monkeypatch.setenv("KNOWLEDGE_API_URL", "http://cloud")
    monkeypatch.setenv("KNOWLEDGE_API_KEY", "k")
    monkeypatch.setattr("app.knowledge.evidence_worker.build_evidence_vector_record", fake_build)
    monkeypatch.setattr("app.knowledge.evidence_worker.KnowledgeApiClient", lambda *a, **k: FakeApi())

    result = asyncio.run(worker.run_once(limit=1, job_type=JOB_VECTOR))
    assert result["success"] == 1
    assert posted["evidence_id"] == "EV:1"
    assert posted["vector"] == [9.9]
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_evidence_worker.py::test_vector_job_remote_uses_api -v`
Expected: FAIL — `AttributeError` / 走到了直连 Qdrant 的老路径

- [ ] **Step 3: 实现客户端方法**

`backend/app/knowledge/worker_api_client.py` 在 `upsert_evidence` 之后追加：

```python
    async def upsert_vector(self, evidence_id, vector, payload):
        async with httpx.AsyncClient(timeout=self.timeout) as c:
            r = await c.post(
                f"{self.base_url}/api/v1/knowledge/vector/upsert",
                json={"evidence_id": evidence_id, "vector": list(vector), "payload": payload},
                headers=self.headers,
            )
        return r.is_success
```

- [ ] **Step 4: 实现 worker 远端分支**

`backend/app/knowledge/evidence_worker.py` 顶部 import 区加入：

```python
from app.knowledge.vector_client import build_evidence_vector_record
```

把 `JOB_VECTOR` 分支（第 185-192 行）替换为：

```python
            if job_type == JOB_VECTOR:
                import os
                if os.getenv("KNOWLEDGE_API_URL") and os.getenv("KNOWLEDGE_API_KEY"):
                    from app.knowledge.worker_api_client import KnowledgeApiClient

                    record = build_evidence_vector_record(evidence)
                    if record is None:
                        await self.service.mark_job_failed(job_id, "vector build rejected")
                        return {"status": "failed", "vector_ok": False}
                    client = KnowledgeApiClient(
                        os.environ["KNOWLEDGE_API_URL"], os.environ["KNOWLEDGE_API_KEY"]
                    )
                    ok = await client.upsert_vector(evidence_id, record.vector, record.payload)
                else:
                    ok = upsert_evidence_chunk_vector(evidence)
                result = {"vector_ok": ok}
                if ok:
                    await self.service.mark_job_done(job_id, result)
                    return {"status": "done", **result}
                await self.service.mark_job_failed(job_id, "vector upsert failed")
                return {"status": "failed", **result}
```

> 注：原 `JOB_VECTOR` 分支引用的 `upsert_evidence_chunk_vector` 仍从 `app.knowledge.vector_client` 导入（本地路径用），保持第 18 行 import 不变。

- [ ] **Step 5: 运行确认通过 + 回归**

Run: `cd backend && .venv/bin/python -m pytest tests/test_evidence_worker.py -v`
Expected: PASS（新增 1 个 + 既有 `test_vector_job_success` 全绿）

- [ ] **Step 6: 提交**

```bash
git add backend/app/knowledge/worker_api_client.py backend/app/knowledge/evidence_worker.py \
        backend/tests/test_evidence_worker.py
git commit -m "feat(knowledge): remote vector branch in evidence worker"
```

---

### Task 4: link 计算/落库拆分（本地路径行为不变）

**Files:**
- Modify: `backend/app/knowledge/linklayer/dict_match.py:78-98`
- Modify: `backend/app/knowledge/linklayer/ingest.py`
- Test: `backend/tests/test_linklayer_ingest.py`（既有用例须全绿）

**Interfaces:**
- Consumes: `load_vocabulary`、`match_all`、`extract_keywords`、`ensure_keyword`
- Produces:
  - `build_subject_index(use_db: bool = True) -> SubjectIndex`
  - `LinkAction`（dataclass：`layer, norm_text, source, span_start, span_end, published_at, dimension=None, level=None`，方法 `to_payload() -> dict`）
  - `compute_link_actions(evidence: dict, *, skip_llm: bool = False, subject_index=None, use_db: bool = True) -> tuple[list[LinkAction], bool]`
  - `persist_link_actions(session, evidence_id: str, actions: list[LinkAction]) -> int`
  - `ingest_evidence(evidence_id, *, _session=None, skip_llm=False) -> dict`（签名与返回值不变）

- [ ] **Step 1: 写失败测试**

追加到 `backend/tests/test_linklayer_ingest.py`：

```python
def test_compute_link_actions_payload_has_span_and_source():
    import asyncio
    from app.knowledge.linklayer.ingest import compute_link_actions

    evidence = {
        "evidence_id": "EV:1",
        "text_excerpt": "公司公告称量产。",
        "subject_hint": {"ts_code": "300001.SZ"},
        "publish_date": "2026-05-21",
    }
    actions, llm_used = asyncio.run(
        compute_link_actions(evidence, skip_llm=True, use_db=False)
    )
    assert llm_used is False
    assert any(a.source == "hint" and a.norm_text == "300001.SZ" for a in actions)
    payload = actions[0].to_payload()
    assert set(payload) >= {"layer", "norm_text", "source", "span_start", "span_end"}
```

> 若该文件已无 `compute_link_actions` 相关导入，测试即为红。

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_linklayer_ingest.py::test_compute_link_actions_payload_has_span_and_source -v`
Expected: FAIL — `ImportError: cannot import name 'compute_link_actions'`

- [ ] **Step 3: `build_subject_index` 增加 use_db**

`backend/app/knowledge/linklayer/dict_match.py` 第 78-98 行改为：

```python
async def build_subject_index(use_db: bool = True) -> SubjectIndex:
    """构建 subject 层别名索引（JSON 别名 + PG stocks 表名，均尽力而为）。

    use_db=False 时跳过 PG（远端 worker 无数据库通道）。
    """
    alias_to_norm = load_alias_table()
    if not use_db:
        return SubjectIndex(alias_to_norm=alias_to_norm)
    try:
        from sqlalchemy import select

        from app.core.database import async_session
        from app.models.models import Stock

        async with async_session() as session:
            rows = await session.execute(select(Stock.ts_code, Stock.name))
            for ts_code, name in rows:
                if name:
                    alias_to_norm.setdefault(name, ts_code)
    except Exception:  # noqa: BLE001 — PG 不可达时降级为纯 JSON 索引
        logger.warning("stocks 表查询失败，跳过股票名索引（仅保留 JSON 别名）", exc_info=True)
    return SubjectIndex(alias_to_norm=alias_to_norm)
```

- [ ] **Step 4: 拆分 `ingest.py`**

`backend/app/knowledge/linklayer/ingest.py` 第 1-88 行替换为：

```python
# backend/app/knowledge/linklayer/ingest.py
"""链接层入库管线：dict match + LLM 浅提取 → 归一化 → keyword/link 幂等 upsert。"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.knowledge.evidence_service import EvidenceService
from app.knowledge.linklayer.dict_match import build_subject_index, match_all
from app.knowledge.linklayer.dictionaries import load_vocabulary
from app.knowledge.linklayer.llm_extract import extract_keywords
from app.knowledge.linklayer.models import Link
from app.knowledge.linklayer.normalize import canonicalize_subject, ensure_keyword

logger = logging.getLogger(__name__)


@dataclass
class LinkAction:
    layer: str
    norm_text: str
    source: str
    span_start: int
    span_end: int
    published_at: datetime | None = None
    dimension: str | None = None
    level: int | None = None

    def to_payload(self) -> dict:
        return {
            "layer": self.layer,
            "norm_text": self.norm_text,
            "source": self.source,
            "span_start": self.span_start,
            "span_end": self.span_end,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "dimension": self.dimension,
            "level": self.level,
        }


async def compute_link_actions(
    evidence: dict,
    *,
    skip_llm: bool = False,
    subject_index=None,
    use_db: bool = True,
) -> tuple[list[LinkAction], bool]:
    """计算一条 evidence 的 link 行集合（不做任何落库）。返回 (actions, llm_used)。"""
    text = evidence.get("text_excerpt") or ""
    vocab = load_vocabulary()
    if subject_index is None:
        subject_index = await build_subject_index(use_db=use_db)

    actions: list[LinkAction] = []
    published = _parse_date(evidence.get("publish_date"))
    for m in match_all(text, vocab, subject_index):
        actions.append(LinkAction(m.layer, m.norm_text, "dictionary", m.span_start, m.span_end, published))
        if m.layer == "stage" and m.dimension:
            actions.append(LinkAction("dimension", m.dimension, "dictionary", m.span_start, m.span_end, published))

    hint_subject = _subject_from_hint(evidence.get("subject_hint"))
    if hint_subject:
        actions.append(LinkAction("subject", hint_subject, "hint", 0, 0, published))

    llm_result = None if skip_llm else await extract_keywords(evidence)
    llm_used = llm_result is not None
    if llm_result:
        for surface in llm_result.get("company", []):
            norm = canonicalize_subject(surface, subject_index) or surface
            actions.append(LinkAction("subject", norm, "llm", 0, 0, published))
        for surface in llm_result.get("product", []):
            actions.append(LinkAction("scope", surface, "llm", 0, 0, published))
        for m in llm_result.get("metric", []):
            actions.append(LinkAction("dimension", m["name"], "llm", 0, 0, published))

    return actions, llm_used


async def persist_link_actions(session, evidence_id: str, actions: list[LinkAction]) -> int:
    """落库 link 行（幂等）。返回处理行数。"""
    link_count = 0
    for action in actions:
        kw_id = await ensure_keyword(session, action.layer, action.norm_text, source=action.source)
        base = pg_insert(Link).values(
            keyword_id=kw_id,
            evidence_id=evidence_id,
            span_start=action.span_start,
            span_end=action.span_end,
            published_at=action.published_at,
            source=action.source,
        )
        if action.source == "hint":
            stmt = base.on_conflict_do_update(
                index_elements=["keyword_id", "evidence_id", "span_start"],
                set_={"source": "hint"},
            )
        else:
            stmt = base.on_conflict_do_nothing()
        await session.execute(stmt)
        link_count += 1
    await session.commit()
    return link_count


async def ingest_evidence(evidence_id: str, *, _session=None, skip_llm: bool = False) -> dict:
    """对单条 evidence 建链。幂等：link PK 冲突 do nothing。行为与拆分前一致。"""
    svc = EvidenceService()
    evidence = await svc.get_evidence(evidence_id)
    if not evidence:
        return {"links": 0, "keywords": 0, "llm_used": False}

    actions, llm_used = await compute_link_actions(evidence, skip_llm=skip_llm)
    assert _session is not None, "需要 PG session（由 worker / script 传入）"
    link_count = await persist_link_actions(_session, evidence_id, actions)
    return {"links": link_count, "keywords": len(actions), "llm_used": llm_used}
```

（`_subject_from_hint`、`_parse_date` 保留在文件末尾不动。）

- [ ] **Step 5: 运行确认通过 + 回归**

Run: `cd backend && .venv/bin/python -m pytest tests/test_linklayer_ingest.py -v`
Expected: PASS（新增 1 个 + 既有用例全绿）
Run: `cd backend && .venv/bin/python -m pytest tests/test_evidence_worker.py tests/test_linklayer_candidates.py -v`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add backend/app/knowledge/linklayer/ingest.py backend/app/knowledge/linklayer/dict_match.py \
        backend/tests/test_linklayer_ingest.py
git commit -m "refactor(linklayer): split link compute from persistence"
```

---

### Task 5: 云端台账管线 + 端点 `/api/v1/knowledge/link/upsert`

**Files:**
- Create: `backend/app/knowledge/linklayer/link_pipeline.py`
- Modify: `backend/app/knowledge/api/worker_writes.py`
- Test: `backend/tests/test_link_pipeline.py`、`backend/tests/test_worker_writes_api.py`（追加）

**Interfaces:**
- Consumes: Task 4 `LinkAction`、`persist_link_actions`；`generate_candidates`/`persist_candidates`/`emit_radar_signals`
- Produces:
  - `run_link_ledger_pipeline(session, evidence_id: str) -> dict`（`{"candidates": int, "radar_signals": int}`）
  - `POST /api/v1/knowledge/link/upsert`，请求 `{evidence_id, actions: [LinkActionPayload]}`，响应 `{"ok": true, "links": int, "candidates": int, "radar_signals": int}`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_link_pipeline.py
from __future__ import annotations

import asyncio

from app.knowledge.linklayer.link_pipeline import run_link_ledger_pipeline


class FakeSession:
    def __init__(self):
        self.committed = False

    async def commit(self):
        self.committed = True


def test_pipeline_returns_counts(monkeypatch):
    calls = {}

    async def fake_generate(evidence_id, session):
        calls["generated"] = evidence_id
        return [{"obs_id": "O1", "subject_ts_code": "300001.SZ", "dimension": "量产",
                 "stage_raw": "量产", "stage_level": 2, "evidence_id": evidence_id}]

    async def fake_persist(cands, session):
        calls["persisted"] = len(cands)
        return 1

    async def fake_emit(cands, session):
        calls["emitted"] = len(cands)
        return 1

    monkeypatch.setattr("app.knowledge.linklayer.link_pipeline.generate_candidates", fake_generate)
    monkeypatch.setattr("app.knowledge.linklayer.link_pipeline.persist_candidates", fake_persist)
    monkeypatch.setattr("app.knowledge.linklayer.link_pipeline.emit_radar_signals", fake_emit)

    result = asyncio.run(run_link_ledger_pipeline(FakeSession(), "EV:1"))
    assert result == {"candidates": 1, "radar_signals": 1}
    assert calls["generated"] == "EV:1"
```

追加到 `backend/tests/test_worker_writes_api.py`：

```python
def test_link_upsert_requires_api_key(client):
    r = client.post("/api/v1/knowledge/link/upsert", json={"evidence_id": "EV:1", "actions": []})
    assert r.status_code == 401


def test_link_upsert_persists_and_runs_ledger(client):
    calls = {}

    async def fake_persist(session, evidence_id, actions):
        calls["persisted_evidence"] = evidence_id
        calls["actions"] = len(actions)
        return len(actions)

    async def fake_pipeline(session, evidence_id):
        calls["pipeline_evidence"] = evidence_id
        return {"candidates": 2, "radar_signals": 1}

    with patch("app.knowledge.api.worker_writes.persist_link_actions", side_effect=fake_persist), \
         patch("app.knowledge.api.worker_writes.run_link_ledger_pipeline", side_effect=fake_pipeline), \
         patch("app.knowledge.api.worker_writes.async_session") as fake_session_ctx:
        class _Ctx:
            async def __aenter__(self):
                return object()

            async def __aexit__(self, *a):
                return False

        fake_session_ctx.return_value = _Ctx()
        r = client.post(
            "/api/v1/knowledge/link/upsert",
            headers=HEADERS,
            json={
                "evidence_id": "EV:1",
                "actions": [
                    {"layer": "subject", "norm_text": "300001.SZ", "source": "hint",
                     "span_start": 0, "span_end": 0}
                ],
            },
        )
    assert r.status_code == 200
    assert r.json() == {"ok": True, "links": 1, "candidates": 2, "radar_signals": 1}
    assert calls["persisted_evidence"] == "EV:1"
    assert calls["pipeline_evidence"] == "EV:1"
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_link_pipeline.py tests/test_worker_writes_api.py -v`
Expected: FAIL — 模块/路由不存在

- [ ] **Step 3: 实现台账管线**

新建 `backend/app/knowledge/linklayer/link_pipeline.py`：

```python
# backend/app/knowledge/linklayer/link_pipeline.py
"""link 落库后的机械台账管线：候选观察 → 雷达信号 → 水位线推进。

只做机械派生（零 LLM），依赖 PG 读取（link 表 / watermark），
故运行在云端（worker 侧无数据库通道）。
"""
from __future__ import annotations

from app.knowledge.linklayer.candidates import (
    emit_radar_signals,
    generate_candidates,
    persist_candidates,
)


async def run_link_ledger_pipeline(session, evidence_id: str) -> dict:
    candidates = await generate_candidates(evidence_id, session)
    persisted = await persist_candidates(candidates, session)
    emitted = await emit_radar_signals(candidates, session)
    return {"candidates": persisted, "radar_signals": emitted}
```

- [ ] **Step 4: 实现端点**

`backend/app/knowledge/api/worker_writes.py` 追加：

```python
from app.core.database import async_session
from app.knowledge.linklayer.ingest import LinkAction, persist_link_actions
from app.knowledge.linklayer.link_pipeline import run_link_ledger_pipeline


class LinkActionPayload(BaseModel):
    layer: str = Field(min_length=1, max_length=40)
    norm_text: str = Field(min_length=1, max_length=500)
    source: str = Field(min_length=1, max_length=40)
    span_start: int = 0
    span_end: int = 0
    published_at: str | None = None
    dimension: str | None = None
    level: int | None = None


class LinkUpsertRequest(BaseModel):
    evidence_id: str = Field(min_length=1, max_length=200)
    actions: list[LinkActionPayload] = Field(default_factory=list)


@router.post("/link/upsert")
async def link_upsert(req: LinkUpsertRequest, x_api_key: str | None = Header(default=None)):
    require_api_key(x_api_key)
    actions = [
        LinkAction(
            layer=a.layer,
            norm_text=a.norm_text,
            source=a.source,
            span_start=a.span_start,
            span_end=a.span_end,
            published_at=_parse_iso(a.published_at),
            dimension=a.dimension,
            level=a.level,
        )
        for a in req.actions
    ]
    async with async_session() as session:
        links = await persist_link_actions(session, req.evidence_id, actions)
        ledger = await run_link_ledger_pipeline(session, req.evidence_id)
    return {"ok": True, "links": links, **ledger}
```

`published_at` 解析复用 `ingest._parse_date`（同模块导入）：

```python
from app.knowledge.linklayer.ingest import _parse_date as _parse_iso
```

- [ ] **Step 5: 运行确认通过 + 回归**

Run: `cd backend && .venv/bin/python -m pytest tests/test_link_pipeline.py tests/test_worker_writes_api.py -v`
Expected: PASS
Run: `cd backend && .venv/bin/python -m pytest tests/test_linklayer_candidates.py tests/test_linklayer_ingest.py -v`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add backend/app/knowledge/linklayer/link_pipeline.py \
        backend/app/knowledge/api/worker_writes.py \
        backend/tests/test_link_pipeline.py backend/tests/test_worker_writes_api.py
git commit -m "feat(knowledge): link upsert endpoint with cloud ledger pipeline"
```

---

### Task 6: 客户端 `upsert_links` + worker link 远端分支

**Files:**
- Modify: `backend/app/knowledge/worker_api_client.py`
- Modify: `backend/app/knowledge/evidence_worker.py:197-205`
- Test: `backend/tests/test_evidence_worker.py`（追加）

**Interfaces:**
- Consumes: Task 4 `compute_link_actions`；Task 5 端点
- Produces:
  - `KnowledgeApiClient.upsert_links(evidence_id: str, actions: list[dict]) -> dict | None`
  - 远端模式下 `JOB_LINK` 不再触碰 `async_session`，返回 `{"status": "done", "links": n}`

- [ ] **Step 1: 写失败测试**

追加到 `backend/tests/test_evidence_worker.py`：

```python
def test_link_job_remote_uses_api_and_no_db(monkeypatch) -> None:
    service = FakeService()
    service.jobs = [
        {"job_id": "JL", "evidence_id": "EV:1", "job_type": JOB_LINK, "status": STATUS_PENDING}
    ]
    worker = EvidenceExtractionWorker(service=service)
    posted = {}

    class FakeApi:
        async def upsert_links(self, evidence_id, actions):
            posted["evidence_id"] = evidence_id
            posted["actions"] = actions
            return {"ok": True, "links": len(actions)}

    def fake_compute(evidence, **kwargs):
        from app.knowledge.linklayer.ingest import LinkAction

        return [LinkAction("subject", "300001.SZ", "hint", 0, 0)], True

    def boom(*a, **k):
        raise AssertionError("远端模式不得使用 async_session")

    monkeypatch.setenv("KNOWLEDGE_API_URL", "http://cloud")
    monkeypatch.setenv("KNOWLEDGE_API_KEY", "k")
    monkeypatch.setattr("app.knowledge.evidence_worker.compute_link_actions", fake_compute)
    monkeypatch.setattr("app.knowledge.evidence_worker.KnowledgeApiClient", lambda *a, **k: FakeApi())
    monkeypatch.setattr("app.knowledge.evidence_worker.async_session", boom)

    result = asyncio.run(worker.run_once(limit=1, job_type=JOB_LINK))
    assert result["success"] == 1
    assert posted["evidence_id"] == "EV:1"
    assert posted["actions"][0]["layer"] == "subject"
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_evidence_worker.py::test_link_job_remote_uses_api_and_no_db -v`
Expected: FAIL — `AssertionError: 远端模式不得使用 async_session`

- [ ] **Step 3: 实现客户端方法**

`backend/app/knowledge/worker_api_client.py` 追加：

```python
    async def upsert_links(self, evidence_id, actions):
        async with httpx.AsyncClient(timeout=self.timeout) as c:
            r = await c.post(
                f"{self.base_url}/api/v1/knowledge/link/upsert",
                json={"evidence_id": evidence_id, "actions": actions},
                headers=self.headers,
            )
        if not r.is_success:
            return None
        return r.json()
```

- [ ] **Step 4: 实现 worker 远端分支**

`backend/app/knowledge/evidence_worker.py` 顶部 import 区加入（用原名导入，便于测试 monkeypatch
`app.knowledge.evidence_worker.compute_link_actions`）：

```python
from app.knowledge.linklayer.ingest import compute_link_actions
```

把 `JOB_LINK` 分支（第 197-205 行）替换为：

```python
            if job_type == JOB_LINK:
                import os
                if os.getenv("KNOWLEDGE_API_URL") and os.getenv("KNOWLEDGE_API_KEY"):
                    from app.knowledge.worker_api_client import KnowledgeApiClient

                    actions, _ = await compute_link_actions(evidence, use_db=False)
                    client = KnowledgeApiClient(
                        os.environ["KNOWLEDGE_API_URL"], os.environ["KNOWLEDGE_API_KEY"]
                    )
                    response = await client.upsert_links(
                        evidence_id, [a.to_payload() for a in actions]
                    )
                    if response is None:
                        await self.service.mark_job_failed(job_id, "link upsert failed")
                        return {"status": "failed", "links": 0}
                    result = {
                        "links": response.get("links", 0),
                        "candidates": response.get("candidates", 0),
                        "radar_signals": response.get("radar_signals", 0),
                    }
                    await self.service.mark_job_done(job_id, result)
                    return {"status": "done", **result}
                async with async_session() as session:
                    result = await ingest_evidence(evidence_id, _session=session)
                    candidates = await generate_candidates(evidence_id, session)
                    result["candidates"] = await persist_candidates(candidates, session)
                    result["radar_signals"] = await emit_radar_signals(candidates, session)
                await self.service.mark_job_done(job_id, result)
                return {"status": "done", **result}
```

- [ ] **Step 5: 运行确认通过 + 回归**

Run: `cd backend && .venv/bin/python -m pytest tests/test_evidence_worker.py -v`
Expected: PASS（新增 1 个 + 既有 `test_link_job_success` / `test_link_job_persists_candidates_and_emits_radar` 全绿）

- [ ] **Step 6: 提交**

```bash
git add backend/app/knowledge/worker_api_client.py backend/app/knowledge/evidence_worker.py \
        backend/tests/test_evidence_worker.py
git commit -m "feat(knowledge): remote link branch in evidence worker"
```

---

### Task 7: 全量回归 + 提交推送

- [ ] **Step 1: 跑全量后端测试**

Run: `cd backend && .venv/bin/python -m pytest -q`
Expected: 与改动前基线一致，无新增失败。

- [ ] **Step 2: 静态检查**

Run: `cd backend && .venv/bin/python -m ruff check app/knowledge`
Expected: 无新增告警。

- [ ] **Step 3: 提交并推送 main**

```bash
git add -A
git commit -m "chore(knowledge): P2 remote-write decoupling complete"
git push origin main
```

- [ ] **Step 4: 同步云端与 chemagent worker 代码**

云端（Mac 可达 `root@124.221.188.38`）与 chemagent（`lwm-server-chemagent`）各拉取同一 commit：
- 云端：`ssh root@124.221.188.38 'cd /home/lwm/code/QingShuiTouYan && git fetch origin && git log -1 origin/main'`
- chemagent：`ssh lwm-server-chemagent 'cd /root/wq && ...'`（按 spec §P3 的同步方式）

> 注：推送 main 前须确认 `git log origin/main` 与本地无分叉；若云端仓库长期落后，先以本地为源。

---

## Self-Review

**Spec coverage**

| Spec 要求 | 覆盖 |
|---|---|
| §5.2 `/vector/upsert` | Task 2 |
| §5.2 `/link/upsert` | Task 5 |
| §5.2 `/ledger/upsert` | 合并进 `/link/upsert`（云端管线），见 Task 5 说明 |
| §5.2 signal | 明确不在范围（见"范围说明"） |
| §5.3 `ingest_evidence` 拆分 | Task 4 |
| §5.3 `vector_client` 拆分 | Task 1 |
| §5.3 `worker_api_client` 增补 | Task 3、6 |
| §5.3 worker 远端分支 | Task 3、6 |
| §5.3 `candidates.py` 拆分 | 未拆分；改为云端管线整体运行（Task 5）。理由：候选/雷达逻辑需读 PG（link 行、watermark），无法在断网 worker 完成 |
| §12 幂等验收 | Task 2/5 沿用 PK 冲突语义；Task 7 回归 |
| 依赖最小化（Global Constraints） | 未新增依赖 |

**偏离说明**：spec §5.2 原列 3 个端点，本计划并成 2 个（`/vector/upsert`、`/link/upsert`），
`ledger` 段由云端在 link 落库后立即运行；`signal` 延后。建议同步修订 spec §5.2/§10 以保持一致。

**评审后追加缺口（2026-09-23 最终评审发现，已部分修复）**

| # | 缺口 | 处置 |
|---|---|---|
| G1 | 远端 link 调 `extract_keywords` 时仍会写 Mongo `keyword_extraction` 缓存 → "worker 无 DB"不成立 | **已修**（commit `e513098`）：`extract_keywords(persist=)` / `compute_link_actions(persist_llm_cache=)`，远端传 `False` 并回传 `llm_used` |
| G2 | 缓存写入被跳过 → 与 `backfill_keyword_links` 池扫描断点口径不一致 | **待补**（R7）：云端缓存写入（`/link/upsert` 载荷字段或独立端点）。仅重复 LLM 成本，非正确性 |
| G3 | `company_aliases.json` 不在仓库，远端 worker 字典层公司匹配可能全空 | **部署要求**（R8）：P3 生成/同步该文件；已加空表告警 |

**类型一致性**：`LinkAction`（Task 4 定义）在 Task 5/6 使用；`to_payload()` 字段与
`LinkActionPayload`（Task 5）一致；`write_chunk_vector`/`build_evidence_vector_record`（Task 1）
在 Task 2/3 使用；`require_api_key`（Task 2）在 Task 5 复用。
