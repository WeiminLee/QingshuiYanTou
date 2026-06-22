#!/bin/bash
#
# IRM 数据同步脚本
#
# 数据来源：
#   1. CSV 导入（历史数据）：python -m scripts.import_irm_csv
#   2. minishare 回补（增量数据）：python -m scripts.sync_minishare_irm_history
#
# 用法:
#   ./sync_irm.sh csv              # 从 CSV 导入历史数据
#   ./sync_irm.sh sync             # 用 minishare 回补增量
#   ./sync_irm.sh sync 20260523   # 从指定日期回补到今天
#   ./sync_irm.sh sync 20260523 20260630  # 指定日期范围
#

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$(dirname "$SCRIPT_DIR")"
cd "$BACKEND_DIR"

# 激活虚拟环境
if [ -f "$BACKEND_DIR/.venv/bin/activate" ]; then
    source "$BACKEND_DIR/.venv/bin/activate"
fi

# 解析参数
MODE="${1:-sync}"
DATE1="$2"
DATE2="${3:-$(date +%Y%m%d)}"

echo "============================================================"
echo "IRM 数据同步"
echo "============================================================"
echo "工作目录: $BACKEND_DIR"
echo "模式: $MODE"

if [ "$MODE" == "csv" ]; then
    # CSV 导入历史数据
    echo "数据源: tushare CSV 文件"
    python -m scripts.import_irm_csv --scope all
elif [ "$MODE" == "sync" ]; then
    # minishare 回补增量
    if [ -z "$DATE1" ]; then
        # 默认从昨天开始
        YESTERDAY=$(date -d "yesterday" +%Y%m%d)
        TODAY=$(date +%Y%m%d)
        echo "日期范围: ${YESTERDAY} ~ ${TODAY}"
        python -m scripts.sync_minishare_irm_history --start-date "$YESTERDAY" --end-date "$TODAY" --scope all
    else
        echo "日期范围: ${DATE1} ~ ${DATE2}"
        python -m scripts.sync_minishare_irm_history --start-date "$DATE1" --end-date "$DATE2" --scope all
    fi
else
    echo "未知模式: $MODE"
    echo "用法:"
    echo "  ./sync_irm.sh csv              # 从 CSV 导入历史数据"
    echo "  ./sync_irm.sh sync             # 用 minishare 回补增量"
    echo "  ./sync_irm.sh sync 20260523   # 从指定日期回补到今天"
    exit 1
fi

echo "============================================================"
echo "同步任务完成"
echo "============================================================"
