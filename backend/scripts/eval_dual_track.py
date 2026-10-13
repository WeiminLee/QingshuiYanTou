#!/usr/bin/env python3
"""Expected-gap eval for Data MCP + DeepSeek harness (sole agent runtime).

Historical name `eval_dual_track` kept for path stability; there is **no**
old LangChain `/api/v1/agent/*` track anymore (removed 2026-10-10).

Acceptance gates (harness-only):
1. Pass rate on `expected_gap_cases_v1.json` meets owner bar
2. Failed cases have locatable tool/trace reasons
3. Embedding must not depend on a Mac tunnel
4. ≥ N (default 3) scheduled eval runs with no regression

Modes:
  --mode harness-files   score answers from --answer-file (default)
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

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
    parser.add_argument(
        "--mode",
        choices=("harness-files",),
        default="harness-files",
        help="Only harness scoring is supported (LangChain agent HTTP removed)",
    )
    parser.add_argument(
        "--answer-file",
        type=Path,
        help="JSON map case_id -> {answer, tools} from dsh/harness run",
    )
    # Back-compat aliases (ignored for old track; --new-answer-file == --answer-file)
    parser.add_argument("--new-answer-file", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--old-answer-file", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--old-base", default="", help=argparse.SUPPRESS)
    parser.add_argument("--api-key", default="", help=argparse.SUPPRESS)
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("eval/out/expected_gap_report.json"),
    )
    args = parser.parse_args(argv)

    if args.old_base or args.old_answer_file or (args.mode if False else False):
        pass
    answer_path = args.answer_file or args.new_answer_file
    if args.old_answer_file and not answer_path:
        print(
            "warning: --old-answer-file ignored (LangChain /api/v1/agent removed); "
            "use --answer-file for harness outputs",
            flush=True,
        )
    if args.old_base:
        print(
            "warning: --old-base ignored (no /api/v1/agent/* runtime)",
            flush=True,
        )

    cases = load_cases(args.cases)
    answers: dict[str, Any] = {}
    if answer_path and answer_path.exists():
        answers = json.loads(answer_path.read_text(encoding="utf-8"))

    report: list[dict[str, Any]] = []
    for case in cases:
        cid = case["case_id"]
        entry = answers.get(cid) or {}
        answer = str(entry.get("answer") or "")
        tools = list(entry.get("tools") or [])
        passed = None
        reasons: list[str] = []
        if answer or tools:
            passed = judge_case(case, answer=answer, tools_called=tools)
            reasons = judge_case_reasons(case, answer=answer, tools_called=tools)
        elif answer_path:
            passed = False
            reasons = ["missing answer for case in --answer-file"]
        report.append(
            {
                "case_id": cid,
                "pass": passed,
                "tools": tools,
                "reasons": reasons,
            }
        )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    n_pass = sum(1 for r in report if r["pass"] is True)
    n_fail = sum(1 for r in report if r["pass"] is False)
    n_skip = sum(1 for r in report if r["pass"] is None)
    summary = {
        "out": str(args.out),
        "runtime": "dsh+mcp_data",
        "cases": len(report),
        "pass": n_pass,
        "fail": n_fail,
        "unscored": n_skip,
        "report": report,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
