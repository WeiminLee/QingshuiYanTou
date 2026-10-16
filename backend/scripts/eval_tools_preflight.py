#!/usr/bin/env python3
"""B3 前置检查：金标轮开跑前核对「案例必调工具 ⊆ MCP 工具面 ∪ 插件本地工具面」。

背景：MCP 21 只读工具在 dsh 属延迟挂载（首步请求仅 35 个裸名工具、无 mcp__ 前缀，
工具往返后才挂载 21 个 mcp__qingshui_data__*——见 request/header 快照 35→56）。
另有 11 个**插件本地工具**（plugins/qingshui/src/tools.ts 注册、走 HTTP 端点，如
metric_trend / rollup_metric / propagate_along / related_nodes / write_finding 等），
agent 从首步 35 裸名面即可见，不在 MCP 21 内（/health 与 tools_readonly.py 均无）。

本脚本以**双面合并**为可用工具集：`:8100/health` 的 21 个 MCP 工具 ∪ tools.ts 的
插件本地工具；与 expected_gap_cases_v2.json 全部案的 must_call_tools / must_call_any_of
求交（裸名后缀归一：mcp__qingshui_data__X ↔ X）；缺失项仅 **warning（非致命）**。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

HEALTH_URL = "http://127.0.0.1:8100/health"
MCP_PREFIX = "mcp__qingshui_data__"
PLUGIN_TOOLS_FILE = (
    Path(__file__).resolve().parents[2] / "plugins" / "qingshui" / "src" / "tools.ts"
)
# 兜底常量：tools.ts 若读取失败时的插件本地工具清单（与 tools.ts 保持一致；
# metric_trend 等 4 工具为插件本地工具，非 MCP 缺口，见 docstring）。
PLUGIN_TOOLS_FALLBACK = {
    "compare_metric",
    "metric_trend",
    "rollup_metric",
    "fetch_evidence",
    "semantic_search",
    "related_nodes",
    "propagate_along",
    "get_kline",
    "get_stock_profile",
    "write_observation",
    "write_finding",
}


def normalize(name: str) -> str:
    """裸名 = MCP 全名的后缀：mcp__qingshui_data__X → X。"""
    return name[len(MCP_PREFIX):] if name.startswith(MCP_PREFIX) else name


def fetch_mcp_tools() -> set[str]:
    with urllib.request.urlopen(HEALTH_URL, timeout=8) as resp:
        payload = json.load(resp)
    return {normalize(t) for t in payload.get("tools", [])}


def fetch_plugin_tools() -> set[str]:
    """插件本地工具名：解析 plugins/qingshui/src/tools.ts 的 name: '...' 注册。"""
    try:
        src = PLUGIN_TOOLS_FILE.read_text(encoding="utf-8")
    except OSError:
        print(f"⚠ [preflight] 读取 {PLUGIN_TOOLS_FILE} 失败，使用兜底常量", file=sys.stderr)
        return set(PLUGIN_TOOLS_FALLBACK)
    names = set(re.findall(r"name:\s*'([^']+)'", src))
    if not names:
        print("⚠ [preflight] tools.ts 未解析到 name 注册，使用兜底常量", file=sys.stderr)
        return set(PLUGIN_TOOLS_FALLBACK)
    return names


def collect_required(cases: list[dict]) -> set[str]:
    req: set[str] = set()
    for case in cases:
        for name in case.get("must_call_tools") or []:
            req.add(normalize(name))
        for name in case.get("must_call_any_of") or []:
            req.add(normalize(name))
    return req


def main() -> int:
    ap = argparse.ArgumentParser(description="金标轮前置：必调工具缺口告警（非致命，双面口径）")
    ap.add_argument("--cases", type=argparse.FileType("r", encoding="utf-8"), required=True)
    args = ap.parse_args()
    cases = json.load(args.cases)

    try:
        mcp_tools = fetch_mcp_tools()
    except Exception as exc:  # noqa: BLE001
        print(f"⚠ [preflight] MCP 工具面获取失败（{exc}）——跳过缺口告警", file=sys.stderr)
        return 0
    plugin_tools = fetch_plugin_tools()
    available = mcp_tools | plugin_tools

    missing = sorted(collect_required(cases) - available)
    if missing:
        print(f"⚠ [preflight] 必调工具缺失 {len(missing)} 项（MCP{len(mcp_tools)} ∪ 插件{len(plugin_tools)} 面中均未找到）:")
        for name in missing:
            users = [
                case["case_id"]
                for case in cases
                if any(normalize(t) == name for t in (case.get("must_call_tools") or []))
                or any(normalize(t) == name for t in (case.get("must_call_any_of") or []))
            ]
            print(f"     - {name} ← 要求于 {sorted(users)}")
    else:
        print(
            f"✓ [preflight] 工具面齐全：MCP {len(mcp_tools)} ∪ 插件本地 {len(plugin_tools)}，"
            f"全部必调工具无缺口"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
