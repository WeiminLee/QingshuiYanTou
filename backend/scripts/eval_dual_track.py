#!/usr/bin/env python3
"""Dual-track expected-gap eval runner (Approach C).

Cutover gates (must all hold before switching default traffic):
1. New-track pass rate ≥ old-track pass rate
2. Cases the old track already passes must not regress on the new track
3. Failed cases have locatable traces (tool/layer)
4. Embedding must not depend on a Mac tunnel
5. ≥ N (default 3) scheduled eval runs with no regression

Note (2026-10-10): `origin/main` currently returns HTTP 410 for
`/api/v1/agent/*` (LangChain retired). Live `--mode old-only` against that
tree will record `old_unavailable_410`. Prefer `--old-answer-file` /
`--new-answer-file` or a deployment that still exposes the legacy agent
until dual-track restore is decided.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import httpx

_BARE_MCP = re.compile(r"^mcp__[^_]+(?:_[^_]+)*__(.+)$")


def bare_tool_name(name: str) -> str:
    m = _BARE_MCP.match(name)
    if m:
        return m.group(1)
    idx = name.rfind("__")
    return name[idx + 2 :] if idx >= 0 else name


def _normalize_tools(tools_called: list[str] | None) -> set[str]:
    return {bare_tool_name(t) for t in (tools_called or []) if t}


def judge_case(
    case: dict[str, Any],
    *,
    answer: str,
    tools_called: list[str] | None,
) -> bool:
    """Return True when tool + phrase gates pass (conclusions[] optional)."""
    tools = _normalize_tools(tools_called)
    for required in case.get("must_call_tools") or []:
        if bare_tool_name(required) not in tools:
            return False
    any_of = case.get("must_call_any_of") or []
    if any_of and not any(bare_tool_name(t) in tools for t in any_of):
        return False
    phrases = case.get("answer_must_include_any") or []
    if phrases and not any(p in (answer or "") for p in phrases):
        return False
    return True


def judge_case_reasons(
    case: dict[str, Any],
    *,
    answer: str,
    tools_called: list[str] | None,
) -> list[str]:
    reasons: list[str] = []
    tools = _normalize_tools(tools_called)
    for required in case.get("must_call_tools") or []:
        if bare_tool_name(required) not in tools:
            reasons.append(f"missing required tool: {required}")
    any_of = case.get("must_call_any_of") or []
    if any_of and not any(bare_tool_name(t) in tools for t in any_of):
        reasons.append(f"missing any of tools: {any_of}")
    phrases = case.get("answer_must_include_any") or []
    if phrases and not any(p in (answer or "") for p in phrases):
        reasons.append(f"answer missing any of phrases: {phrases}")
    return reasons


def load_cases(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("cases file must be a JSON list")
    return data


def try_old_agent_stream_report(
    base: str,
    question: str,
    api_key: str,
    timeout: float = 600.0,
) -> dict[str, Any]:
    """Best-effort call to legacy stream/report. Handles 410 Gone on main."""
    url = f"{base.rstrip('/')}/api/v1/agent/stream/report"
    headers = {"X-API-Key": api_key, "Content-Type": "application/json"}
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(url, headers=headers, json={"question": question})
    except httpx.HTTPError as exc:
        return {"ok": False, "error": str(exc), "answer": "", "tools": []}

    if resp.status_code == 410:
        return {
            "ok": False,
            "error": "old_unavailable_410",
            "answer": "",
            "tools": [],
            "detail": resp.text[:500],
        }
    if resp.status_code >= 400:
        return {
            "ok": False,
            "error": f"http_{resp.status_code}",
            "answer": "",
            "tools": [],
            "detail": resp.text[:500],
        }
    # Streaming responses vary; try JSON then plain text.
    answer = ""
    tools: list[str] = []
    try:
        body = resp.json()
        if isinstance(body, dict):
            answer = str(body.get("report_content") or body.get("answer") or body.get("content") or "")
            raw_tools = body.get("tools_called") or body.get("tools") or []
            if isinstance(raw_tools, list):
                tools = [str(t) for t in raw_tools]
    except Exception:  # noqa: BLE001
        answer = resp.text
    return {"ok": True, "answer": answer, "tools": tools, "error": None}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--cases",
        type=Path,
        default=Path("eval/expected_gap_cases_v1.json"),
    )
    parser.add_argument("--old-base", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--mode",
        choices=("old-only", "both", "judge-files"),
        default="judge-files",
        help="judge-files: score provided answer files; old-only/both attempt live HTTP",
    )
    parser.add_argument("--api-key", default="", help="or env KNOWLEDGE_API_KEY / API_KEY")
    parser.add_argument("--old-answer-file", type=Path, help="JSON map case_id -> {answer, tools}")
    parser.add_argument("--new-answer-file", type=Path, help="JSON map case_id -> {answer, tools}")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("eval/out/dual_track_report.json"),
    )
    args = parser.parse_args(argv)

    import os

    api_key = (
        args.api_key
        or os.environ.get("KNOWLEDGE_API_KEY", "")
        or os.environ.get("API_KEY", "")
    ).strip()

    cases = load_cases(args.cases)
    old_map: dict[str, Any] = {}
    new_map: dict[str, Any] = {}
    if args.old_answer_file and args.old_answer_file.exists():
        old_map = json.loads(args.old_answer_file.read_text(encoding="utf-8"))
    if args.new_answer_file and args.new_answer_file.exists():
        new_map = json.loads(args.new_answer_file.read_text(encoding="utf-8"))

    report: list[dict[str, Any]] = []
    for case in cases:
        cid = case["case_id"]
        old_answer = ""
        old_tools: list[str] = []
        new_answer = ""
        new_tools: list[str] = []
        old_err = None
        new_err = None

        if cid in old_map:
            old_answer = str(old_map[cid].get("answer") or "")
            old_tools = list(old_map[cid].get("tools") or [])
        elif args.mode in ("old-only", "both"):
            if not api_key:
                old_err = "missing_api_key"
            else:
                live = try_old_agent_stream_report(args.old_base, case["question"], api_key)
                if live.get("ok"):
                    old_answer = live.get("answer") or ""
                    old_tools = list(live.get("tools") or [])
                else:
                    old_err = live.get("error")

        if cid in new_map:
            new_answer = str(new_map[cid].get("answer") or "")
            new_tools = list(new_map[cid].get("tools") or [])
        elif args.mode == "both":
            new_err = "new_track_not_wired_use_answer_file"

        old_pass = None
        new_pass = None
        reasons: list[str] = []
        if args.mode in ("old-only", "both", "judge-files") and (old_answer or old_tools or old_err):
            if old_err:
                old_pass = False
                reasons.append(f"old:{old_err}")
            else:
                old_pass = judge_case(case, answer=old_answer, tools_called=old_tools)
                reasons.extend(f"old:{r}" for r in judge_case_reasons(case, answer=old_answer, tools_called=old_tools))
        if args.mode in ("both", "judge-files") and (new_answer or new_tools or new_err or args.new_answer_file):
            if new_err and not new_answer:
                new_pass = False
                reasons.append(f"new:{new_err}")
            elif new_answer or new_tools:
                new_pass = judge_case(case, answer=new_answer, tools_called=new_tools)
                reasons.extend(f"new:{r}" for r in judge_case_reasons(case, answer=new_answer, tools_called=new_tools))

        report.append(
            {
                "case_id": cid,
                "old_pass": old_pass,
                "new_pass": new_pass,
                "old_tools": old_tools,
                "new_tools": new_tools,
                "reasons": reasons,
            }
        )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"out": str(args.out), "cases": len(report), "report": report}, ensure_ascii=False, indent=2))
    # Exit 0 even if fails — report is the artifact; CI can parse.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
