from __future__ import annotations

import pytest

from app.mcp_data.truncation import truncate_evidence_text
from app.mcp_data.tools_readonly import TOOL_NAMES, WRITE_TOOL_NAMES


def test_p0_tool_names_locked():
    assert set(TOOL_NAMES) >= {
        "fetch_evidence",
        "semantic_search",
        "compare_metric",
        "pull_history",
        "lookup_players",
        "lookup_products",
        "get_kline",
        "get_stock_profile",
        "data_readiness",
    }


def test_evidence_truncation_8k():
    text = "x" * 9000
    out = truncate_evidence_text(text)
    assert len(out) < 9000
    assert "截断" in out or "truncated" in out.lower() or len(out) <= 8000 + 80


def test_no_write_tools_registered():
    assert set(TOOL_NAMES).isdisjoint(WRITE_TOOL_NAMES)
    for name in TOOL_NAMES:
        assert "claim" not in name
        assert "upsert" not in name
        assert not name.startswith("write_")


@pytest.mark.asyncio
async def test_fetch_evidence_applies_truncation(monkeypatch):
    from app.mcp_data import tools_readonly as mod

    long_text = "y" * 9000

    async def fake_get(path: str, **kwargs):
        assert path.endswith("/EV:1")
        return {"evidence_id": "EV:1", "text_excerpt": long_text, "source_type": "announcement"}

    monkeypatch.setattr(mod, "knowledge_get", fake_get)
    out = await mod.fetch_evidence("EV:1")
    assert out["evidence_id"] == "EV:1"
    assert len(out["text_excerpt"]) < 9000
    assert "截断" in out["text_excerpt"]


def test_fastmcp_registers_p0_tools():
    from app.mcp_data.server import build_mcp
    from app.mcp_data.tools_readonly import TOOL_NAMES

    mcp = build_mcp()
    names = {t.name for t in mcp._tool_manager.list_tools()}
    assert set(TOOL_NAMES) <= names
    assert names.isdisjoint({"claim_job", "upsert_evidence", "write_todos"})
