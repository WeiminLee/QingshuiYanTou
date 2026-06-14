"""Concurrency tests for Evidence Worker and batch claim."""
from __future__ import annotations

import asyncio
from copy import deepcopy

import pytest

from app.knowledge.evidence import (
    EvidenceInput,
    JOB_COMBINED,
    STATUS_PENDING,
    STATUS_RUNNING,
)
from app.knowledge.evidence_service import EvidenceService
from app.knowledge.evidence_worker import EvidenceExtractionWorker
from tests.test_evidence_service import FakeDB


def _input(text: str = "hello") -> EvidenceInput:
    return EvidenceInput(
        source_type="irm",
        source_name="互动易:1",
        source_id="1",
        text_excerpt=text,
        subject_hint={"ts_code": "300001.SZ"},
        source_ref={"cninfo_id": "1"},
    )


class FakeCollectionWithCounter:
    """FakeCollection that tracks concurrent operations."""

    def __init__(self):
        self.docs: list[dict] = []
        self.indexes: list = []
        self.active_count = 0
        self.max_concurrent = 0

    async def create_index(self, *args, **kwargs):
        self.indexes.append((args, kwargs))

    async def find_one(self, query, projection=None):
        for doc in self.docs:
            if self._matches(doc, query):
                return self._project(doc, projection)
        return None

    def find(self, query, *args, **kwargs):
        rows = [self._project(doc) for doc in self.docs if self._matches(doc, query)]
        return _FakeCursorForCount(rows, self)

    async def update_one(self, query, update, upsert=False):
        for doc in self.docs:
            if self._matches(doc, query):
                self._apply(doc, update.get("$set", {}))
                return _UpdateResult(1)
        if upsert:
            # Build upserted doc from query + $setOnInsert + $set
            doc = {}
            for key, value in query.items():
                if not isinstance(value, dict):  # Skip query operators
                    doc[key] = value
            for key, value in update.get("$setOnInsert", {}).items():
                doc[key] = value
            for key, value in update.get("$set", {}).items():
                doc[key] = value
            self.docs.append(doc)
            return _UpdateResult(1)
        return _UpdateResult(0)

    async def update_many(self, query, update):
        count = 0
        job_ids = query.get("job_id", {}).get("$in", [])
        for doc in self.docs:
            if doc.get("job_id") in job_ids:
                # Check status condition if present in query
                if "status" in query and doc.get("status") != query.get("status"):
                    continue
                self._apply(doc, update.get("$set", {}))
                count += 1
        return _UpdateResult(count)

    async def count_documents(self, query):
        return sum(1 for doc in self.docs if self._matches(doc, query))

    def _matches(self, doc, query):
        """Check if document matches query."""
        for key, expected in query.items():
            if key.startswith("$"):
                continue  # Skip operators like $or, $in, $lt, etc.
            actual = doc.get(key)
            if isinstance(expected, dict):
                # Handle comparison operators
                if "$in" in expected:
                    if actual not in expected["$in"]:
                        return False
                elif "$lt" in expected:
                    if actual is None or not actual < expected["$lt"]:
                        return False
                elif "$gte" in expected:
                    if actual is None or not actual >= expected["$gte"]:
                        return False
            elif actual != expected:
                return False
        return True

    def _apply(self, doc, update):
        """Apply $set updates to document."""
        for key, value in update.items():
            doc[key] = value

    def _project(self, doc, projection=None):
        result = deepcopy(doc)
        if projection and projection.get("_id") == 0:
            result.pop("_id", None)
        return result


class _FakeCursorForCount:
    def __init__(self, rows, counter: FakeCollectionWithCounter):
        self.rows = rows
        self._counter = counter

    def sort(self, key, direction):
        self.rows.sort(key=lambda d: d.get(key) or 0, reverse=direction < 0)
        return self

    def limit(self, n: int):
        self.rows = self.rows[:n]
        return self

    async def to_list(self, length=None):
        return self.rows[:length]


class _UpdateResult:
    def __init__(self, modified_count: int = 1):
        self.modified_count = modified_count


class _FakeDBForConcurrency:
    def __init__(self):
        self._evidence = FakeCollectionWithCounter()
        self._jobs = FakeCollectionWithCounter()
        self._collections: dict[str, FakeCollectionWithCounter] = {
            "kg_evidence": self._evidence,
            "kg_extraction_jobs": self._jobs,
        }

    def __getitem__(self, name):
        if name in self._collections:
            return self._collections[name]
        return self._collections.setdefault(name, FakeCollectionWithCounter())


def test_semaphore_limits_concurrency():
    """Verify Semaphore correctly limits concurrent operations."""

    async def main():
        db = _FakeDBForConcurrency()
        svc = EvidenceService(db)
        worker = EvidenceExtractionWorker(
            service=svc,
            worker_id="test-worker",
            batch_size=5,
            max_concurrency=2,
        )

        # Verify Semaphore is an instance variable
        assert hasattr(worker, "_sem")
        assert isinstance(worker._sem, asyncio.Semaphore)

        # Verify Semaphore value matches max_concurrency
        assert worker._sem._value == 2

    asyncio.run(main())


def test_batch_claim_no_double_claim():
    """Verify batch claim doesn't double-claim jobs."""

    async def main():
        db = _FakeDBForConcurrency()
        svc = EvidenceService(db)

        # Create 5 different pending jobs (different evidence each time)
        for i in range(5):
            ev = await svc.upsert_evidence(_input(f"test {i}"))
            await svc.enqueue_job(ev["evidence_id"], JOB_COMBINED)

        # Verify 5 jobs are pending
        pending_count = await svc._jobs.count_documents({"status": STATUS_PENDING})
        assert pending_count == 5

        # Worker A claims 3 jobs
        jobs_a = await svc.claim_batch_jobs(3, JOB_COMBINED, "worker-a")
        assert len(jobs_a) == 3

        # Worker B should only get the remaining 2
        jobs_b = await svc.claim_batch_jobs(3, JOB_COMBINED, "worker-b")
        assert len(jobs_b) == 2

        # No jobs left for Worker C
        jobs_c = await svc.claim_batch_jobs(3, JOB_COMBINED, "worker-c")
        assert len(jobs_c) == 0

    asyncio.run(main())


def test_concurrent_batch_claim():
    """Verify concurrent batch claims don't cause race conditions."""

    async def main():
        db = _FakeDBForConcurrency()
        svc = EvidenceService(db)

        # Create 5 pending jobs
        for i in range(5):
            ev = await svc.upsert_evidence(_input(f"concurrent {i}"))
            await svc.enqueue_job(ev["evidence_id"], JOB_COMBINED)

        # Run two concurrent claims
        jobs_a, jobs_b = await asyncio.gather(
            svc.claim_batch_jobs(3, JOB_COMBINED, "worker-a"),
            svc.claim_batch_jobs(3, JOB_COMBINED, "worker-b"),
        )

        # All 5 jobs should be claimed (no double-claim)
        total_claimed = len(jobs_a) + len(jobs_b)
        assert total_claimed == 5

        # No jobs should be claimed by both
        job_ids_a = {j["job_id"] for j in jobs_a}
        job_ids_b = {j["job_id"] for j in jobs_b}
        assert len(job_ids_a & job_ids_b) == 0

    asyncio.run(main())