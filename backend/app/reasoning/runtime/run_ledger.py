"""Run-level evidence binding helpers for agent trace metadata."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

_STATUS_POLICY = {
    "fresh": ("normal", True),
    "degraded": ("degraded", True),
    "unavailable": ("blocked", False),
}


@dataclass(frozen=True)
class RunLedgerRecord:
    run_id: str
    thread_id: str
    question: str
    report_id: str
    readiness_binding: dict[str, Any]
    trace_summary: dict[str, Any]
    evidence_refs: list[dict[str, Any]]
    tool_audit: list[dict[str, Any]]
    graph_refs: list[dict[str, Any]]
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class JsonlRunLedgerStore:
    """Append-only JSONL store for run-level replay evidence."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    @classmethod
    def default(cls) -> JsonlRunLedgerStore:
        path = os.environ.get("QINGSHUI_RUN_LEDGER_PATH") or "logs/agent_run_ledger.jsonl"
        return cls(path)

    def append(self, record: RunLedgerRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")


def build_readiness_binding(freshness_context: str | None) -> dict[str, Any]:
    """Parse the injected <data_readiness> prompt block into durable metadata."""
    text = freshness_context or ""
    binding: dict[str, Any] = {
        "as_of": "",
        "overall_status": "unknown",
        "answer_boundary": "",
        "readiness_error": "",
        "conclusion_policy": "unknown",
        "is_time_sensitive_allowed": False,
        "sources": [],
        "stale_sources": [],
        "failed_sources": [],
        "missing_sources": [],
    }
    if not text.strip():
        return binding

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line in {"<data_readiness>", "</data_readiness>", "rules:", "sources:"}:
            continue
        if line.startswith("- "):
            source = _parse_source_line(line)
            if source:
                binding["sources"].append(source)
            continue
        if "=" in line:
            key, value = line.split("=", 1)
            key = key.strip()
            if key in {"as_of", "overall_status", "answer_boundary", "readiness_error"}:
                binding[key] = value.strip()

    overall = str(binding.get("overall_status") or "unknown")
    policy, allowed = _STATUS_POLICY.get(overall, ("unknown", False))
    binding["conclusion_policy"] = policy
    binding["is_time_sensitive_allowed"] = allowed

    for source in binding["sources"]:
        status = source.get("status")
        name = source.get("source")
        if not name:
            continue
        if status == "stale":
            binding["stale_sources"].append(name)
        elif status == "failed":
            binding["failed_sources"].append(name)
        elif status == "missing":
            binding["missing_sources"].append(name)

    return binding


def build_readiness_evidence_ref(binding: dict[str, Any]) -> dict[str, Any] | None:
    """Convert readiness metadata into a first-class evidence reference."""
    status = str(binding.get("overall_status") or "unknown")
    if status == "unknown" and not binding.get("readiness_error"):
        return None
    content = binding.get("answer_boundary") or _default_readiness_content(status)
    return {
        "id": "DATA_READINESS",
        "source_type": "readiness",
        "source_name": "数据新鲜度与同步状态",
        "content": content,
        "confidence": "TIER1_SYSTEM",
        "metadata": {
            "as_of": binding.get("as_of", ""),
            "overall_status": status,
            "conclusion_policy": binding.get("conclusion_policy", "unknown"),
            "is_time_sensitive_allowed": binding.get("is_time_sensitive_allowed", False),
            "stale_sources": list(binding.get("stale_sources", [])),
            "failed_sources": list(binding.get("failed_sources", [])),
            "missing_sources": list(binding.get("missing_sources", [])),
            "readiness_error": binding.get("readiness_error", ""),
        },
    }


def _parse_source_line(line: str) -> dict[str, Any] | None:
    body = line[2:].strip()
    if ":" not in body:
        return None
    source, rest = body.split(":", 1)
    parts = [part.strip() for part in rest.split(";") if part.strip()]
    if not parts:
        return None
    item: dict[str, Any] = {
        "source": source.strip(),
        "status": parts[0].strip(),
    }
    for part in parts[1:]:
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        item[key.strip()] = _coerce_scalar(value.strip())
    return item


def _coerce_scalar(value: str) -> Any:
    if value == "None":
        return None
    if value.isdigit():
        return int(value)
    return value


def _default_readiness_content(status: str) -> str:
    if status == "fresh":
        return "关键数据源处于日级可靠窗口内。"
    if status == "degraded":
        return "关键数据源存在滞后，结论需要声明数据截至日期并降低强度。"
    if status == "unavailable":
        return "关键数据缺失或同步失败，不得输出强时效结论。"
    return "数据新鲜度状态未知，结论需要保守处理。"
