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
