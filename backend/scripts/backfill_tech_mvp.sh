#!/bin/bash
#
# 科技股白名单数据回补脚本（2024-01-01 至今）
#
# 执行顺序:
#   1. 股票基础信息（FK 约束前置）
#   2. K 线日线（补齐缺失）
#   3. 公告历史（minishare + PDF）
#   4. IRM 互动易（全量 Q&A）
#   5. 进度检查
#
# 用法:
#   ./backfill_tech_mvp.sh
#   ./backfill_tech_mvp.sh --step kline    # 仅执行指定步骤
#   ./backfill_tech_mvp.sh --step announcements
#   ./backfill_tech_mvp.sh --step irm
#   ./backfill_tech_mvp.sh --step check
#
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$(dirname "$SCRIPT_DIR")"
cd "$BACKEND_DIR"

# 激活虚拟环境
if [ -f "$BACKEND_DIR/.venv/bin/activate" ]; then
    source "$BACKEND_DIR/.venv/bin/activate"
fi

# 配置
START_DATE="20240101"
END_DATE="$(date +%Y%m%d)"
SCOPE="tech_mvp"
LOG_DIR="$BACKEND_DIR/logs/backfill"
mkdir -p "$LOG_DIR"

TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/backfill_${TIMESTAMP}.log"

# 解析参数
STEP="all"
while [[ $# -gt 0 ]]; do
    case $1 in
        --step)
            STEP="$2"
            shift 2
            ;;
        *)
            shift
            ;;
    esac
done

echo "============================================================"
echo "科技股白名单数据回补"
echo "============================================================"
echo "时间范围: $START_DATE ~ $END_DATE"
echo "白名单: $SCOPE (1,916 只科技股)"
echo "执行步骤: $STEP"
echo "日志文件: $LOG_FILE"
echo "============================================================"

# Step 0: 检查白名单文件存在
WHITELIST="$BACKEND_DIR/data/board_concept/tech_ts_codes.txt"
if [ ! -f "$WHITELIST" ]; then
    echo "错误: 白名单文件不存在 $WHITELIST"
    exit 1
fi
echo "白名单股票数: $(wc -l < "$WHITELIST")"

# Step 1: 股票基础信息（前置依赖）
run_step1() {
    echo ""
    echo "[Step 1] 股票基础信息同步..."
    echo "----------------------------------------"
    python scripts/sync_stock_basic.py 2>&1 | tee -a "$LOG_FILE"
    echo "[Step 1] 完成"
}

# Step 2: K 线日线（补齐缺失）
run_step2() {
    echo ""
    echo "[Step 2] K 线日线同步..."
    echo "----------------------------------------"
    # 先检查缺失数量
    MISSING_KLINE=$(python -c "
from pathlib import Path
progress_file = Path('$BACKEND_DIR/scripts/.daily_sync_progress')
if progress_file.exists():
    synced = set(progress_file.read_text().strip().splitlines())
else:
    synced = set()
whitelist = set(Path('$WHITELIST').read_text().strip().splitlines())
missing = whitelist - synced
print(len(missing))
")
    echo "待补齐 K 线股票数: $MISSING_KLINE"

    if [ "$MISSING_KLINE" -gt 0 ]; then
        echo "开始 K 线回补..."
        python scripts/sync_daily_baostock.py \
            --scope "$SCOPE" \
            --start-date "$START_DATE" \
            --end-date "$END_DATE" \
            2>&1 | tee -a "$LOG_FILE"
    else
        echo "所有白名单股票 K 线已同步，跳过"
    fi
    echo "[Step 2] 完成"
}

# Step 3: 公告历史（minishare + PDF）
run_step3() {
    echo ""
    echo "[Step 3] 公告历史同步（minishare + PDF）..."
    echo "----------------------------------------"
    python scripts/sync_minishare_ann_history.py \
        --start-date "$START_DATE" \
        --end-date "$END_DATE" \
        --scope "$SCOPE" \
        2>&1 | tee -a "$LOG_FILE"
    echo "[Step 3] 完成"
}

# Step 4: IRM 互动易（全量）
run_step4() {
    echo ""
    echo "[Step 4] IRM 互动易同步..."
    echo "----------------------------------------"
    python scripts/sync_irm_history.py --exchange ALL 2>&1 | tee -a "$LOG_FILE"
    echo "[Step 4] 完成"
}

# Step 5: 进度检查
run_step5() {
    echo ""
    echo "[Step 5] 数据覆盖检查..."
    echo "----------------------------------------"

    # K 线覆盖率
    python -c "
import asyncio
from sqlalchemy import text
from app.core.database import engine
from pathlib import Path

async def check_kline():
    whitelist = set(Path('$WHITELIST').read_text().strip().splitlines())
    async with engine.connect() as conn:
        result = await conn.execute(text('SELECT DISTINCT ts_code FROM daily_data'))
        covered = set(row[0] for row in result.fetchall())
    covered_whitelist = whitelist & covered
    print(f'K 线: {len(covered_whitelist)}/{len(whitelist)} 白名单股覆盖')
    missing = whitelist - covered
    if missing and len(missing) <= 20:
        print(f'缺失: {sorted(list(missing))[:20]}')
    elif missing:
        print(f'缺失前 20: {sorted(list(missing))[:20]}...')

asyncio.run(check_kline())
" 2>&1 | tee -a "$LOG_FILE"

    # 公告 PDF 覆盖率
    python -c "
from pathlib import Path

whitelist = set(Path('$WHITELIST').read_text().strip().splitlines())
notice_root = Path('/home/lwm/qingshui_data/notices')
if notice_root.exists():
    dirs = set(d.name for d in notice_root.iterdir() if d.is_dir())
else:
    dirs = set()
covered_whitelist = whitelist & dirs
print(f'公告 PDF: {len(covered_whitelist)}/{len(whitelist)} 白名单股覆盖')
missing = whitelist - dirs
if missing and len(missing) <= 20:
    print(f'缺失: {sorted(list(missing))[:20]}')
elif missing:
    print(f'缺失前 20: {sorted(list(missing))[:20]}...')
" 2>&1 | tee -a "$LOG_FILE"

    # IRM 覆盖率
    python -c "
import asyncio
from sqlalchemy import text
from app.core.database import engine
from pathlib import Path

async def check_irm():
    whitelist = set(Path('$WHITELIST').read_text().strip().splitlines())
    async with engine.connect() as conn:
        result = await conn.execute(text(
            \"SELECT DISTINCT ts_code FROM announcements WHERE source_type LIKE 'irm%'\"
        ))
        covered = set(row[0] for row in result.fetchall())
    covered_whitelist = whitelist & covered
    print(f'IRM: {len(covered_whitelist)}/{len(whitelist)} 白名单股覆盖')

asyncio.run(check_irm())
" 2>&1 | tee -a "$LOG_FILE"
}

# 执行
case "$STEP" in
    stock_basic|step1)
        run_step1
        ;;
    kline|step2)
        run_step2
        ;;
    announcements|step3)
        run_step3
        ;;
    irm|step4)
        run_step4
        ;;
    check|step5)
        run_step5
        ;;
    all)
        run_step1
        run_step2
        run_step3
        run_step4
        run_step5
        ;;
    *)
        echo "未知步骤: $STEP"
        echo "可用: stock_basic, kline, announcements, irm, check, all"
        exit 1
        ;;
esac

echo ""
echo "============================================================"
echo "数据回补完成"
echo "============================================================"
echo "日志文件: $LOG_FILE"
