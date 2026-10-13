#!/usr/bin/env bash
# 清水投研 · 本地 Agent（dsh web）一键启动
#
# 与 MatDiscovery 的 dsh 完全隔离：本脚本强制独立 DSH_HOME（~/.dsh-qingshui），
# 会话/配置/凭据互不可见。覆盖：DSH_HOME=/path bash scripts/start-local-dsh-web.sh
#
# 前置：
#   1. 隧道：bash scripts/tunnel_chemagent.sh（或任何等价的 8100/8001 转发）
#   2. LLM 密钥：scripts/local-dsh-env.sh（从 local-dsh-env.example.sh 复制）填
#      OPENAI_API_KEY（pjlab 网关；隔离 home 下无共享凭据库，必须显式提供）
#
# 用法：bash scripts/start-local-dsh-web.sh [--port 8399]
set -euo pipefail
cd "$(dirname "$0")/.."

PORT="${1:-8399}"
export DSH_HOME="${DSH_HOME:-$HOME/.dsh-qingshui}"

for p in 8100 8001; do
  if ! nc -z 127.0.0.1 "$p" 2>/dev/null; then
    echo "✗ 本机 $p 未监听——先起隧道：bash scripts/tunnel_chemagent.sh" >&2
    exit 1
  fi
done

# KNOWLEDGE_API_KEY 兜底：从仓内已提交的 deploy/chemagent/worker_supervisor.py 提取
if [ -z "${KNOWLEDGE_API_KEY:-}" ]; then
  KNOWLEDGE_API_KEY="$(grep -m1 '^KNOWLEDGE_API_KEY=' deploy/chemagent/worker_supervisor.py | cut -d= -f2)"
  export KNOWLEDGE_API_KEY
fi

ENV_FILE="scripts/local-dsh-env.sh"
if [ -f "$ENV_FILE" ]; then
  # shellcheck disable=SC1090
  source "$ENV_FILE"
fi
: "${KNOWLEDGE_API_KEY:?KNOWLEDGE_API_KEY 未设置（仓内兜底提取也失败）}"
# OPENAI_API_KEY：进程 env > scripts/local-dsh-env.sh > $DSH_HOME/.env（dsh 凭据层会读）
if [ -z "${OPENAI_API_KEY:-}" ] && ! grep -qs '^OPENAI_API_KEY=' "$DSH_HOME/.env"; then
  echo "✗ 缺 OPENAI_API_KEY（pjlab 网关）。任选其一：" >&2
  echo "    echo 'OPENAI_API_KEY=<key>' > $DSH_HOME/.env   # 推荐，一次到位" >&2
  echo "    或复制 scripts/local-dsh-env.example.sh 为 scripts/local-dsh-env.sh 填入" >&2
  exit 1
fi

# 首次引导：隔离 home 下 web profile 还没有 qingshui 插件时自动安装
PROFILE_PKG="$DSH_HOME/profiles/web/package.json"
if ! grep -q '"qingshui"' "$PROFILE_PKG" 2>/dev/null; then
  echo "· 首次引导：向隔离 home($DSH_HOME) 的 web profile 安装 qingshui 插件"
  node scripts/dsh.mjs plugin --profile web add ./plugins/qingshui
fi

PATCH_ARGS=(--patch patches/qingshui.yml --patch patches/local-pjlab-retry.yml)
if [ -f patches/local-mac.yml ]; then
  PATCH_ARGS+=(--patch patches/local-mac.yml)
fi

echo "✓ DSH_HOME=$DSH_HOME（与 MatDiscovery 隔离）"
echo "✓ 隧道 8100/8001 在线，启动 dsh web :$PORT"
exec node scripts/dsh.mjs --profile web \
  "${PATCH_ARGS[@]}" \
  --port "$PORT"
