"""Tests for EvidenceService lifecycle."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime
from typing import Any

from app.knowledge.evidence import (
    JOB_COMBINED,
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

    async def find_one(self, query, projection=None):
        for doc in self.docs:
            if _match(doc, query):
                return self._project(doc, projection)
        return None

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
    assert stable_job_id("EV:x", JOB_COMBINED, "v1") == stable_job_id("EV:x", JOB_COMBINED, "v1")


def test_upsert_evidence_is_idempotent() -> None:
    async def main():
        svc = _service()
        first = await svc.upsert_evidence(_input(), chunk_index=0)
        second = await svc.upsert_evidence(_input(), chunk_index=0)
        assert first["evidence_id"] == second["evidence_id"]
        assert await svc._evidence.count_documents({}) == 1
        assert first["confidence"] == 0.85

    asyncio.run(main())


def test_enqueue_default_jobs_is_idempotent() -> None:
    async def main():
        svc = _service()
        ev = await svc.upsert_evidence(_input())
        jobs1 = await svc.enqueue_default_jobs(ev["evidence_id"])
        jobs2 = await svc.enqueue_default_jobs(ev["evidence_id"])
        assert {j["job_type"] for j in jobs1} == {JOB_COMBINED, JOB_VECTOR}
        assert [j["job_id"] for j in jobs1] == [j["job_id"] for j in jobs2]
        assert await svc._jobs.count_documents({}) == 2

    asyncio.run(main())


def test_claim_next_job_marks_running_once() -> None:
    async def main():
        svc = _service()
        ev = await svc.upsert_evidence(_input())
        await svc.enqueue_job(ev["evidence_id"], JOB_COMBINED)
        claimed = await svc.claim_next_job(JOB_COMBINED, worker_id="w1")
        assert claimed and claimed["status"] == STATUS_RUNNING
        assert svc._jobs.find_one_and_update_called
        assert await svc.claim_next_job(JOB_COMBINED, worker_id="w2") is None

    asyncio.run(main())


def test_mark_done_updates_job_and_evidence_status() -> None:
    async def main():
        svc = _service()
        ev = await svc.upsert_evidence(_input())
        job = await svc.enqueue_job(ev["evidence_id"], JOB_COMBINED)
        await svc.mark_job_done(job["job_id"], {"ok": True})
        saved_job = await svc._jobs.find_one({"job_id": job["job_id"]})
        saved_ev = await svc.get_evidence(ev["evidence_id"])
        assert saved_job["status"] == STATUS_DONE
        assert saved_ev["extraction_status"][JOB_COMBINED] == STATUS_DONE

    asyncio.run(main())


def test_mark_failed_retries_then_fails_and_keeps_evidence() -> None:
    async def main():
        svc = _service()
        ev = await svc.upsert_evidence(_input())
        job = await svc.enqueue_job(ev["evidence_id"], JOB_COMBINED)
        await svc.mark_job_failed(job["job_id"], "boom", max_retries=2)
        retry_job = await svc._jobs.find_one({"job_id": job["job_id"]})
        assert retry_job["status"] == STATUS_PENDING
        await svc.mark_job_failed(job["job_id"], "boom", max_retries=2)
        failed_job = await svc._jobs.find_one({"job_id": job["job_id"]})
        saved_ev = await svc.get_evidence(ev["evidence_id"])
        assert failed_job["status"] == STATUS_FAILED
        assert saved_ev["text_excerpt"] == "hello"
        assert saved_ev["extraction_status"][JOB_COMBINED] == STATUS_FAILED

    asyncio.run(main())
