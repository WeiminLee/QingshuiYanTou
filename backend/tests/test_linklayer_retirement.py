"""三元组抽取（combined job → Neo4j 写入）退役开关测试。"""

from __future__ import annotations

import asyncio

from app.config import settings
from app.knowledge.evidence import JOB_LINK, JOB_VECTOR
from app.knowledge.evidence_service import EvidenceService


class _RecordingJobsCollection:
    """记录所有入队 job_type 的假 jobs collection。"""

    def __init__(self) -> None:
        self.job_types: list[str] = []

    async def create_index(self, *args, **kwargs):
        pass

    async def update_one(self, query, update, upsert=False):
        self.job_types.append(update["$setOnInsert"]["job_type"])
        return type("R", (), {"modified_count": 1})()

    async def find_one(self, query, projection=None):
        return None

    async def bulk_write(self, operations, ordered=True):
        for op in operations:
            self.job_types.append(op._doc["$setOnInsert"]["job_type"])
        return type("R", (), {"upserted_count": len(operations)})()


class _FakeDB:
    def __init__(self) -> None:
        self.jobs = _RecordingJobsCollection()

    def __getitem__(self, name):
        return self.jobs


def test_enable_kg_extraction_flag_exists():
    from app.config import Settings
    assert hasattr(Settings(), "enable_kg_extraction")


def test_flag_off_skips_combined_job(monkeypatch):
    """开关关闭后，默认入队集合变为 {vector, link}，不再有 combined。"""

    async def check_enqueue_default():
        svc = EvidenceService(_FakeDB())
        jobs = await svc.enqueue_default_jobs("EV:x")
        return {j["job_type"] for j in jobs}, set(svc._jobs.job_types)

    async def check_bulk_enqueue():
        svc = EvidenceService(_FakeDB())
        upserted = await svc.bulk_enqueue_jobs(["EV:a", "EV:b"])
        return upserted, set(svc._jobs.job_types)

    monkeypatch.setattr(settings, "enable_kg_extraction", False)

    returned, recorded = asyncio.run(check_enqueue_default())
    assert returned == {JOB_VECTOR, JOB_LINK}
    assert recorded == {JOB_VECTOR, JOB_LINK}

    upserted, bulk_types = asyncio.run(check_bulk_enqueue())
    assert upserted == 4
    assert bulk_types == {JOB_VECTOR, JOB_LINK}


def test_neo4j_kg_search_disabled_in_registry():
    """neo4j_kg_search 应标记 enabled: false，并提示用 pull_history 替代。"""
    import yaml

    from app.reasoning.registry.loader import _CONFIG_PATH

    with open(_CONFIG_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    entry = next(t for t in data["tools"] if t["name"] == "neo4j_kg_search")
    assert entry.get("enabled") is False
    assert entry["description"].startswith("[已弃用]")
    assert "pull_history" in entry["description"]
