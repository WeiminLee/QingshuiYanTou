#!/usr/bin/env bash
# 清水投研 · 预期差金标「一轮 + 退化终止自动重跑」runner
#
# 先跑完整一轮，再用 backend/scripts/eval_degenerate_guard.py 检出**退化终止**的案
# ——即「回合正常结束（turn/end=completed）但末条 assistant 消息既无 text 也无
# tool-call」的形态。这正是 pjlab 网关在限流下返回截断补全却谎报 stopReason:"stop"
# 时留下的痕迹（见 review_r1 / gap-wafer-margin-001 / session-38e06af1：step 7
# content=['reasoning']、286 output tokens、推理截断在 "...metric_tre"）。
# 未检出则与 run-golden-eval.sh 行为一致；检出则对该案重跑，直到无退化或重跑轮次用尽。
#
# **重跑必留痕**：每次重跑写入 $OUTDIR/<tag>.degenerate_retries.jsonl；
# 重跑用尽仍有退化案时以非零退出并明确报错，绝不把退化案伪装成正常完成。
#
# 用法: bash scripts/run-golden-eval-retry.sh [tag] [max_retry_rounds]   # 默认 tag=glm_$(date +%F), max=2
# 注意: 需要隧道（8100/8001）与 LLM 凭据，同 run-golden-eval.sh；串行执行。
set -uo pipefail
cd "$(dirname "$0")/.."
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

TAG="${1:-glm_$(date +%F)}"
MAX_ROUNDS="${2:-2}"
OUTDIR="backend/eval/out"
RAW="$OUTDIR/raw/$TAG"
LEDGER="$OUTDIR/${TAG}.degenerate_retries.jsonl"
export DSH_HOME="${DSH_HOME:-$HOME/.dsh-qingshui}"
CASES="${CASES:-backend/eval/expected_gap_cases_v2.json}"; export CASES

guard_ids() {
  python3 backend/scripts/eval_degenerate_guard.py \
    --raw-dir "$RAW" --dsh-home "$DSH_HOME" --ids 2>/dev/null
}

echo "== 金标一轮 + 退化重跑 tag=$TAG max_retry_rounds=$MAX_ROUNDS =="

# 首轮：判分不达标（exit 1）不算本轮失败，退化才是本脚本关心的信号。
bash scripts/run-golden-eval.sh "$TAG"

for round in $(seq 1 "$MAX_ROUNDS"); do
  ids="$(guard_ids || true)"
  if [ -z "$ids" ]; then
    echo "✓ 无退化终止案（第 $round 轮检查）"
    break
  fi
  echo "⚠ 第 $round 轮检出退化案：$(echo "$ids" | tr '\n' ' ')"
  for cid in $ids; do
    printf '%s\t%s\tretry_round=%s\n' \
      "$(date -Iseconds)" "$cid" "$round" >> "$LEDGER"
    echo "── 重跑 $cid"
    bash scripts/run-golden-eval.sh "$TAG" "$cid"
  done
done

if ! python3 backend/scripts/eval_degenerate_guard.py \
      --raw-dir "$RAW" --dsh-home "$DSH_HOME"; then
  echo "✗ 重跑用尽仍有退化终止案——请人工复核原始会话，不要将本轮视为正常完成" >&2
  echo "  留痕: $LEDGER" >&2
  exit 1
fi

echo "✓ 本轮无退化终止案；留痕（如有重跑）: $LEDGER"
