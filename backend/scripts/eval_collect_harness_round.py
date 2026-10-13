#!/usr/bin/env python3
"""Collect one golden-eval round: per case, attribute the dsh headless session
created after the case's marker file, extract called tool names from
`session.jsonl.zstd`, and assemble the `{case_id: {answer, tools}}` map that
`eval_dual_track.py --mode harness-files` consumes.

Usage:
  eval_collect_harness_round.py --cases eval/expected_gap_cases_v1.json \
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


def session_files_since(dsh_home: Path, marker: Path) -> list[Path]:
    root = dsh_home / "sessions"
    if not root.is_dir():
        return []
    since = marker.stat().st_mtime
    hits = [p for p in root.glob("*/session-*/session.jsonl.zstd") if p.stat().st_mtime >= since]
    return sorted(hits, key=lambda p: p.stat().st_mtime)


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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", type=Path, required=True)
    ap.add_argument("--raw-dir", type=Path, required=True)
    ap.add_argument("--dsh-home", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    answers: dict[str, dict] = {}
    problems: list[str] = []
    for case in cases:
        cid = case["case_id"]
        marker = args.raw_dir / f"{cid}.marker"
        answer_path = args.raw_dir / f"{cid}.answer.txt"
        answer = answer_path.read_text(encoding="utf-8", errors="replace").strip() if answer_path.exists() else ""
        tools: list[str] = []
        sessions = session_files_since(args.dsh_home, marker) if marker.exists() else []
        if sessions:
            tools = extract_tools(sessions[-1])
            if len(sessions) > 1:
                problems.append(f"{cid}: {len(sessions)} sessions after marker, used newest {sessions[-1].parent.name}")
        else:
            problems.append(f"{cid}: no session found after marker; tools=[]")
        answers[cid] = {"answer": answer, "tools": tools}
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
