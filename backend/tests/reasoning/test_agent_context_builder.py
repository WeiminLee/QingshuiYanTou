from unittest.mock import AsyncMock

import pytest

import app.reasoning.context.builder as builder_mod
from app.reasoning.context.builder import AgentContextBuilder, match_user_hits
from app.reasoning.context.schemas import UserSnapshotDTO


def test_match_user_hits_uses_signal_path_nodes_and_preferences():
    detail = {
        "subject_name": "中际旭创",
        "propagations": [{"target_name": "光芯片", "signal_path": {"nodes": ["中际旭创", "光模块", "光芯片"]}}],
    }
    snapshot = UserSnapshotDTO(
        user_id="lwm",
        portfolio=[{"ts_code": "300308.SZ", "name": "中际旭创"}],
        preferences=[{"subject": "光模块", "stance": "关注"}],
    )

    hits = match_user_hits(detail, snapshot)

    assert hits.portfolio == ["中际旭创"]
    assert hits.preferences == ["光模块"]


@pytest.mark.asyncio
async def test_builder_with_signal_id_builds_prompt_context(monkeypatch):
    async def fake_snapshot(user_id):
        return UserSnapshotDTO(user_id=user_id, portfolio=[{"name": "中际旭创", "ts_code": "300308.SZ"}]), []

    async def fake_signal(signal_id):
        return {
            "signal_id": signal_id,
            "title": "800G 光模块规模量产",
            "summary": "量产确认",
            "source_type": "announcement",
            "subject_name": "中际旭创",
            "subject_type": "company",
            "signal_type": "mass_production",
            "polarity": "positive",
            "value_score": 92,
            "confidence": 0.92,
            "evidence_excerpt": "相关产品已进入规模量产阶段",
            "memory": {"schema_version": "signal.memory.v1", "signal_id": signal_id, "lifecycle_status": "active", "user_status": "new"},
            "propagations": [{"reasoning": "上游需求增强", "signal_path": {"nodes": ["中际旭创", "光模块"], "edges": [], "hops": 1, "confidence": 0.8}}],
        }

    monkeypatch.setattr(builder_mod, "build_user_snapshot", fake_snapshot)
    monkeypatch.setattr(builder_mod, "_load_signal_detail", fake_signal)
    monkeypatch.setattr(builder_mod, "_load_readiness_context", AsyncMock(return_value={"overall_status": "fresh", "answer_boundary": "fresh"}))

    ctx = await AgentContextBuilder().build(user_id="lwm", thread_id="t1", question="分析信号", signal_id="SIG:abc")

    assert ctx.route == "relation_reasoning"
    assert ctx.signal_context is not None
    assert "800G 光模块规模量产" in ctx.prompt_context
    assert "<signal-context>" in ctx.prompt_context


@pytest.mark.asyncio
async def test_builder_relation_without_signal_warns(monkeypatch):
    async def fake_snapshot(user_id):
        return UserSnapshotDTO(user_id=user_id), []

    monkeypatch.setattr(builder_mod, "build_user_snapshot", fake_snapshot)
    monkeypatch.setattr(builder_mod, "_load_readiness_context", AsyncMock(return_value={"overall_status": "unknown", "answer_boundary": ""}))

    ctx = await AgentContextBuilder().build(user_id="lwm", thread_id="t1", question="光模块怎么看")

    assert "signal_context_missing" in ctx.warnings


@pytest.mark.asyncio
async def test_builder_signal_detail_failure_returns_prompt_context(monkeypatch):
    async def fake_snapshot(user_id):
        return UserSnapshotDTO(user_id=user_id), []

    async def broken_signal(signal_id):
        raise RuntimeError("signal detail unavailable")

    monkeypatch.setattr(builder_mod, "build_user_snapshot", fake_snapshot)
    monkeypatch.setattr(builder_mod, "_load_signal_detail", broken_signal)
    monkeypatch.setattr(builder_mod, "_load_readiness_context", AsyncMock(return_value={"overall_status": "unknown", "answer_boundary": ""}))

    ctx = await AgentContextBuilder().build(user_id="lwm", thread_id="t1", question="分析信号", signal_id="SIG:abc")

    assert "signal_context_read_failed" in ctx.warnings
    assert ctx.prompt_context
    assert ctx.prompt_context.startswith("<signal-context>")
