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

# launchd 环境 PATH 极简，必须显式带上 homebrew（node/pnpm 所在）
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

PORT="${1:-8399}"
export DSH_HOME="${DSH_HOME:-$HOME/.dsh-qingshui}"

for p in 8100 8001; do
  if ! nc -z 127.0.0.1 "$p" 2>/dev/null; then
    echo "✗ 本机 $p 未监听——先起隧道：bash scripts/tunnel_chemagent.sh" >&2
    exit 1
  fi
done

# 本地密钥（gitignored）：进程 env > scripts/local-dsh-env.sh
ENV_FILE="scripts/local-dsh-env.sh"
if [ -f "$ENV_FILE" ]; then
  # shellcheck disable=SC1090
  source "$ENV_FILE"
fi
if [ -z "${KNOWLEDGE_API_KEY:-}" ]; then
  echo "✗ 缺 KNOWLEDGE_API_KEY。复制模板并填入 chemagent backend/.env 的 API_KEY：" >&2
  echo "    cp scripts/local-dsh-env.example.sh scripts/local-dsh-env.sh && chmod 600 scripts/local-dsh-env.sh" >&2
  exit 1
fi
export KNOWLEDGE_API_KEY
# OPENAI_API_KEY：进程 env > scripts/local-dsh-env.sh > $DSH_HOME/.env > 凭据库软链
# （~/.dsh-qingshui/.credentials.yaml -> ~/.dsh/.credentials.yaml，复用 pjlab 网关 key）
if [ -z "${OPENAI_API_KEY:-}" ] && ! grep -qs '^OPENAI_API_KEY=' "$DSH_HOME/.env" 2>/dev/null && [ ! -f "$DSH_HOME/.credentials.yaml" ]; then
  echo "✗ 缺 OPENAI_API_KEY（pjlab 网关）。任选其一：" >&2
  echo "    echo 'OPENAI_API_KEY=<key>' > $DSH_HOME/.env   # 一次到位" >&2
  echo "    ln -sf ~/.dsh/.credentials.yaml $DSH_HOME/.credentials.yaml  # 复用 dsh 凭据库" >&2
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

echo "✓ DSH_HOME=${DSH_HOME}（与 MatDiscovery 隔离）"
echo "✓ 隧道 8100/8001 在线，启动 dsh web :$PORT"
exec node scripts/dsh.mjs --profile web \
  "${PATCH_ARGS[@]}" \
  --port "$PORT" \
  --no-open
