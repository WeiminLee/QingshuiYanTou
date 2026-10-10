#!/usr/bin/env bash
set -euo pipefail
KEY="${KNOWLEDGE_API_KEY:?KNOWLEDGE_API_KEY required}"
BASE="${KNOWLEDGE_BASE_URL:-http://127.0.0.1:8000}"
MCP_HEALTH="${MCP_HEALTH_URL:-http://127.0.0.1:8100/health}"

echo "== semantic_search =="
curl -fsS -H "X-API-Key: $KEY" -H 'Content-Type: application/json' \
  -d '{"query":"硅片 毛利率","scope":"entities","top_k":3}' \
  "$BASE/api/v1/knowledge/search/semantic" | head -c 400
echo

echo "== metrics/compare =="
curl -fsS -H "X-API-Key: $KEY" -H 'Content-Type: application/json' \
  -d '{"dimension":"毛利率","scope":"硅片","top_k":5}' \
  "$BASE/api/v1/knowledge/metrics/compare" | head -c 400
echo

echo "== readiness =="
curl -fsS -H "X-API-Key: $KEY" "$BASE/api/v1/readiness/" | head -c 400
echo

echo "== links/history (sample) =="
curl -fsS -H "X-API-Key: $KEY" -H 'Content-Type: application/json' \
  -d '{"subject":"300861.SZ","dimension":"毛利率","limit":3}' \
  "$BASE/api/v1/knowledge/links/history" | head -c 400
echo

echo "== MCP /health (optional) =="
if curl -fsS "$MCP_HEALTH" | head -c 400; then
  echo
else
  echo "(MCP health skipped/unreachable)"
fi
