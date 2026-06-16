#!/bin/bash
# =============================================================================
# 清水投研系统 — 数据同步脚本
# =============================================================================
# 用法:
#   ./sync.sh daily                  # 每日增量同步（昨天数据）
#   ./sync.sh daily --irm-only       # 仅同步互动易
#   ./sync.sh daily --reports-only   # 仅同步研报
#   ./sync.sh daily --ann-only       # 仅同步公告
#   ./sync.sh history                # 历史批量回补（从上次断点继续）
#   ./sync.sh history --reports-only  # 仅回补研报
#   ./sync.sh history --irm-only      # 仅回补互动易
#   ./sync.sh history --ann-only      # 仅回补公告
#   ./sync.sh history 20250601 20260616  # 指定日期范围回补
#   ./sync.sh progress               # 查看回补进度
#   ./sync.sh status                 # 查看数据状态
#   ./sync.sh --help                 # 显示帮助
# =============================================================================

set -e

# ---- 配置 ---------------------------------------------------------------
API_BASE="${API_BASE:-http://localhost:8080}"
BACKEND_DIR="$(cd "$(dirname "$0")/backend" && pwd)"

# 从 .env 读取 API_KEY（默认 qingshui-secret）
load_api_key() {
    local env_file="${BACKEND_DIR}/.env"
    if [ -f "$env_file" ]; then
        local key=$(grep "^API_KEY=" "$env_file" | head -1 | cut -d'=' -f2- | tr -d '\r')
        if [ -n "$key" ]; then
            echo "$key"
            return
        fi
    fi
    echo "qingshui-secret"
}
API_KEY="${API_KEY:-$(load_api_key)}"

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
# 用法: api_call "POST" "/path" "query=val&body=val" "label"
#   或:  api_call "GET"  "/path?query=val" ""       "label"
api_call() {
    local method="$1"
    local path="$2"
    local data="$3"
    local label="$4"

    log_info "${label}..."
    log_info "  ${method} ${API_BASE}${path}${data:+?${data}}"

    if [ "$method" = "GET" ]; then
        RESPONSE=$(curl -s "${API_BASE}${path}" \
            -H "X-API-Key: ${API_KEY}" \
            --max-time 300)
    else
        if [[ "$path" == *"?start_date="* ]] || [[ "$path" == *"?trade_date="* ]]; then
            # query string already in URL (history endpoints)
            RESPONSE=$(curl -s -X "$method" "${API_BASE}${path}" \
                -H "X-API-Key: ${API_KEY}" \
                --max-time 600)
        else
            # form body (simple POST)
            RESPONSE=$(curl -s -X "$method" "${API_BASE}${path}" \
                -H "X-API-Key: ${API_KEY}" \
                -H "Content-Type: application/x-www-form-urlencoded" \
                -d "$data" \
                --max-time 300)
        fi
    fi

    if [ $? -ne 0 ]; then
        log_error "${label} 请求失败（网络错误）"
        return 1
    fi

    # 解析 JSON 响应（只读一次）
    echo "$RESPONSE" | python3 -c "
import sys, json
raw = sys.stdin.read()
try:
    d = json.loads(raw)
    tid = d.get('task_id', '-')
    status = d.get('status', '-')
    msg = d.get('message', '-')
    print(f'  task_id : {tid}')
    print(f'  status  : {status}')
    print(f'  message : {msg}')
    details = d.get('details', {})
    if details:
        for k, v in details.items():
            if k != 'error':
                print(f'  {k}     : {v}')
    err = details.get('error') or d.get('error')
    if err:
        print(f'  error   : {err}', file=sys.stderr)
except:
    print('  raw:', raw[:300])
" 2>&1

    STATUS=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.loads(sys.stdin.read()); print(d.get('status','?'))" 2>/dev/null || echo "?")
    if [ "$STATUS" = "completed" ] || [ "$STATUS" = "ok" ]; then
        log_ok "${label} 完成"
    elif [ "$STATUS" = "failed" ]; then
        log_error "${label} 失败"
    else
        log_warn "${label} 状态: ${STATUS}"
    fi
}


# ---- 轮询任务状态 -------------------------------------------------------
# 用法: watch_task "full_uuid" "label"
# 实时显示进度条，直到任务结束
watch_task() {
    local full_uuid="$1"
    local label="$2"
    local POLL_INTERVAL=3
    local MAX_POLL=1200  # 最多轮询 20 分钟

    local count=0
    while [ $((count * POLL_INTERVAL)) -lt $MAX_POLL ]; do
        count=$((count + 1))

        RESP=$(curl -sf "${API_BASE}/api/v1/sync/minishare/tasks/${full_uuid}" \
            -H "X-API-Key: ${API_KEY}" 2>/dev/null) || {
            echo -e "\${YELLOW}[WAIT]\${NC}  查询失败，等待重试..."
            sleep $POLL_INTERVAL
            continue
        }

        # 解析 JSON
        status=$(echo "$RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status','?'))" 2>/dev/null || echo "?")
        cur_wm=$(echo "$RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('current_watermark',''))" 2>/dev/null || echo "")
        days_pct=$(echo "$RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('progress',{}).get('days_pct',0))" 2>/dev/null || echo "0")
        success=$(echo "$RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('progress',{}).get('success',0))" 2>/dev/null || echo "0")
        skipped=$(echo "$RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('progress',{}).get('skipped',0))" 2>/dev/null || echo "0")
        fail=$(echo "$RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('progress',{}).get('fail',0))" 2>/dev/null || echo "0")
        err=$(echo "$RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('last_error') or '')" 2>/dev/null || echo "")

        # 进度条（50字符）
        pct_int=${days_pct%.*}
        filled=$((pct_int / 2))
        empty=$((50 - filled))
        bar=""
        for i in $(seq 1 $filled); do bar="${bar}█"; done
        for i in $(seq 1 $empty); do bar="${bar}░"; done

        printf "\r\${CYAN}[%s]\${NC}  %-30s  [%s]  %3d%%  日期:%s  succ:%s skip:%s fail:%s  " \
            "$status" "$label" "$bar" "$pct_int" "$cur_wm" "$success" "$skipped" "$fail"

        if [ "$status" = "completed" ] || [ "$status" = "success" ] || [ "$status" = "partial" ] || [ "$status" = "failed" ]; then
            echo ""
            if [ "$status" = "failed" ]; then
                [ -n "$err" ] && echo -e "\${RED}[ERROR]\${NC}  最后错误: ${err:0:120}"
                log_error "$label 失败 (status=$status)"
            else
                log_ok "$label 完成 (status=$status)"
            fi
            return 0
        fi

        sleep $POLL_INTERVAL
    done

    echo ""
    log_warn "$label 轮询超时（超过 ${MAX_POLL}s）"
}

# 提交异步任务并轮询
# 用法: submit_and_watch "endpoint" "data" "label"
submit_and_watch() {
    local path="$1"
    local data="$2"
    local label="$3"

    log_info "$label 提交任务..."
    log_info "  POST ${API_BASE}${path}${data:+?${data}}"

    RESP=$(curl -sf -X POST "${API_BASE}${path}${data:+?${data}}" \
        -H "X-API-Key: ${API_KEY}" \
        --max-time 30) || {
        log_error "$label 提交失败（网络错误）"
        return 1
    }

    task_id=$(echo "$RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('task_id',''))" 2>/dev/null || echo "")
    status=$(echo "$RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status',''))" 2>/dev/null || echo "")
    message=$(echo "$RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('message',''))" 2>/dev/null || echo "")

    echo "$RESP" | python3 << 'PYEOF2'
import sys, json
try:
    d = json.loads(sys.stdin.read())
    print("  task_id :", d.get("task_id","-"))
    print("  status  :", d.get("status","-"))
    print("  message :", d.get("message","-"))
except:
    pass
PYEOF2

    if [ "$status" = "completed" ] || [ "$status" = "ok" ]; then
        log_ok "$label 完成"
        return 0
    elif [ "$status" = "failed" ]; then
        log_error "$label 失败"
        return 1
    fi

    # 从 message 中提取完整 UUID
    full_uuid=$(echo "$message" | grep -oE '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}' | head -1)
    if [ -z "$full_uuid" ]; then
        log_warn "$label 无法提取任务 UUID，跳过轮询"
        return 0
    fi

    echo ""
    watch_task "$full_uuid" "$label"
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
            --ann-only)
                log_info "=== 每日增量同步：公告 ==="
                api_call "POST" "/api/v1/sync/minishare/announcements" "" "minishare 公告"
                ;;
            "")
                log_info "=== 每日增量同步：研报 + 互动易 + 公告 ==="
                api_call "POST" "/api/v1/sync/minishare/reports" "" "minishare 研报"
                echo ""
                api_call "POST" "/api/v1/sync/minishare/irm" "" "minishare 互动易"
                echo ""
                api_call "POST" "/api/v1/sync/minishare/announcements" "" "minishare 公告"
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
            --ann-only)       TARGET="ann" ;;
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
            echo ""
            submit_and_watch \
                "/api/v1/sync/minishare/reports/history" \
                "start_date=${START_DATE}&end_date=${END_DATE}&download_pdf=false" \
                "研报批量回补 (minishare)"
        fi

        if [ "$TARGET" = "both" ]; then
            echo ""
        fi

        if [ "$TARGET" = "irm" ] || [ "$TARGET" = "both" ]; then
            submit_and_watch \
                "/api/v1/sync/minishare/irm/history" \
                "start_date=${START_DATE}&end_date=${END_DATE}" \
                "互动易批量回补 (minishare)"
        fi

        if [ "$TARGET" = "ann" ] || [ "$TARGET" = "both" ]; then
            if [ "$TARGET" = "both" ]; then
                echo ""
            fi
            submit_and_watch \
                "/api/v1/sync/minishare/announcements/history" \
                "start_date=${START_DATE}&end_date=${END_DATE}" \
                "公告批量回补 (minishare)"
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