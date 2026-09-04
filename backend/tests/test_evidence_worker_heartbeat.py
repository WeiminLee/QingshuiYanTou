import asyncio

import pytest

from app.knowledge.evidence_worker import EvidenceExtractionWorker


@pytest.mark.asyncio
async def test_heartbeat_stops_when_lock_is_lost(monkeypatch):
    calls = []

    class Service:
        async def heartbeat_job(self, job_id, worker_id):
            calls.append((job_id, worker_id))
            return False

    worker = EvidenceExtractionWorker(service=Service(), worker_id="w1")
    original_sleep = asyncio.sleep
    async def immediate_sleep(_):
        await original_sleep(0)
    monkeypatch.setattr(asyncio, "sleep", immediate_sleep)
    await asyncio.wait_for(worker._heartbeat("j1"), timeout=0.1)
    assert calls == [("j1", "w1")]
