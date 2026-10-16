"""Guard against degenerate terminations in one golden-eval round.

A case is *degenerate* when its attributed headless session ended its turn as
``completed`` while the final assistant message carries neither a ``text`` nor
a ``tool-call`` block. That is the shape a truncated provider completion takes
when the gateway drops the action blocks but still reports ``stopReason:
"stop"``: the loop sees no tool call, treats the turn as finished, and the
captured answer is a mid-investigation fragment. Observed in the `review_r1`
round on `gap-wafer-margin-001` (session ``38e06af1``: step 7 content
``['reasoning']``, finish reported ``stop``, 286 output tokens, reasoning text
cut mid-word at ``"...metric_tre"``, zero retries).

Session attribution reuses `eval_collect_harness_round` so the guard and the
collector always agree on which session belongs to which case.

**Scope and known limit.** The rule deliberately keys on the *high-precision*
signal — a completed turn whose final assistant message carries no ``text`` and
no ``tool-call`` block. Across the 2026-10-15 ``review_r1`` round it flags
exactly the one degenerate case and none of the ten healthy ones, and re-running
the flagged case recovered it (267 B fragment → 9,977 B report, case PASS).
A truncated completion that still carries a short ``text`` prefix alongside its
reasoning would *not* be caught; the observed truncation produced reasoning
only, so the extra recall is not worth the false-positive cost — a needless
re-run burns 10–37 minutes of rate-limited gateway time. Worth revisiting only
if such a shape is ever observed in the wild.

Usage:
    python backend/scripts/eval_degenerate_guard.py \
        --raw-dir backend/eval/out/raw/review_r1 \
        --dsh-home ~/.dsh-qingshui [--json]

Exit codes: 0 = no degenerate case, 1 = at least one degenerate case,
2 = usage/attribution problem that prevents a verdict.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from eval_collect_harness_round import _birthtime, session_files  # noqa: E402

ACTIONABLE_BLOCKS = ("text", "tool-call")


def read_events(session_file: Path) -> list[dict]:
    """Decompress and parse a session log into its raw JSONL events."""
    raw = subprocess.run(
        ["zstd", "-dc", str(session_file)],
        capture_output=True,
        check=True,
    ).stdout.decode("utf-8", "replace")
    events = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def classify(events: list[dict]) -> tuple[bool, str]:
    """Return ``(degenerate, reason)`` for one session's events."""
    turn_end = None
    last_assistant = None
    for event in events:
        kind = event.get("type")
        if kind == "turn/end":
            turn_end = (event.get("data") or {}).get("reason", {}).get("kind")
        elif kind == "assistant/message":
            last_assistant = event.get("data") or {}

    if turn_end is None:
        return False, "turn still open (no turn/end) — not counted"
    if turn_end != "completed":
        return False, f"turn ended as {turn_end!r}, not a completed stop"
    if last_assistant is None:
        return True, "turn completed with no assistant message at all"

    content = ((last_assistant.get("message") or {}).get("content")) or []
    block_types = [block.get("type") for block in content]
    if any(block_type in ACTIONABLE_BLOCKS for block_type in block_types):
        return False, f"final assistant message has actionable blocks {block_types}"

    step = last_assistant.get("step")
    return True, (
        f"turn completed at step {step} with no text and no tool call "
        f"(blocks={block_types}) — truncated completion reported as stop"
    )


def attribute(raw_dir: Path, dsh_home: Path) -> tuple[dict[str, Path], list[str]]:
    """Map case id -> its session file, using the collector's window rules."""
    sessions_root = dsh_home / "sessions"
    sessions = [(path, _birthtime(path)) for path in session_files(sessions_root)]

    marker_times: dict[str, float] = {}
    for marker in raw_dir.glob("*.marker"):
        marker_times[marker.stem] = marker.stat().st_mtime
    ordered = sorted(marker_times.items(), key=lambda item: item[1])

    attributed: dict[str, Path] = {}
    problems: list[str] = []
    for index, (case_id, start) in enumerate(ordered):
        end = ordered[index + 1][1] if index + 1 < len(ordered) else float("inf")
        in_window = [path for path, born in sessions if start < born <= end]
        if in_window:
            attributed[case_id] = min(in_window, key=_birthtime)
        else:
            problems.append(f"{case_id}: no session born in its marker window")
    return attributed, problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", required=True, type=Path)
    parser.add_argument("--dsh-home", required=True, type=Path)
    parser.add_argument("--json", action="store_true", help="emit a JSON report")
    parser.add_argument("--ids", action="store_true",
                        help="print only degenerate case ids, one per line (for shell callers)")
    args = parser.parse_args()

    raw_dir = args.raw_dir.expanduser().resolve()
    dsh_home = args.dsh_home.expanduser().resolve()
    if not raw_dir.is_dir():
        print(f"raw dir not found: {raw_dir}", file=sys.stderr)
        return 2

    attributed, problems = attribute(raw_dir, dsh_home)
    if not attributed:
        print(f"no case attributed under {raw_dir}", file=sys.stderr)
        return 2

    degenerate: list[dict] = []
    for case_id in sorted(attributed):
        session_file = attributed[case_id]
        is_degenerate, reason = classify(read_events(session_file))
        if is_degenerate:
            degenerate.append({
                "case_id": case_id,
                "session": session_file.parent.name,
                "reason": reason,
            })

    if args.ids:
        for item in degenerate:
            print(item["case_id"])
    elif args.json:
        print(json.dumps(
            {"degenerate": degenerate, "problems": problems},
            ensure_ascii=False,
            indent=2,
        ))
    else:
        if degenerate:
            print(f"degenerate cases: {len(degenerate)}/{len(attributed)}")
            for item in degenerate:
                print(f"  {item['case_id']}  ({item['session']})  {item['reason']}")
        else:
            print(f"no degenerate case ({len(attributed)} attributed)")
        for problem in problems:
            print(f"  note: {problem}", file=sys.stderr)

    return 1 if degenerate else 0


if __name__ == "__main__":
    raise SystemExit(main())
