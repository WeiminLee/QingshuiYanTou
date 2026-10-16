#!/usr/bin/env python3
"""Collect one golden-eval round: per case, attribute the dsh headless session
born inside that case's marker time window, extract called tool names from
`session.jsonl.zstd`, and assemble the `{case_id: {answer, tools}}` map that
`eval_dual_track.py --mode harness-files` consumes.

  Session attribution (deterministic):
  - Raw dir holds one `<case_id>.marker` per case, touched right before its headless run.
  - Marker files sorted by mtime define consecutive windows; a session belongs
    to the case whose window contains the session's *birth* time (st_birthtime,
    falling back to st_mtime). A re-run case's marker becomes the newest, so
    its window extends to +inf — reruns stay correctly attributed.
  - Multiple sessions in one window: the **earliest-born** wins. The window
    owner's marker is touched immediately before its own run, so its session
    is by construction born first in the window; any later-born session there
    is an orphan from a failed/superseded run of another case.

Usage:
  eval_collect_harness_round.py --cases eval/expected_gap_cases_v2.json \
    --raw-dir eval/out/raw/<tag> --dsh-home ~/.dsh-qingshui \
    --out eval/out/harness_answers_<tag>.json

Raw dir layout (produced by scripts/run-golden-eval.sh):
  <case_id>.answer.txt    headless stdout (final assistant message)
  <case_id>.marker        touched right before the headless run
  <case_id>.exit          process exit code
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def _birthtime(path: Path) -> float:
    st = path.stat()
    return getattr(st, "st_birthtime", None) or st.st_mtime


def session_files(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    return list(root.glob("*/session-*/session.jsonl.zstd"))


def extract_tools(session_file: Path) -> list[str]:
    out = subprocess.run(
        ["zstd", "-dc", str(session_file)], capture_output=True, check=True
    ).stdout.decode("utf-8", errors="replace")
    tools: list[str] = []
    seen: set[str] = set()
    for line in out.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "tool/call":
            name = (event.get("data") or {}).get("name")
            if name and name not in seen:
                seen.add(name)
                tools.append(name)
    return tools


def extract_request_tool_snapshots(session_file: Path) -> tuple[dict, dict] | None:
    """首/末次 LLM 请求的工具面快照（request/header 事件）。

    B3 背景：MCP 21 工具延迟挂载——首步请求仅 core 工具（如 35 个、0 个 mcp__），
    工具往返后才挂载 mcp__ 前缀工具（56 个、21 个 mcp__）。快照用于诊断
    「agent 断言某工具未暴露」时首步快照是否真实成立。
    """
    out = subprocess.run(
        ["zstd", "-dc", str(session_file)], capture_output=True, check=True
    ).stdout.decode("utf-8", errors="replace")
    snapshots: list[dict] = []
    for line in out.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") != "request/header":
            continue
        tools = (event.get("data") or {}).get("header", {}).get("tools") or []
        names = [t.get("name") if isinstance(t, dict) else t for t in tools]
        mcp_count = sum(
            1 for n in names if isinstance(n, str) and n.startswith("mcp__")
        )
        snapshots.append({"count": len(names), "mcp_count": mcp_count})
    if not snapshots:
        return None
    return snapshots[0], snapshots[-1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", type=Path, required=True)
    ap.add_argument("--raw-dir", type=Path, required=True)
    ap.add_argument("--dsh-home", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    sessions_root = args.dsh_home / "sessions"
    sessions = [(p, _birthtime(p)) for p in session_files(sessions_root)]

    answers: dict[str, dict] = {}
    problems: list[str] = []

    # marker mtime ordering defines attribution windows; newest marker ⇒ open-ended window
    marker_times: dict[str, float] = {}
    for case in cases:
        cid = case["case_id"]
        marker = args.raw_dir / f"{cid}.marker"
        marker_times[cid] = marker.stat().st_mtime if marker.exists() else float("inf")
    ordered = sorted(marker_times.items(), key=lambda kv: kv[1])

    for case in cases:
        cid = case["case_id"]
        answer_path = args.raw_dir / f"{cid}.answer.txt"
        answer = answer_path.read_text(encoding="utf-8", errors="replace").strip() if answer_path.exists() else ""

        tools: list[str] = []
        snapshots: tuple[dict, dict] | None = None
        start = marker_times.get(cid, float("inf"))
        if start == float("inf"):
            problems.append(f"{cid}: marker missing; tools=[]")
        else:
            pos = next(i for i, (c, _) in enumerate(ordered) if c == cid)
            end = ordered[pos + 1][1] if pos + 1 < len(ordered) else float("inf")
            in_window = [p for p, born in sessions if start < born <= end]
            if in_window:
                session = min(in_window, key=_birthtime)
                tools = extract_tools(session)
                snapshots = extract_request_tool_snapshots(session)
                if len(in_window) > 1:
                    problems.append(
                        f"{cid}: {len(in_window)} sessions in window, used earliest-born {session.parent.name} (later ones are superseded orphans)"
                    )
            else:
                problems.append(f"{cid}: no session born in window; tools=[]")

        answers[cid] = {"answer": answer, "tools": tools}
        if snapshots:
            answers[cid]["tools_at_first_request"] = snapshots[0]
            answers[cid]["tools_at_last_request"] = snapshots[1]
        exit_note = ""
        exit_file = args.raw_dir / f"{cid}.exit"
        if exit_file.exists() and exit_file.read_text().strip() not in ("0", ""):
            exit_note = f" exit={exit_file.read_text().strip()}"
        print(f"· {cid}: answer {len(answer)} chars, tools {len(tools)}{exit_note}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(answers, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✓ answers -> {args.out}")
    for p in problems:
        print(f"  WARN {p}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
