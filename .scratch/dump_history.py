#!/usr/bin/env python3
"""Dump pull_history excerpts for subjects x dimension to files for reading."""
import json
import subprocess
import sys

SCRIPT = "/Users/lwm/code/QingshuiYanTou.worktrees/agent-mcp-dsh/.scratch/mcp_call.py"

subjects = sys.argv[1].split(",")
dimension = sys.argv[2] if len(sys.argv) > 2 else "毛利率"

for s in subjects:
    out = subprocess.run(
        ["python3", SCRIPT, "call", "pull_history",
         json.dumps({"subject": s, "dimension": dimension, "limit": 15})],
        capture_output=True, text=True,
    )
    try:
        d = json.loads(out.stdout)
        r = json.loads(d["structuredContent"]["result"])
    except Exception as e:
        print(f"=== {s}: parse fail {e}")
        print(out.stdout[:500])
        continue
    print(f"########## {s} × {dimension}  (count={r.get('count')}) ##########")
    for it in r.get("items", []):
        print(f"\n----- EV {it['evidence_id'][3:23]}… | {it['published_at'][:10]} | {it['source_name']} -----")
        print(it["text_excerpt"][:2300])
    print()
