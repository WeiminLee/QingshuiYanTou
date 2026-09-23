"""Tests for EvidenceExtractionWorker."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

from app.knowledge.evidence import (
    JOB_COMBINED,
    JOB_LINK,
    JOB_SIGNAL,
    JOB_VECTOR,
    STATUS_DONE,
    STATUS_FAILED,
    STATUS_PENDING,
)
from app.knowledge.evidence_worker import EvidenceExtractionWorker
from app.knowledge.linklayer.ledger_models import Watermark
from app.knowledge.linklayer.models import Keyword, Link


class FakeService:
    def __init__(self):
        self.evidence = {
            "EV:1": {
                "evidence_id": "EV:1",
                "source_type": "irm",
                "source_name": "互动易:1",
                "text_excerpt": "公司公告称量产并导入客户。",
                "subject_hint": {"ts_code": "300001.SZ"},
                "source_ref": {},
                "observed_at": "2026-05-21T00:00:00",
                "publish_date": "2026-05-21",
                "confidence": 0.85,
            },
            "EV:2": {
                "evidence_id": "EV:2",
                "source_type": "irm",
                "source_name": "互动易:2",
                "text_excerpt": "订单排产到 2027 年。",
                "subject_hint": {"ts_code": "300002.SZ"},
                "source_ref": {},
                "observed_at": "2026-05-21T00:00:00",
                "publish_date": "2026-05-21",
                "confidence": 0.85,
            },
        }
        self.jobs = []
        self.done = []
        self.failed = []
        self.skipped = []

    async def get_evidence(self, evidence_id: str):
        return self.evidence.get(evidence_id)

    async def claim_next_job(self, job_type: str | None = None, worker_id: str = "", stale_after_minutes: int = 30):
        for job in self.jobs:
            if job["status"] == STATUS_PENDING and (job_type is None or job["job_type"] == job_type):
                job["status"] = "running"
                return job
        return None

    async def mark_job_done(self, job_id: str, result: dict | None = None) -> None:
        self.done.append((job_id, result or {}))
        for job in self.jobs:
            if job["job_id"] == job_id:
                await self.update_evidence_status(job["evidence_id"], job["job_type"], STATUS_DONE)
                break

    async def mark_job_failed(self, job_id: str, error: str, max_retries: int = 3) -> None:
        self.failed.append((job_id, error))
        for job in self.jobs:
            if job["job_id"] == job_id:
                await self.update_evidence_status(job["evidence_id"], job["job_type"], STATUS_FAILED)
                break

    async def mark_job_skipped(self, job_id: str, reason: str = "") -> None:
        self.skipped.append((job_id, reason))
        for job in self.jobs:
            if job["job_id"] == job_id:
                await self.update_evidence_status(job["evidence_id"], job["job_type"], "skipped")
                break

    async def update_evidence_status(
        self, evidence_id: str, job_type: str, status: str, extractor_version: str = "evidence-v1"
    ) -> None:
        self.evidence[evidence_id].setdefault("status_updates", []).append((job_type, status))


def _worker(service=None) -> EvidenceExtractionWorker:
    return EvidenceExtractionWorker(
        service=service or FakeService(), batch_size=2, max_concurrency=2, worker_id="test-worker"
    )


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows

    def one(self):
        return self._rows[0]

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


class _StatefulLinkSession:
    """链接 job 集成测试的有状态假会话：内存水位线 + 观察/信号按唯一键去重。"""

    def __init__(self, link_rows):
        self.link_rows = link_rows
        self.watermarks: dict[tuple[str, str, str], int] = {}
        self.observation_inserts = []
        self.signal_inserts = []
        self._seen_obs_ids: set[str] = set()
        self._seen_signal_ids: set[str] = set()

    async def execute(self, stmt):
        params = stmt.compile(dialect=postgresql.dialect()).params
        entities = [d["entity"] for d in getattr(stmt, "column_descriptions", [])]
        if Watermark in entities:
            key = (params["subject_ts_code_1"], params["dimension_1"], params["dimension_scope_1"])
            if key not in self.watermarks:
                return _Result([])
            return _Result([
                Watermark(
                    subject_ts_code=key[0],
                    dimension=key[1],
                    dimension_scope=key[2],
                    max_level=self.watermarks[key],
                )
            ])
        table = getattr(stmt, "table", None)
        if table is None:  # select(Keyword, Link)
            return _Result(self.link_rows)
        if table.name == "observations":
            if params["obs_id"] in self._seen_obs_ids:
                return _Result([])
            self._seen_obs_ids.add(params["obs_id"])
            self.observation_inserts.append(params)
            return _Result([(1,)])
        if table.name == "signals":
            if params["signal_id"] in self._seen_signal_ids:
                return _Result([])
            self._seen_signal_ids.add(params["signal_id"])
            self.signal_inserts.append(params)
            return _Result([(1,)])
        if table.name == "watermarks":
            key = (params["subject_ts_code"], params["dimension"], params["dimension_scope"])
            level = max(self.watermarks.get(key, 0), params["max_level"])
            self.watermarks[key] = level
            return _Result([
                SimpleNamespace(
                    subject_ts_code=key[0],
                    dimension=key[1],
                    dimension_scope=key[2],
                    max_level=level,
                    max_value=None,
                    first_reached_at=None,
                    last_updated_at=None,
                )
            ])
        raise AssertionError(f"unexpected statement: {stmt}")

    async def commit(self):
        return None


class _SessionContext:
    def __init__(self, session):
        self._session = session

    def __call__(self):
        return self

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *exc):
        return False


def _session_factory(session):
    return _SessionContext(session)


def _kw(norm_text, layer, keyword_id=None, aliases=None):
    return Keyword(
        keyword_id=keyword_id or f"KW:{norm_text}",
        layer=layer,
        norm_text=norm_text,
        display_text=norm_text,
        aliases=aliases if aliases is not None else [],
    )


def _link(evidence_id="EV:1", span_start=0):
    return Link(keyword_id="KW:x", evidence_id=evidence_id, span_start=span_start, span_end=0, source="dictionary")


def test_run_once_limit_zero_returns_zero() -> None:
    async def main():
        worker = _worker()
        result = await worker.run_once(limit=0)
        assert result == {
            "claimed": 0,
            "success": 0,
            "failed": 0,
            "skipped": 0,
            "job_type": "combined",
        }

    asyncio.run(main())


def test_successful_combined_job_marks_done_and_updates_evidence(monkeypatch) -> None:
    async def main():
        async def fake_extract(evidence):
            return {"entities_created": 1, "relations_created": 0}

        monkeypatch.setattr("app.knowledge.evidence_worker.extract_evidence_async", fake_extract)
        service = FakeService()
        service.jobs = [
            {
                "job_id": "J1",
                "evidence_id": "EV:1",
                "job_type": JOB_COMBINED,
                "status": STATUS_PENDING,
            }
        ]
        worker = _worker(service)
        result = await worker.run_once(limit=1, job_type=JOB_COMBINED)
        assert result["claimed"] == 1
        assert result["success"] == 1
        assert service.done
        assert service.evidence["EV:1"]["status_updates"][-1] == (JOB_COMBINED, STATUS_DONE)

    asyncio.run(main())


def test_missing_evidence_marks_job_failed() -> None:
    async def main():
        service = FakeService()
        service.jobs = [
            {
                "job_id": "J1",
                "evidence_id": "EV:missing",
                "job_type": JOB_COMBINED,
                "status": STATUS_PENDING,
            }
        ]
        worker = _worker(service)
        result = await worker.run_once(limit=1, job_type=JOB_COMBINED)
        assert result["failed"] == 1
        assert service.failed

    asyncio.run(main())


def test_extractor_exception_marks_failed() -> None:
    async def main():
        service = FakeService()
        service.evidence["EV:1"]["source_type"] = "announcement"
        service.jobs = [
            {
                "job_id": "J1",
                "evidence_id": "EV:1",
                "job_type": JOB_COMBINED,
                "status": STATUS_PENDING,
            }
        ]
        worker = _worker(service)
        from app.knowledge import evidence_worker as ew

        orig = ew.extract_evidence_async

        async def boom(*args, **kwargs):
            raise RuntimeError("boom")

        ew.extract_evidence_async = boom
        try:
            result = await worker.run_once(limit=1, job_type=JOB_COMBINED)
            assert result["failed"] == 1
            assert service.failed
            assert service.evidence["EV:1"]["status_updates"][-1] == (JOB_COMBINED, STATUS_FAILED)
        finally:
            ew.extract_evidence_async = orig

    asyncio.run(main())


def test_two_jobs_processed(monkeypatch) -> None:
    async def main():
        async def fake_extract(evidence):
            return {"entities_created": 1, "relations_created": 0}

        monkeypatch.setattr("app.knowledge.evidence_worker.extract_evidence_async", fake_extract)
        service = FakeService()
        service.jobs = [
            {
                "job_id": "J1",
                "evidence_id": "EV:1",
                "job_type": JOB_COMBINED,
                "status": STATUS_PENDING,
            },
            {
                "job_id": "J2",
                "evidence_id": "EV:2",
                "job_type": JOB_COMBINED,
                "status": STATUS_PENDING,
            },
        ]
        worker = _worker(service)
        result = await worker.run_once(limit=2, job_type=JOB_COMBINED)
        assert result["claimed"] == 2
        assert result["success"] == 2

    asyncio.run(main())


@pytest.mark.integration
def test_vector_job_success() -> None:
    async def main():
        service = FakeService()
        service.jobs = [
            {
                "job_id": "J3",
                "evidence_id": "EV:1",
                "job_type": JOB_VECTOR,
                "status": STATUS_PENDING,
            }
        ]
        worker = _worker(service)
        result = await worker.run_once(limit=1, job_type=JOB_VECTOR)
        assert result["success"] == 1

    asyncio.run(main())


def test_signal_job_success(monkeypatch) -> None:
    async def main():
        service = FakeService()
        service.jobs = [
            {
                "job_id": "J4",
                "evidence_id": "EV:1",
                "job_type": JOB_SIGNAL,
                "status": STATUS_PENDING,
            }
        ]
        calls = []

        async def fake_ingest(evidence):
            calls.append(evidence["evidence_id"])
            return {"signals_upserted": 1, "propagations_upserted": 2}

        monkeypatch.setattr("app.knowledge.evidence_worker.ingest_evidence_signals", fake_ingest)

        worker = _worker(service)
        result = await worker.run_once(limit=1, job_type=JOB_SIGNAL)

        assert result["success"] == 1
        assert calls == ["EV:1"]
        assert service.done[-1][1] == {"signals_upserted": 1, "propagations_upserted": 2}
        assert service.evidence["EV:1"]["status_updates"][-1] == (JOB_SIGNAL, STATUS_DONE)

    asyncio.run(main())


def test_link_job_success(monkeypatch) -> None:
    async def main():
        async def fake_ingest(evidence_id, *, _session=None):
            return {"links": 3, "keywords": 3, "llm_used": True}

        monkeypatch.setattr("app.knowledge.evidence_worker.ingest_evidence", fake_ingest)
        monkeypatch.setattr(
            "app.knowledge.evidence_worker.async_session", _session_factory(_StatefulLinkSession([]))
        )

        service = FakeService()
        service.jobs = [
            {
                "job_id": "J5",
                "evidence_id": "EV:1",
                "job_type": JOB_LINK,
                "status": STATUS_PENDING,
            }
        ]
        worker = _worker(service)
        result = await worker.run_once(limit=1, job_type=JOB_LINK)

        assert result["success"] == 1
        assert service.done[-1][1] == {
            "links": 3,
            "keywords": 3,
            "llm_used": True,
            "candidates": 0,
            "radar_signals": 0,
        }
        assert service.evidence["EV:1"]["status_updates"][-1] == (JOB_LINK, STATUS_DONE)

    asyncio.run(main())


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

    async def fake_compute(evidence, **kwargs):
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


def test_link_job_remote_does_not_touch_mongo(monkeypatch) -> None:
    service = FakeService()
    service.jobs = [
        {"job_id": "JM", "evidence_id": "EV:1", "job_type": JOB_LINK, "status": STATUS_PENDING}
    ]
    worker = EvidenceExtractionWorker(service=service)
    posted = {}

    class FakeApi:
        async def upsert_links(self, evidence_id, actions):
            posted["actions"] = actions
            return {"ok": True, "links": len(actions), "candidates": 1, "radar_signals": 0}

    class BoomEvidenceService:
        def __init__(self, *a, **k):
            raise AssertionError("remote link path must not construct EvidenceService")

    async def fake_chat(*a, **k):
        return '{"company": ["宁德时代"], "product": ["压延铜箔"], "metric": []}'

    monkeypatch.setenv("KNOWLEDGE_API_URL", "http://cloud")
    monkeypatch.setenv("KNOWLEDGE_API_KEY", "k")
    monkeypatch.setattr("app.knowledge.evidence_worker.KnowledgeApiClient", lambda *a, **k: FakeApi())
    monkeypatch.setattr(
        "app.knowledge.evidence_service.EvidenceService", BoomEvidenceService
    )
    monkeypatch.setattr("app.knowledge.linklayer.llm_extract.chat_async", fake_chat)

    result = asyncio.run(worker.run_once(limit=1, job_type=JOB_LINK))
    assert result["success"] == 1
    assert any(a["source"] == "llm" for a in posted["actions"])


def test_link_job_persists_candidates_and_emits_radar(monkeypatch) -> None:
    """链接 job 集成链路：建链 → 机械候选落库 → 雷达信号 + 水位线推进（广度触发器）。

    ingest 打桩，generate_candidates/persist_candidates/emit_radar_signals 走真实逻辑。
    第二轮同 level 复跑：观察 obs_id 幂等冲突、水位线拦截，不再产新信号。
    """

    async def main():
        async def fake_ingest(evidence_id, *, _session=None):
            return {"links": 2, "keywords": 2, "llm_used": True}

        link_rows = [
            (_kw("003026.SZ", "subject"), _link()),
            (_kw("量产", "stage"), _link(span_start=10)),
        ]
        session = _StatefulLinkSession(link_rows)
        monkeypatch.setattr("app.knowledge.evidence_worker.ingest_evidence", fake_ingest)
        monkeypatch.setattr("app.knowledge.evidence_worker.async_session", _session_factory(session))

        service = FakeService()
        service.jobs = [
            {"job_id": "J5", "evidence_id": "EV:1", "job_type": JOB_LINK, "status": STATUS_PENDING},
            {"job_id": "J6", "evidence_id": "EV:1", "job_type": JOB_LINK, "status": STATUS_PENDING},
        ]
        worker = _worker(service)
        await worker.run_once(limit=1, job_type=JOB_LINK)

        # 第一轮：候选已按 pipeline/candidate 落库，雷达信号已产出，水位线推进
        assert service.done[0][0] == "J5"
        assert service.done[0][1] == {"links": 2, "keywords": 2, "llm_used": True, "candidates": 1, "radar_signals": 1}
        assert len(session.observation_inserts) == 1
        obs_params = session.observation_inserts[0]
        assert obs_params["written_by"] == "pipeline"
        assert obs_params["status"] == "candidate"
        assert obs_params["stage_level"] == 6
        assert len(session.signal_inserts) == 1
        assert session.signal_inserts[0]["signal_id"].startswith("LL:OB:")
        assert session.watermarks[("003026.SZ", "产线进展", "")] == 6

        # 第二轮（同 level）：obs_id 幂等冲突 + 水位线拦截 → 不产新信号、不落新观察
        await worker.run_once(limit=1, job_type=JOB_LINK)
        assert service.done[1][0] == "J6"
        assert service.done[1][1] == {"links": 2, "keywords": 2, "llm_used": True, "candidates": 0, "radar_signals": 0}
        assert len(session.signal_inserts) == 1
        assert len(session.observation_inserts) == 1
        assert session.watermarks[("003026.SZ", "产线进展", "")] == 6

    asyncio.run(main())
