#!/usr/bin/env bash
# 清水投研 · 本地 Agent（dsh web）一键启动
#
# 前置：
#   1. 隧道：bash scripts/tunnel_chemagent.sh（或任何等价的 8100/8001 转发）
#   2. 密钥：复制 scripts/local-dsh-env.example.sh 为 scripts/local-dsh-env.sh 并填两个 key
#
# 用法：bash scripts/start-local-dsh-web.sh [--port 8399]
set -euo pipefail
cd "$(dirname "$0")/.."

PORT="${1:-8399}"

for p in 8100 8001; do
  if ! nc -z 127.0.0.1 "$p" 2>/dev/null; then
    echo "✗ 本机 $p 未监听——先起隧道：bash scripts/tunnel_chemagent.sh" >&2
    exit 1
  fi
done

ENV_FILE="scripts/local-dsh-env.sh"
if [ ! -f "$ENV_FILE" ]; then
  echo "✗ 缺 $ENV_FILE——从 scripts/local-dsh-env.example.sh 复制并填入两个 key" >&2
  exit 1
fi
# shellcheck disable=SC1090
source "$ENV_FILE"
: "${KNOWLEDGE_API_KEY:?KNOWLEDGE_API_KEY 未设置}"
: "${OPENAI_API_KEY:?OPENAI_API_KEY 未设置}"

PATCH_ARGS=(--patch patches/qingshui.yml)
# 本机覆盖（可选，勿提交）：如 patches/local-mac.yml 覆盖 knowledgeBaseUrl 等
if [ -f patches/local-mac.yml ]; then
  PATCH_ARGS+=(--patch patches/local-mac.yml)
fi

echo "✓ 隧道 8100/8001 在线，启动 dsh web :$PORT"
exec node scripts/dsh.mjs --profile web \
  "${PATCH_ARGS[@]}" \
  --port "$PORT"
