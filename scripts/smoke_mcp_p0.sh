#!/usr/bin/env bash
set -euo pipefail
KEY="${KNOWLEDGE_API_KEY:?KNOWLEDGE_API_KEY required}"
BASE="${KNOWLEDGE_BASE_URL:-http://127.0.0.1:8000}"
MCP_HEALTH="${MCP_HEALTH_URL:-http://127.0.0.1:8100/health}"

# 摘要函数：head -c 截断避免大响应刷屏；不随管道 SIGPIPE 报错
snip() { head -c 400 || true; echo; }

echo "== semantic_search =="
curl -fsS -H "X-API-Key: $KEY" -H 'Content-Type: application/json' \
  -d '{"query":"硅片 毛利率","scope":"entities","top_k":3}' \
  "$BASE/api/v1/knowledge/search/semantic" | snip

echo "== metrics/compare =="
curl -fsS -H "X-API-Key: $KEY" -H 'Content-Type: application/json' \
  -d '{"dimension":"毛利率","scope":"硅片","top_k":5}' \
  "$BASE/api/v1/knowledge/metrics/compare" | snip

echo "== readiness =="
# 无 trailing slash：readiness router 会对 /api/v1/readiness/ 发 307
curl -fsSL -H "X-API-Key: $KEY" "$BASE/api/v1/readiness" | snip

echo "== links/history (sample) =="
curl -fsS -H "X-API-Key: $KEY" -H 'Content-Type: application/json' \
  -d '{"subject":"300861.SZ","dimension":"毛利率","limit":3}' \
  "$BASE/api/v1/knowledge/links/history" | snip

echo "== market/kline (sample) =="
curl -fsS -H "X-API-Key: $KEY" \
  "$BASE/api/v1/knowledge/market/kline?ts_code=000591.SZ&days=3" | snip

echo "== MCP /health (optional) =="
if curl -fsS "$MCP_HEALTH" | snip; then
  :
else
  echo "(MCP health skipped/unreachable)"
fi
