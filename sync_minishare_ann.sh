#!/usr/bin/env bash
set -euo pipefail

START_DATE="${1:-}"
END_DATE="${2:-$(date +%Y%m%d)}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="${SCRIPT_DIR}/logs/ann_sync"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOG_FILE="${LOG_DIR}/sync_${START_DATE:-default}_${END_DATE}_${TIMESTAMP}.log"

mkdir -p "$LOG_DIR"

echo ""
echo "========================================================"
echo " Minishare 公告历史回补"
echo "========================================================"
echo " 起始日期: ${START_DATE:-默认(2年前)}"
echo " 结束日期: ${END_DATE}"
echo " 日志文件: ${LOG_FILE}"
echo " 开始时间: $(date '+%Y-%m-%d %H:%M:%S')"
echo "========================================================"
echo ""

PY_ARGS=""
if [ -n "$START_DATE" ]; then
    PY_ARGS="${PY_ARGS} --start-date ${START_DATE}"
fi
PY_ARGS="${PY_ARGS} --end-date ${END_DATE}"

cd "${SCRIPT_DIR}/backend"

python -m scripts.sync_minishare_ann_history ${PY_ARGS} 2>&1 | tee -a "${LOG_FILE}"

EXIT_CODE="${PIPESTATUS[0]}"

echo ""
echo "========================================================"
echo " 执行完成"
echo "========================================================"
echo " 退出码: ${EXIT_CODE}"
echo " 完成时间: $(date '+%Y-%m-%d %H:%M:%S')"
echo " 日志文件: ${LOG_FILE}"
echo "========================================================"

exit "${EXIT_CODE}"
