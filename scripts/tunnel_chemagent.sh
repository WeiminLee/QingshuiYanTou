#!/usr/bin/env bash
# Mac → chemagent 访问通道（第一版本地 Agent 的用户终端通道，AGENTS.md 条目 2 豁免）
# 用法: bash scripts/tunnel_chemagent.sh        # 前台运行（Ctrl-C 断开）
# 转发: 本机 8100 → chemagent Data MCP；本机 8001 → chemagent Knowledge API
set -euo pipefail
exec ssh -N \
  -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -o ExitOnForwardFailure=yes \
  -L 8100:127.0.0.1:8100 \
  -L 8001:127.0.0.1:8001 \
  lwm-server-chemagent
