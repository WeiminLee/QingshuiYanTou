#!/usr/bin/env bash
# 清水投研 · 能力面端到端冒烟（不跑 LLM 评测）
#
# 逐项打透 Agent 工具面：
#   P0 老九件回归 + P0.5 十二件新读工具 + 台账写两件（幂等性双写验证）+ MCP 工具清单
# 用法：KNOWLEDGE_API_KEY=... bash scripts/smoke_capability.sh
#   KNOWLEDGE_BASE（默认 http://127.0.0.1:8001，经隧道）/ MCP_BASE（默认 http://127.0.0.1:8100/mcp）
# 退出码：0=全绿；1=有失败项。
set -uo pipefail
cd "$(dirname "$0")/.."
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

BASE="${KNOWLEDGE_BASE:-http://127.0.0.1:8001}"
MCP="${MCP_BASE:-http://127.0.0.1:8100/mcp}"
KEY="${KNOWLEDGE_API_KEY:?需要 KNOWLEDGE_API_KEY}"
export BASE MCP KEY

PASS=0; FAIL=0; FAILED_ITEMS=()

# jget <file> <py-expr on d>，读取 JSON 到 python 断言
jcheck() { # jcheck <名称> <json文件> <断言表达式（d=解析对象）>
  local name="$1" file="$2" expr="$3"
  if python3 -c "
import json, sys
d = json.load(open('$file', encoding='utf-8'))
sys.exit(0 if ($expr) else 1)
" 2>/dev/null; then
    echo "  PASS $name"; PASS=$((PASS+1))
  else
    echo "  FAIL $name  ($expr)"; FAIL=$((FAIL+1)); FAILED_ITEMS+=("$name")
  fi
}

post() { # post <路径> <json体> <输出文件>
  curl -sS -m 60 -H "X-API-Key: $KEY" -H 'Content-Type: application/json' \
    -d "$2" "$BASE$1" > "$3" 2>/dev/null
}
get() {
  curl -sS -m 60 -H "X-API-Key: $KEY" "$BASE$1" > "$2" 2>/dev/null
}

T=$(mktemp -d); trap 'rm -rf "$T"' EXIT

echo "== 清水能力面 E2E（$BASE | MCP $MCP）=="

echo "── 鉴权负例 ──"
curl -sS -m 10 -H 'Content-Type: application/json' -d '{}' \
  "$BASE/api/v1/knowledge/ledger/history" -o "$T/noauth.json" 2>/dev/null
code=$(python3 -c "import json;print(json.load(open('$T/noauth.json')).get('detail','') != '' or 'x')" 2>/dev/null; echo $?)
jcheck "ledger/history 无鉴权拒绝" "$T/noauth.json" "d.get('detail') is not None"

echo "── P0 老九件回归 ──"
post /api/v1/readiness/ '{}' "$T/readiness.json" 2>/dev/null || true
get /api/v1/readiness "$T/readiness.json"
jcheck "data_readiness" "$T/readiness.json" "isinstance(d, dict) and len(d) >= 3"

get "/api/v1/knowledge/market/kline?ts_code=300308.SZ&start_date=20260901&end_date=20261013" "$T/kline.json"
jcheck "get_kline" "$T/kline.json" "d.get('count', 0) > 0 and len(d.get('items', [])) > 0"

get "/api/v1/knowledge/market/stock_profile?ts_code=300308.SZ" "$T/profile.json"
jcheck "get_stock_profile" "$T/profile.json" "'中际旭创' in d.get('text', '') or d.get('main_business') != ''"

post /api/v1/knowledge/links/history '{"subject":"中晶科技","dimension":"毛利率","limit":10}' "$T/hist.json"
jcheck "pull_history" "$T/hist.json" "d.get('count', 0) > 0 and d['items'][0].get('evidence_id')"

post /api/v1/knowledge/search/semantic '{"query":"硅片 毛利率","scope":"entities","top_k":3}' "$T/sem.json"
jcheck "semantic_search" "$T/sem.json" "len(d.get('entities', [])) > 0"

post /api/v1/knowledge/metrics/compare '{"dimension":"毛利率","scope":"硅片","top_k":5}' "$T/cmp.json"
jcheck "compare_metric" "$T/cmp.json" "d.get('count', 0) > 0"

post /api/v1/knowledge/links/lookup_players '{"keyword_norm_text":"硅片","top_k":5}' "$T/players.json"
jcheck "lookup_players" "$T/players.json" "len(d.get('items', [])) > 0"

post /api/v1/knowledge/links/lookup_products '{"company":"中晶科技","top_k":5}' "$T/products.json"
jcheck "lookup_products" "$T/products.json" "len(d.get('items', [])) >= 0 and 'count' in d"

# 从 history 动态取真实 EV（供 fetch_evidence / backlinks / 台账写用）
python3 -c "
import json
d = json.load(open('$T/hist.json', encoding='utf-8'))
item = d['items'][0]
open('$T/ev.txt', 'w').write(item['evidence_id'])
open('$T/ev_text.txt', 'w').write(item.get('text_excerpt') or '')
"

EV=$(cat "$T/ev.txt") ; EVLEN=$(python3 -c "print(len(open('$T/ev_text.txt').read()))")
[ -z "$EV" ] && { echo "  (无可用 EV，后续项将失败）"; }

get "/api/v1/knowledge/evidence/$EV" "$T/evdoc.json"
jcheck "fetch_evidence" "$T/evdoc.json" "d.get('evidence_id') == '$EV'"

echo "── P0.5 新读工具 ──"
post /api/v1/knowledge/sources/announcement '{"ts_code":"003026.SZ","page_size":3}' "$T/ann.json"
jcheck "get_announcement" "$T/ann.json" "d.get('count', 0) > 0"

post /api/v1/knowledge/sources/irm '{"ts_code":"003026.SZ","keyword":"认证","page_size":5}' "$T/irm.json"
jcheck "get_irm" "$T/irm.json" "d.get('count', 0) > 0"

post /api/v1/knowledge/sources/events '{"query":"光模块","top_n":3}' "$T/events.json"
jcheck "find_events" "$T/events.json" "d.get('count', 0) > 0"
python3 -c "
import json
d = json.load(open('$T/events.json', encoding='utf-8'))
items = d.get('items', [])
open('$T/evid_event.txt','w').write(items[0]['event_id'] if items else '')
"
EVEV=$(cat "$T/evid_event.txt")
post /api/v1/knowledge/sources/event_detail "{\"event_id\":\"$EVEV\"}" "$T/evdetail.json"
jcheck "get_event_detail" "$T/evdetail.json" "d.get('found') == True and d.get('content') != ''"

post /api/v1/knowledge/links/scan_dimension '{"dimension":"毛利率","limit":5}' "$T/scan.json"
jcheck "scan_dimension" "$T/scan.json" "d.get('count', 0) > 0"

post "/api/v1/knowledge/links/backlinks" "{\"evidence_id\":\"$EV\"}" "$T/bk.json"
jcheck "backlinks" "$T/bk.json" "len(d.get('keywords', [])) > 0"

post /api/v1/knowledge/market/concept_top '{"days":5,"top_n":5}' "$T/ct.json"
jcheck "get_top_concepts" "$T/ct.json" "len(d.get('items', d.get('concepts', []))) > 0"
# 兼容返回形态，动态取第一个概念的 code/name
python3 -c "
import json
d = json.load(open('$T/ct.json', encoding='utf-8'))
items = d.get('items') or d.get('concepts') or []
first = items[0] if items else {}
code = first.get('ts_code') or first.get('concept_code') or ('CPO' if not items else '')
open('$T/concept.txt','w').write(str(code))
"
CONC=$(cat "$T/concept.txt"); CONC=${CONC:-CPO}
post /api/v1/knowledge/market/concept_stocks "{\"concept_code\":\"$CONC\",\"limit\":5}" "$T/cs.json"
jcheck "get_concept_stocks" "$T/cs.json" "len(d.get('stocks', d.get('items', []))) > 0"

post /api/v1/knowledge/market/stock_concepts '{"ts_code":"300308.SZ"}' "$T/sc.json"
jcheck "get_stock_concepts" "$T/sc.json" "len(d.get('concepts', d.get('items', []))) > 0"

post /api/v1/knowledge/ledger/history '{"subject":"中晶科技","dimension":"产线进展"}' "$T/lh.json"
jcheck "history_findings" "$T/lh.json" "'observations' in d and isinstance(d['observations'], list)"

post /api/v1/knowledge/ledger/search '{"kind":"progression"}' "$T/ls.json"
jcheck "search_findings" "$T/ls.json" "'count' in d"

post /api/v1/knowledge/ledger/watermark '{"subject_ts_code":"003026.SZ","dimension":"产线进展"}' "$T/wm.json"
jcheck "watermark" "$T/wm.json" "'found' in d"

echo "── 台账写门（E2E 专用维度，幂等双写） ──"
SPANS=$(python3 -c "print(min(3, $EVLEN)); print($EVLEN)")
S1=$(echo "$SPANS" | head -1); S2=$(echo "$SPANS" | tail -1)
post /api/v1/knowledge/ledger/observation "{\"subject_ts_code\":\"003026.SZ\",\"dimension\":\"E2E冒烟\",\"evidence_id\":\"$EV\",\"span_start\":$S1,\"span_end\":$S2,\"stage_raw\":\"冒烟验证\",\"stage_level\":1}" "$T/obs1.json"
jcheck "write_observation 首写" "$T/obs1.json" "d.get('ok') == True and d.get('obs_id','').startswith('OB:')"
post /api/v1/knowledge/ledger/observation "{\"subject_ts_code\":\"003026.SZ\",\"dimension\":\"E2E冒烟\",\"evidence_id\":\"$EV\",\"span_start\":$S1,\"span_end\":$S2,\"stage_raw\":\"冒烟验证\",\"stage_level\":1}" "$T/obs2.json"
jcheck "write_observation 幂等重写" "$T/obs2.json" "d.get('ok') == True"
python3 -c "
import json
a = json.load(open('$T/obs1.json')); b = json.load(open('$T/obs2.json'))
sys_exit = 0 if a.get('obs_id') == b.get('obs_id') else 1
import sys; sys.exit(sys_exit)
" && { echo "  PASS 幂等 obs_id 一致"; PASS=$((PASS+1)); } || { echo "  FAIL 幂等 obs_id 一致"; FAIL=$((FAIL+1)); FAILED_ITEMS+=("obs_id 幂等"); }

OBSID=$(python3 -c "import json; print(json.load(open('$T/obs1.json')).get('obs_id',''))")
post /api/v1/knowledge/ledger/finding "{\"subject_ts_code\":\"003026.SZ\",\"dimension\":\"E2E冒烟\",\"kind\":\"new_event\",\"judgment\":\"E2E 冒烟写入验证——观察到台账链路贯通\",\"supports\":[{\"evidence_id\":\"$EV\",\"span_start\":$S1,\"span_end\":$S2,\"obs_id\":\"$OBSID\"}],\"to_state\":{\"level\":1,\"stage\":\"冒烟验证\"},\"confidence\":0.9}" "$T/fd1.json"
jcheck "write_finding 首写" "$T/fd1.json" "d.get('ok') == True and d.get('finding_id','').startswith('FD:')"
post /api/v1/knowledge/ledger/finding "{\"subject_ts_code\":\"003026.SZ\",\"dimension\":\"E2E冒烟\",\"kind\":\"new_event\",\"judgment\":\"E2E 冒烟写入验证——观察到台账链路贯通\",\"supports\":[{\"evidence_id\":\"$EV\",\"span_start\":$S1,\"span_end\":$S2,\"obs_id\":\"$OBSID\"}],\"to_state\":{\"level\":1,\"stage\":\"冒烟验证\"},\"confidence\":0.9}" "$T/fd2.json"
jcheck "write_finding 幂等重写" "$T/fd2.json" "d.get('ok') == True"
python3 -c "
import json, sys
a = json.load(open('$T/fd1.json')); b = json.load(open('$T/fd2.json'))
sys.exit(0 if a.get('finding_id') == b.get('finding_id') else 1)
" && { echo "  PASS 幂等 finding_id 一致"; PASS=$((PASS+1)); } || { echo "  FAIL 幂等 finding_id 一致"; FAIL=$((FAIL+1)); FAILED_ITEMS+=("finding_id 幂等"); }

post /api/v1/knowledge/ledger/finding "{\"subject_ts_code\":\"003026.SZ\",\"dimension\":\"E2E冒烟\",\"kind\":\"hunch\",\"judgment\":\"x\",\"supports\":[{\"evidence_id\":\"$EV\",\"span_start\":$S1,\"span_end\":$S2}]}" "$T/fdbad.json"
jcheck "write_finding 非法 kind 拒写" "$T/fdbad.json" "d.get('ok') == False and 'kind 非法' in d.get('errors', [''])[0]"

echo "── MCP 面 ──"
curl -sS -m 10 "$MCP_BASE_HACKED" -o /dev/null 2>/dev/null || true
curl -sS -m 20 -H "X-API-Key: $KEY" -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' "$MCP" > "$T/mcp.json" 2>/dev/null
python3 -c "
import json, sys
raw = open('$T/mcp.json').read()
# streamable-http 可能以 SSE 事件包裹
if raw.lstrip().startswith('event:') or 'data:' in raw[:200]:
    raw = [l for l in raw.splitlines() if l.startswith('data:')][0][5:].strip()
d = json.loads(raw)
names = {t['name'] for t in d['result']['tools']}
expected = {'fetch_evidence','semantic_search','compare_metric','pull_history','lookup_players','lookup_products','get_kline','get_stock_profile','data_readiness','get_announcement','get_irm','find_events','get_event_detail','scan_dimension','backlinks','get_top_concepts','get_concept_stocks','get_stock_concepts','history_findings','search_findings','watermark'}
missing = expected - names
print(f'MCP tools: {len(names)} 个，期望 21，缺失: {missing or \"无\"}')
sys.exit(1 if missing else 0)
" && { echo "  PASS MCP tools/list 21 件齐"; PASS=$((PASS+1)); } || { echo "  FAIL MCP tools/list"; FAIL=$((FAIL+1)); FAILED_ITEMS+=("MCP tools/list"); }

curl -sS -m 10 -o /dev/null -w "%{http_code}" "http://127.0.0.1:8100/health" 2>/dev/null \
  | grep -q 200 && { echo "  PASS MCP /health"; PASS=$((PASS+1)); } || { echo "  FAIL MCP /health"; FAIL=$((FAIL+1)); FAILED_ITEMS+=("MCP /health"); }

echo "== 结果：PASS=$PASS FAIL=$FAIL =="
if [ "$FAIL" -gt 0 ]; then
  printf '失败项: %s\n' "${FAILED_ITEMS[*]}"
  exit 1
fi
echo "能力面全部贯通"
