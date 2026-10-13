#!/usr/bin/env python3
"""Minimal MCP Streamable-HTTP client for the Qingshui read-only Data MCP.

Usage:
  mcp_call.py tools                       # list tools
  mcp_call.py call <tool> '<json-args>'   # call a tool
"""
import json
import sys
import urllib.request

BASE = "http://127.0.0.1:8100/mcp"
KEY = "sk-V-ZNidHIYdGK4rOXpPCsPw"


def post(payload, session_id=None):
    req = urllib.request.Request(BASE, data=json.dumps(payload).encode())
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json, text/event-stream")
    req.add_header("X-API-Key", KEY)
    if session_id:
        req.add_header("Mcp-Session-Id", session_id)
    resp = urllib.request.urlopen(req, timeout=120)
    sid = resp.headers.get("Mcp-Session-Id")
    body = resp.read().decode()
    ctype = resp.headers.get("Content-Type", "")
    if "text/event-stream" in ctype:
        # parse SSE: take last data: line that is JSON
        data_lines = [l[len("data:"):].strip() for l in body.splitlines() if l.startswith("data:")]
        msgs = [json.loads(d) for d in data_lines if d]
        return sid, msgs
    return sid, [json.loads(body)] if body.strip() else []


def main():
    # initialize
    init = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "dsh-research", "version": "1.0"},
        },
    }
    sid, msgs = post(init)
    # initialized notification
    post({"jsonrpc": "2.0", "method": "notifications/initialized"}, sid)

    cmd = sys.argv[1] if len(sys.argv) > 1 else "tools"
    rid = 10
    if cmd == "tools":
        rid += 1
        _, msgs = post({"jsonrpc": "2.0", "id": rid, "method": "tools/list"}, sid)
    elif cmd == "call":
        tool = sys.argv[2]
        args = json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}
        rid += 1
        _, msgs = post(
            {"jsonrpc": "2.0", "id": rid, "method": "tools/call",
             "params": {"name": tool, "arguments": args}},
            sid,
        )
    else:
        print("unknown cmd")
        return

    for m in msgs:
        if "error" in m:
            print("RPC ERROR:", json.dumps(m["error"], ensure_ascii=False))
        if "result" in m:
            print(json.dumps(m["result"], ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
