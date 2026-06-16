#!/bin/bash
# =============================================================================
# 清水投研系统 — 数据同步脚本
# =============================================================================
# 用法:
#   ./sync.sh daily                  # 每日增量同步（昨天数据）
#   ./sync.sh daily --irm-only       # 仅同步互动易
#   ./sync.sh daily --reports-only   # 仅同步研报
#   ./sync.sh history                # 历史批量回补（从上次断点继续）
#   ./sync.sh history --reports-only  # 仅回补研报
#   ./sync.sh history --irm-only      # 仅回补互动易
#   ./sync.sh history 20250601 20260616  # 指定日期范围回补
#   ./sync.sh progress               # 查看回补进度
#   ./sync.sh status                 # 查看数据状态
#   ./sync.sh --help                 # 显示帮助
# =============================================================================

set -e

# ---- 配置 ---------------------------------------------------------------
API_BASE="${API_BASE:-http://localhost:8080}"
API_KEY="${API_KEY:-qingshui-secret}"
BACKEND_DIR="$(cd "$(dirname "$0")/backend" && pwd)"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# ---- 工具函数 -----------------------------------------------------------
log_info()  { echo -e "${CYAN}[INFO]${NC}  $1"; }
log_ok()    { echo -e "${GREEN}[ OK ]${NC}  $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1" >&2; }

usage() {
    head -32 "$0" | tail -26 | sed 's/^#//' | sed 's/^ //'
    echo ""
    echo "环境变量:"
    echo "  API_BASE   API 基础地址 (默认: http://localhost:8080)"
    echo "  API_KEY    API 密钥     (默认: qingshui-secret)"
    echo ""
    echo "示例:"
    echo "  API_KEY=my-key ./sync.sh history 20250601 20260616"
}

# 检查后端是否运行
check_backend() {
    if ! curl -sf "${API_BASE}/health" > /dev/null 2>&1; then
        log_error "后端未运行，请先启动: cd ${BACKEND_DIR} && .venv/bin/python -m uvicorn app.main:app --port 8080"
        exit 1
    fi
}

# 通用 API 调用
api_call() {
    local method="$1"
    local path="$2"
    local data="$3"
    local label="$4"

    log_info "${label}..."
    log_info "  POST ${API_BASE}${path}"
    if [ -n "$data" ]; then
        log_info "  data: ${data}"
    fi

    RESPONSE=$(curl -s -X "${method}" "${API_BASE}${path}" \
        -H "X-API-Key: ${API_KEY}" \
        -H "Content-Type: application/x-www-form-urlencoded" \
        ${data:+-d "$data"} \
        --max-time 300)

    if [ $? -ne 0 ]; then
        log_error "${label} 请求失败（网络错误）"
        return 1
    fi

    echo "$RESPONSE" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(f\"  task_id : {d.get('task_id', '-')}\")
    print(f\"  status  : {d.get('status', '-')}\")
    print(f\"  message : {d.get('message', '-')}\")
    details = d.get('details', {})
    if details:
        for k, v in details.items():
            if k != 'error':
                print(f'  {k}     : {v}')
    if 'error' in details or 'error' in d:
        print(f\"  error   : {details.get('error', d.get('error', ''))}\", file=sys.stderr)
except:
    print('  raw:', sys.stdin.read()[:200])
" 2>&1

    STATUS=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status','?'))" 2>/dev/null || echo "?")
    if [ "$STATUS" = "completed" ] || [ "$STATUS" = "ok" ]; then
        log_ok "${label} 完成"
    else
        log_warn "${label} 状态: ${STATUS}"
    fi
}

# =============================================================================
# 命令处理
# =============================================================================

MODE="${1:-}"
shift || true

case "$MODE" in
    --help|-h|help)
        usage
        exit 0
        ;;
    daily)
        check_backend

        # 解析选项
        OPT=""
        while [[ "$1" =~ ^-- ]]; do
            OPT="$1"
            shift
        done

        case "$OPT" in
            --irm-only)
                log_info "=== 每日增量同步：互动易 ==="
                api_call "POST" "/api/v1/sync/minishare/irm" "" "minishare 互动易"
                ;;
            --reports-only)
                log_info "=== 每日增量同步：研报 ==="
                api_call "POST" "/api/v1/sync/minishare/reports" "" "minishare 研报"
                ;;
            "")
                log_info "=== 每日增量同步：研报 + 互动易 ==="
                api_call "POST" "/api/v1/sync/minishare/reports" "" "minishare 研报"
                echo ""
                api_call "POST" "/api/v1/sync/minishare/irm" "" "minishare 互动易"
                ;;
            *)
                log_error "未知选项: $OPT"
                usage
                exit 1
                ;;
        esac
        ;;

    history)
        check_backend

        # 解析选项 / 日期参数
        OPT=""
        START_DATE=""
        END_DATE=""
        TARGET="both"

        while [[ "$#" -gt 0 ]]; do
            if [[ "$1" =~ ^-- ]]; then
                OPT="$1"
            elif [[ "$1" =~ ^[0-9]{8}$ ]] && [ -z "$START_DATE" ]; then
                START_DATE="$1"
            elif [[ "$1" =~ ^[0-9]{8}$ ]] && [ -z "$END_DATE" ]; then
                END_DATE="$1"
            else
                OPT="$1"
            fi
            shift
        done

        case "$OPT" in
            --irm-only)       TARGET="irm" ;;
            --reports-only)   TARGET="reports" ;;
            "")               TARGET="both" ;;
            *)
                log_error "未知选项: $OPT"
                usage
                exit 1
                ;;
        esac

        # 默认一年前到昨天
        if [ -z "$END_DATE" ]; then
            END_DATE=$(date -d "yesterday" +%Y%m%d)
        fi
        if [ -z "$START_DATE" ]; then
            START_DATE=$(date -d "1 year ago" +%Y%m%d)
        fi

        log_info "=== 历史批量回补: ${START_DATE} ~ ${END_DATE} ==="

        if [ "$TARGET" = "reports" ] || [ "$TARGET" = "both" ]; then
            api_call "POST" "/api/v1/sync/minishare/reports/history" \
                "start_date=${START_DATE}&end_date=${END_DATE}&source=research" \
                "研报批量回补 (minishare)"
        fi

        if [ "$TARGET" = "both" ]; then
            echo ""
        fi

        if [ "$TARGET" = "irm" ] || [ "$TARGET" = "both" ]; then
            api_call "POST" "/api/v1/sync/minishare/irm/history" \
                "start_date=${START_DATE}&end_date=${END_DATE}" \
                "互动易批量回补 (minishare)"
        fi
        ;;

    progress)
        check_backend
        log_info "=== 查询断点续跑进度 ==="
        RESPONSE=$(curl -s "${API_BASE}/api/v1/sync/minishare/progress" \
            -H "X-API-Key: ${API_KEY}")
        echo "$RESPONSE" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    if 'progress' in d:
        for p in d['progress']:
            src = p.get('source', '-')
            task = p.get('task_name', '-')
            last = p.get('last_success_watermark', '-')
            total = p.get('total_fetched', '-')
            print(f'  {src}/{task}: 最新日期={last}, 已抓取={total}')
    else:
        print(json.dumps(d, indent=2, ensure_ascii=False))
except:
    sys.stdout.write(sys.stdin.read())
" 2>&1
        ;;

    status)
        check_backend
        log_info "=== 数据同步状态 ==="
        RESPONSE=$(curl -s "${API_BASE}/api/v1/sync/status" \
            -H "X-API-Key: ${API_KEY}")
        echo "$RESPONSE" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    for section, info in d.items():
        print(f'  {section}:')
        if isinstance(info, dict):
            for k, v in info.items():
                print(f'    {k}: {v}')
        else:
            print(f'    {info}')
except:
    sys.stdout.write(sys.stdin.read())
" 2>&1
        ;;

    *)
        if [ -z "$MODE" ]; then
            log_error "缺少命令参数"
        else
            log_error "未知命令: $MODE"
        fi
        usage
        exit 1
        ;;
esac