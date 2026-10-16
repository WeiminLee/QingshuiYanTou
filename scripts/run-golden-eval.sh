#!/usr/bin/env bash
# 清水投研 · 预期差金标「一轮优化」runner
#
# 逐案跑 dsh headless（隔离 DSH_HOME）→ 从 session.jsonl.zstd 归因工具清单 →
# 组装 harness_answers_<tag>.json → eval_dual_track.py 判分出报告。
# 串行执行（约 5min/案），保证 session 归因无歧义。
#
# 用法: bash scripts/run-golden-eval.sh [tag] [case_id]   # 默认 tag=glm_$(date +%F)
#        指定 case_id 时只重跑该案（marker 刷新后窗口归因自动正确）
# 前置:
#   1. 隧道：bash scripts/tunnel_chemagent.sh（8100/8001 转发到 chemagent）
#   2. LLM 凭据：~/.dsh-qingshui/.credentials.yaml（或 scripts/local-dsh-env.sh 里 OPENAI_API_KEY）
# 产物:
#   backend/eval/out/raw/<tag>/<case_id>.{answer.txt,stderr.log,exit,marker}
#   backend/eval/out/harness_answers_<tag>.json
#   backend/eval/out/expected_gap_<tag>.json
set -uo pipefail
cd "$(dirname "$0")/.."
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

TAG="${1:-glm_$(date +%F)}"
RUN_ONLY="${2:-}"
# 金标案集：默认 v2（v1 三案 + 台账/源材料/概念/补涨七新案）；回退用 CASES=... 覆盖
CASES="${CASES:-backend/eval/expected_gap_cases_v2.json}"; export CASES
GATE="${GATE:-0.8}"
export DSH_HOME="${DSH_HOME:-$HOME/.dsh-qingshui}"
OUTDIR="backend/eval/out"
RAW="$OUTDIR/raw/$TAG"
mkdir -p "$RAW"

for p in 8100 8001; do
  nc -z 127.0.0.1 "$p" >/dev/null 2>&1 || { echo "✗ 本机 $p 未监听——先起隧道：bash scripts/tunnel_chemagent.sh" >&2; exit 1; }
done
if [ -z "${KNOWLEDGE_API_KEY:-}" ]; then
  KNOWLEDGE_API_KEY="$(grep -m1 '^KNOWLEDGE_API_KEY=' deploy/chemagent/worker_supervisor.py | cut -d= -f2)"
  export KNOWLEDGE_API_KEY
fi
if [ -f scripts/local-dsh-env.sh ]; then
  # shellcheck disable=SC1090
  source scripts/local-dsh-env.sh
fi
: "${KNOWLEDGE_API_KEY:?KNOWLEDGE_API_KEY 未设置}"

echo "== 金标一轮 tag=$TAG DSH_HOME=$DSH_HOME =="

# B3 前置：必调工具 vs MCP 工具面缺口告警（非致命；仅整轮检查，单案重跑跳过）
if [ -z "$RUN_ONLY" ]; then
  python3 backend/scripts/eval_tools_preflight.py --cases "$CASES" || true
fi

# 逐案 headless（串行，保证 session 归因唯一；RUN_ONLY 指定时只跑该案）
python3 - "$CASES" "$RUN_ONLY" <<'PY' | while IFS=$'\t' read -r CID QUESTION; do
import json, sys
cases = json.load(open(sys.argv[1], encoding="utf-8"))
only = sys.argv[2]
for c in cases:
    if only and c["case_id"] != only:
        continue
    print(f"{c['case_id']}\t{c['question']}")
PY
  echo "── [$CID] $QUESTION"
  touch "$RAW/$CID.marker"
  node scripts/dsh.mjs --profile headless \
    --patch patches/qingshui.yml --patch patches/local-pjlab-retry.yml --patch patches/local-mac.yml \
    "$QUESTION" > "$RAW/$CID.answer.txt" 2> "$RAW/$CID.stderr.log"
  echo "$?" > "$RAW/$CID.exit"
  echo "   exit=$(cat "$RAW/$CID.exit") answer=$(wc -c < "$RAW/$CID.answer.txt" | tr -d ' ')B"
done

# 归因工具 + 组 answers + 判分
python3 backend/scripts/eval_collect_harness_round.py \
  --cases "$CASES" --raw-dir "$RAW" --dsh-home "$DSH_HOME" \
  --out "$OUTDIR/harness_answers_$TAG.json" || exit 1

python3 backend/scripts/eval_dual_track.py \
  --cases "$CASES" --mode harness-files \
  --answer-file "$OUTDIR/harness_answers_$TAG.json" \
  --out "$OUTDIR/expected_gap_$TAG.json" \
  --history "$OUTDIR/gate_history.jsonl" \
  --gate "$GATE" || FAIL_GATE=1

echo "== 判分结果（${TAG}）=="
python3 - "$OUTDIR/expected_gap_$TAG.json" <<'PY'
import json, sys
report = json.load(open(sys.argv[1], encoding="utf-8"))
passed = sum(1 for r in report if r.get("pass"))
for r in report:
    mark = "PASS" if r.get("pass") else "FAIL"
    print(f"  [{mark}] {r['case_id']}  reasons={r.get('reasons')}")
print(f"  {passed}/{len(report)} 通过")
PY

# 门禁失败以非零退出（launchd/cron 以此判红）；判分产物已落盘
exit "${FAIL_GATE:-0}"
