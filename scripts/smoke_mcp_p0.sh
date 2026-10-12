#!/usr/bin/env bash
set -euo pipefail
KEY="${KNOWLEDGE_API_KEY:?KNOWLEDGE_API_KEY required}"
BASE="${KNOWLEDGE_BASE_URL:-http://127.0.0.1:8000}"
MCP_HEALTH="${MCP_HEALTH_URL:-http://127.0.0.1:8100/health}"

# 摘要函数：截断避免大响应刷屏；curl 写管道被截断不视为失败
snip() { head -c 400; echo; }
probe() {
  # $@ = curl 参数；成功(2xx)即输出截断 body
  # head 截断会让 curl 收到 SIGPIPE(141)，body 已到手就不算失败
  local body
  body=$(curl -fsS "$@" 2>/dev/null | head -c 400; echo "PIPE_OK")
  body=${body%PIPE_OK}
  [ -n "$body" ] || { echo "FAILED"; return 1; }
  printf '%s\n' "$body"
}

echo "== semantic_search =="
probe -H "X-API-Key: $KEY" -H 'Content-Type: application/json' \
  -d '{"query":"硅片 毛利率","scope":"entities","top_k":3}' \
  "$BASE/api/v1/knowledge/search/semantic"

echo "== metrics/compare =="
probe -H "X-API-Key: $KEY" -H 'Content-Type: application/json' \
  -d '{"dimension":"毛利率","scope":"硅片","top_k":5}' \
  "$BASE/api/v1/knowledge/metrics/compare"

echo "== readiness =="
# 无 trailing slash：readiness router 会对 /api/v1/readiness/ 发 307
probe -H "X-API-Key: $KEY" "$BASE/api/v1/readiness"

echo "== links/history (sample) =="
probe -H "X-API-Key: $KEY" -H 'Content-Type: application/json' \
  -d '{"subject":"300861.SZ","dimension":"毛利率","limit":3}' \
  "$BASE/api/v1/knowledge/links/history"

echo "== market/kline (sample) =="
probe -H "X-API-Key: $KEY" \
  "$BASE/api/v1/knowledge/market/kline?ts_code=000591.SZ&days=3"

echo "== MCP /health (optional) =="
if probe "$MCP_HEALTH"; then
  :
else
  echo "(MCP health skipped/unreachable)"
fi
