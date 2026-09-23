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
