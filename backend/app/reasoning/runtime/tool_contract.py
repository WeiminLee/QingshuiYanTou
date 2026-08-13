"""Tool-result metadata contract for trace and ledger records."""

from __future__ import annotations

from typing import Any

_TOOL_DATA_SOURCES = {
    "get_kline": "kline",
    "get_announcement": "announcement",
    "get_irm": "irm",
    "get_research_report": "research_report",
    "tavily_search": "news",
}


def build_tool_result_contract(
    *,
    tool_name: str,
    tool_call_id: str,
    preview: str,
    success: bool,
    source_layer: str,
    readiness_binding: dict[str, Any],
    original_len: int,
    duration_ms: float,
) -> dict[str, Any]:
    data_source = _TOOL_DATA_SOURCES.get(tool_name, "")
    source_readiness = _source_readiness(readiness_binding, data_source)
    data_status = source_readiness.get("status") or "unknown"
    return {
        "tool_call_id": tool_call_id,
        "tool": tool_name,
        "source_layer": source_layer,
        "data_source": data_source,
        "data_status": data_status,
        "latest_data_date": source_readiness.get("latest_data_date"),
        "stale": data_status == "stale",
        "time_sensitive_allowed": bool(readiness_binding.get("is_time_sensitive_allowed", False)),
        "success": success,
        "error_type": "" if success else "tool_failure",
        "duration_ms": duration_ms,
        "original_len": original_len,
        "preview": preview,
    }


def _source_readiness(readiness_binding: dict[str, Any], source: str) -> dict[str, Any]:
    if not source:
        return {}
    for item in readiness_binding.get("sources", []):
        if isinstance(item, dict) and item.get("source") == source:
            return item
    return {}
