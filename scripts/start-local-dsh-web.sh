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

# KNOWLEDGE_API_KEY 兜底：从仓内已提交的 deploy/chemagent/worker_supervisor.py 提取
# （该值本来就在 git 里；env 文件方式优先）
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
# OPENAI_API_KEY 可缺省：dsh ~/.dsh/.credentials.yaml 里已有 pjlab 网关凭据
if [ -z "${OPENAI_API_KEY:-}" ]; then
  echo "· OPENAI_API_KEY 未设置，使用 dsh 凭据库（~/.dsh/.credentials.yaml）"
fi

PATCH_ARGS=(--patch patches/qingshui.yml)
# 本机覆盖（可选，勿提交）：如 patches/local-mac.yml 覆盖 knowledgeBaseUrl 等
if [ -f patches/local-mac.yml ]; then
  PATCH_ARGS+=(--patch patches/local-mac.yml)
fi

echo "✓ 隧道 8100/8001 在线，启动 dsh web :$PORT"
exec node scripts/dsh.mjs --profile web \
  "${PATCH_ARGS[@]}" \
  --port "$PORT"
