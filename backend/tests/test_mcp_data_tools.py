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


def test_p05_tool_names_locked():
    assert set(TOOL_NAMES) >= {
        "get_announcement",
        "get_irm",
        "find_events",
        "get_event_detail",
        "scan_dimension",
        "backlinks",
        "get_top_concepts",
        "get_concept_stocks",
        "get_stock_concepts",
        "history_findings",
        "search_findings",
        "watermark",
    }
    # 台账写面只走 Knowledge HTTP（插件直连），MCP 第一期不注册任何写工具
    assert "write_observation" in WRITE_TOOL_NAMES
    assert "write_finding" in WRITE_TOOL_NAMES


@pytest.mark.asyncio
async def test_ledger_read_tools_post_to_knowledge_http(monkeypatch):
    from app.mcp_data import tools_readonly as mod

    calls: list[tuple[str, dict]] = []

    async def fake_post(path: str, body: dict, **kwargs):
        calls.append((path, body))
        return {"ok": True}

    monkeypatch.setattr(mod, "knowledge_post", fake_post)
    assert (await mod.history_findings(subject="中晶科技", dimension="产线进展"))["ok"] is True
    assert (await mod.search_findings(kind="progression"))["ok"] is True
    assert (await mod.watermark("003026.SZ", "产线进展"))["ok"] is True
    assert calls[0][0] == "/api/v1/knowledge/ledger/history"
    assert calls[1][0] == "/api/v1/knowledge/ledger/search"
    assert calls[2][0] == "/api/v1/knowledge/ledger/watermark"


@pytest.mark.asyncio
async def test_find_events_passes_body(monkeypatch):
    from app.mcp_data import tools_readonly as mod

    captured: dict = {}

    async def fake_post(path: str, body: dict, **kwargs):
        captured["path"] = path
        captured["body"] = body
        return {"items": [], "count": 0}

    monkeypatch.setattr(mod, "knowledge_post", fake_post)
    out = await mod.find_events(query="光模块 涨价", tags=["CPO"], top_n=5)
    assert out["count"] == 0
    assert captured["path"] == "/api/v1/knowledge/sources/events"
    assert captured["body"]["tags"] == ["CPO"]
    assert captured["body"]["top_n"] == 5
