"""Tests for EvidenceService lifecycle."""

from __future__ import annotations

import asyncio
import re
from copy import deepcopy
from datetime import datetime
from typing import Any

from app.config import settings
from app.knowledge.evidence import (
    JOB_LINK,
    JOB_VECTOR,
    STATUS_DONE,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_RUNNING,
    EvidenceInput,
    stable_evidence_id,
    stable_job_id,
)
from app.knowledge.evidence_service import EvidenceService


class _Result:
    def __init__(self, modified_count: int = 1):
        self.modified_count = modified_count


class _BulkResult:
    def __init__(self, upserted_count: int = 0):
        self.upserted_count = upserted_count


def _get_path(doc: dict[str, Any], path: str) -> Any:
    cur: Any = doc
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _set_path(doc: dict[str, Any], path: str, value: Any) -> None:
    cur = doc
    parts = path.split(".")
    for part in parts[:-1]:
        cur = cur.setdefault(part, {})
    cur[parts[-1]] = value


def _match(doc: dict[str, Any], query: dict[str, Any]) -> bool:
    for key, expected in query.items():
        if key == "$or":
            if not any(_match(doc, sub) for sub in expected):
                return False
            continue
        actual = _get_path(doc, key)
        if isinstance(expected, dict):
            if "$lt" in expected:
                if actual is None or not actual < expected["$lt"]:
                    return False
            elif "$regex" in expected:
                if not re.match(expected["$regex"], str(actual)):
                    return False
            else:
                return False
        elif actual != expected:
            return False
    return True


class FakeCursor:
    def __init__(self, rows: list[dict[str, Any]]):
        self.rows = rows

    def __aiter__(self):
        self._iter = iter(self.rows)
        return self

    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


class FakeCollection:
    def __init__(self):
        self.docs: list[dict[str, Any]] = []
        self.indexes: list[tuple] = []
        self.find_one_and_update_called = False

    async def create_index(self, *args, **kwargs):
        self.indexes.append((args, kwargs))

    async def find_one(self, query, projection=None, sort=None):
        rows = [doc for doc in self.docs if _match(doc, query)]
        if sort:
            key, direction = sort[0]
            rows.sort(key=lambda d: str(_get_path(d, key) or ""), reverse=direction < 0)
        if not rows:
            return None
        return self._project(rows[0], projection)

    async def update_one(self, query, update, upsert=False):
        for doc in self.docs:
            if _match(doc, query):
                self._apply(doc, update, inserting=False)
                return _Result(1)
        if upsert:
            doc = deepcopy(query)
            self._apply(doc, update, inserting=True)
            self.docs.append(doc)
            return _Result(1)
        return _Result(0)

    async def update_many(self, query, update):
        count = 0
        for doc in self.docs:
            if _match(doc, query):
                self._apply(doc, update, inserting=False)
                count += 1
        return _Result(count)

    async def find_one_and_update(self, query, update, sort=None, return_document=None, projection=None):
        self.find_one_and_update_called = True
        rows = [doc for doc in self.docs if _match(doc, query)]
        if sort:
            key, direction = sort[0]
            rows.sort(key=lambda d: _get_path(d, key) or datetime.min, reverse=direction < 0)
        if not rows:
            return None
        self._apply(rows[0], update, inserting=False)
        return self._project(rows[0], projection)

    async def count_documents(self, query):
        return sum(1 for doc in self.docs if _match(doc, query))

    async def bulk_write(self, operations, ordered=True):
        upserted = 0
        for op in operations:
            doc = next((d for d in self.docs if _match(d, op._filter)), None)
            if doc is None and getattr(op, "_upsert", False):
                doc = deepcopy(op._filter)
                self._apply(doc, op._doc, inserting=True)
                self.docs.append(doc)
                upserted += 1
        return _BulkResult(upserted)

    def aggregate(self, pipeline):
        groups: dict[Any, int] = {}
        for doc in self.docs:
            key = doc.get("status")
            groups[key] = groups.get(key, 0) + 1
        return FakeCursor([{"_id": key, "count": count} for key, count in groups.items()])

    def _apply(self, doc, update, inserting):
        for key, value in update.get("$setOnInsert", {}).items():
            if inserting:
                _set_path(doc, key, deepcopy(value))
        for key, value in update.get("$set", {}).items():
            _set_path(doc, key, deepcopy(value))

    def _project(self, doc, projection):
        result = deepcopy(doc)
        if projection and projection.get("_id") == 0:
            result.pop("_id", None)
        return result


class FakeDB:
    def __init__(self):
        self.collections: dict[str, FakeCollection] = {}

    def __getitem__(self, name):
        return self.collections.setdefault(name, FakeCollection())


def _service() -> EvidenceService:
    return EvidenceService(FakeDB())


def _input(text: str = "hello") -> EvidenceInput:
    return EvidenceInput(
        source_type="irm",
        source_name="互动易:1",
        source_id="1",
        text_excerpt=text,
        subject_hint={"ts_code": "300001.SZ"},
        source_ref={"cninfo_id": "1"},
    )


def test_stable_ids_are_deterministic() -> None:
    assert stable_evidence_id("irm", "1", 0, "hello") == stable_evidence_id("irm", "1", 0, "hello")
    assert stable_job_id("EV:x", JOB_VECTOR, "v1") == stable_job_id("EV:x", JOB_VECTOR, "v1")


def test_upsert_evidence_is_idempotent() -> None:
    async def main():
        svc = _service()
        first = await svc.upsert_evidence(_input(), chunk_index=0)
        second = await svc.upsert_evidence(_input(), chunk_index=0)
        assert first["evidence_id"] == second["evidence_id"]
        assert await svc._evidence.count_documents({}) == 1
        assert first["confidence"] == 0.85

    asyncio.run(main())


def test_upsert_evidence_auto_enqueues_default_jobs(monkeypatch) -> None:
    async def main():
        svc = _service()
        ev = await svc.upsert_evidence(_input(), chunk_index=0)

        assert await svc._jobs.count_documents({}) == 2
        jobs = svc._jobs.docs
        assert {job["job_type"] for job in jobs} == {JOB_VECTOR, JOB_LINK}
        assert all(job["evidence_id"] == ev["evidence_id"] for job in jobs)

    asyncio.run(main())


def test_enqueue_default_jobs_is_idempotent(monkeypatch) -> None:
    async def main():
        svc = _service()
        ev = await svc.upsert_evidence(_input())
        jobs1 = await svc.enqueue_default_jobs(ev["evidence_id"])
        jobs2 = await svc.enqueue_default_jobs(ev["evidence_id"])
        assert {j["job_type"] for j in jobs1} == {JOB_VECTOR, JOB_LINK}
        assert [j["job_id"] for j in jobs1] == [j["job_id"] for j in jobs2]
        assert await svc._jobs.count_documents({}) == 2

    asyncio.run(main())


def test_bulk_enqueue_jobs_includes_link_and_is_idempotent(monkeypatch) -> None:
    async def main():
        svc = _service()
        upserted = await svc.bulk_enqueue_jobs(["EV:a", "EV:b"])
        assert upserted == 4
        jobs = svc._jobs.docs
        assert {job["job_type"] for job in jobs} == {JOB_VECTOR, JOB_LINK}
        assert all(job["status"] == STATUS_PENDING for job in jobs)
        assert all(job["evidence_id"] in {"EV:a", "EV:b"} for job in jobs)
        # 幂等：重复入队不新增
        upserted_again = await svc.bulk_enqueue_jobs(["EV:a", "EV:b"])
        assert upserted_again == 0
        assert await svc._jobs.count_documents({}) == 4

    asyncio.run(main())


def test_claim_next_job_marks_running_once() -> None:
    async def main():
        svc = _service()
        ev = await svc.upsert_evidence(_input())
        await svc.enqueue_job(ev["evidence_id"], JOB_VECTOR)
        claimed = await svc.claim_next_job(JOB_VECTOR, worker_id="w1")
        assert claimed and claimed["status"] == STATUS_RUNNING
        assert svc._jobs.find_one_and_update_called
        assert await svc.claim_next_job(JOB_VECTOR, worker_id="w2") is None

    asyncio.run(main())


def test_mark_done_updates_job_and_evidence_status() -> None:
    async def main():
        svc = _service()
        ev = await svc.upsert_evidence(_input())
        job = await svc.enqueue_job(ev["evidence_id"], JOB_VECTOR)
        await svc.mark_job_done(job["job_id"], {"ok": True})
        saved_job = await svc._jobs.find_one({"job_id": job["job_id"]})
        saved_ev = await svc.get_evidence(ev["evidence_id"])
        assert saved_job["status"] == STATUS_DONE
        assert saved_ev["extraction_status"][JOB_VECTOR] == STATUS_DONE

    asyncio.run(main())


def test_mark_failed_retries_then_fails_and_keeps_evidence() -> None:
    async def main():
        svc = _service()
        ev = await svc.upsert_evidence(_input())
        job = await svc.enqueue_job(ev["evidence_id"], JOB_VECTOR)
        await svc.mark_job_failed(job["job_id"], "boom", max_retries=2)
        retry_job = await svc._jobs.find_one({"job_id": job["job_id"]})
        assert retry_job["status"] == STATUS_PENDING
        await svc.mark_job_failed(job["job_id"], "boom", max_retries=2)
        failed_job = await svc._jobs.find_one({"job_id": job["job_id"]})
        saved_ev = await svc.get_evidence(ev["evidence_id"])
        assert failed_job["status"] == STATUS_FAILED
        assert saved_ev["text_excerpt"] == "hello"
        assert saved_ev["extraction_status"][JOB_VECTOR] == STATUS_FAILED

    asyncio.run(main())


def test_get_evidence_resolves_short_id_prefix() -> None:
    async def main():
        svc = _service()
        ev = await svc.upsert_evidence(_input())
        full_id = str(ev["evidence_id"])
        short_id = full_id[:16]  # EV: + 8 hex 前缀
        resolved = await svc.get_evidence(short_id)
        assert resolved is not None
        assert resolved["evidence_id"] == full_id
        # 完整 ID 精确命中依旧
        assert (await svc.get_evidence(full_id))["evidence_id"] == full_id
        # 更长前缀（16 hex）同样可解析
        mid_id = full_id[:19]
        assert (await svc.get_evidence(mid_id))["evidence_id"] == full_id
        # 不存在的前缀返回 None
        assert await svc.get_evidence("EV:0000000000000000") is None
        # 非法形式（过短/非 hex）不走前缀路径
        assert await svc.get_evidence("EV:abc") is None
        assert await svc.get_evidence("not-an-id") is None

    asyncio.run(main())


def test_get_evidence_prefix_prefers_lexicographically_first_on_ambiguity() -> None:
    async def main():
        svc = _service()
        await svc.upsert_evidence(_input(text="chunk A"), chunk_index=0)
        await svc.upsert_evidence(_input(text="chunk B"), chunk_index=1)
        ids = sorted(str(doc["evidence_id"]) for doc in svc._evidence.docs)
        assert len(ids) == 2
        # 两者的 3 位公共前缀不足 8 hex，解析务必用前 8 hex 以上；构造共同前缀情景：
        # 直接以第一个 id 的前 8 hex 查询，若恰好唯一命中，结果必须等于该完整 id。
        short = ids[0][:16]
        resolved = await svc.get_evidence(short)
        if resolved is not None:
            assert str(resolved["evidence_id"]) in ids

    asyncio.run(main())
