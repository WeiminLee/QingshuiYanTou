#!/bin/bash
# ============================================================
# 清水投研系统 - 统一启动脚本
#
# 启动：
#   bash backend/scripts/start_all.sh
#
# 停止：
#   bash backend/scripts/start_all.sh --stop
#
# 查看状态：
#   bash backend/scripts/start_all.sh --status
#
# 日志目录：
#   backend/logs/
#   └── uvicorn.log        - Backend API 日志
# ============================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$(dirname "$SCRIPT_DIR")"
LOG_DIR="$BACKEND_DIR/logs"
# uv 管理 Python 环境，统一用 uv run，禁止直接调用 .venv/bin/python
UV="uv"
# uv run --directory 确保在正确项目上下文中运行
UV_PY="$UV run --directory $BACKEND_DIR -- python"

mkdir -p "$LOG_DIR"

NAME_UVICORN="uvicorn"
PID_DIR="$BACKEND_DIR/.pids"

mkdir -p "$PID_DIR"

# ── 辅助函数 ───────────────────────────────────────────

pid_file() {
    echo "$PID_DIR/$1.pid"
}

get_pid() {
    local f="$(pid_file $1)"
    if [ -f "$f" ]; then
        cat "$f"
    fi
    echo ""
}

is_running() {
    local pid=$(get_pid $1)
    [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null
}

is_port_listening() {
    ss -tlnp 2>/dev/null | grep -q ":8000 " || netstat -tlnp 2>/dev/null | grep -q ":8000 "
}

start_uvicorn() {
    # ── 强制清理：无论 PID 文件/进程状态如何，端口被占用就必须清 ──
    if is_port_listening; then
        local occupying_pid
        occupying_pid=$(ss -tlnp 2>/dev/null | grep ":8000 " | grep -oP 'pid=\K[0-9]+' | head -1)
        if [ -n "$occupying_pid" ]; then
            echo "⚠ 端口 8000 被占用（PID $occupying_pid），强制清理 ..."
            # 杀掉该进程及其所有子进程
            local child
            for child in $(pgrep -P "$occupying_pid" 2>/dev/null); do
                kill -9 "$child" 2>/dev/null || true
            done
            kill -9 "$occupying_pid" 2>/dev/null || true
        else
            # 无法从 ss 输出取 PID，杀掉 PID 文件中的进程
            echo "⚠ 端口 8000 被占用（PID 文件：$(get_pid $NAME_UVICORN)），强制清理 ..."
            local old_pid=$(get_pid $NAME_UVICORN)
            for child in $(pgrep -P "$old_pid" 2>/dev/null); do
                kill -9 "$child" 2>/dev/null || true
            done
            kill -9 "$old_pid" 2>/dev/null || true
        fi
        # 等待端口释放
        for i in $(seq 1 10); do
            if ! is_port_listening; then
                echo "  ✓ 端口已释放"
                break
            fi
            sleep 1
        done
        if is_port_listening; then
            echo "✗ 端口 8000 仍无法释放，跳过启动。请手动处理。"
            return
        fi
    fi

    # 清理残留 PID 文件
    rm -f "$(pid_file $NAME_UVICORN)"

    # ── 系统自检 ─────────────────────────────────
    echo "运行系统自检 ..."
    if ! $UV_PY "$SCRIPT_DIR/health_check.py"; then
        echo "✗ 自检未通过，停止启动。请修复上述问题后重试。"
        exit 1
    fi

    echo "启动 Backend API ..."
    cd "$BACKEND_DIR"
    nohup $UV_PY -m uvicorn app.main:app \
        --host 0.0.0.0 --port 8000 \
        > "$LOG_DIR/uvicorn.log" 2>&1 &
    local pid=$!
    echo $pid > "$(pid_file $NAME_UVICORN)"
    sleep 2
    if is_running "$NAME_UVICORN"; then
        echo "✓ Backend API 已启动（PID $pid）"
    else
        echo "✗ Backend API 启动失败，查看日志："
        tail -20 "$LOG_DIR/uvicorn.log"
    fi
}

start_cls_polling() {
    echo "cls polling disabled (data via Tushare)"
}


stop_service() {
    local name=$1
    local pid=$(get_pid $name)
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
        echo "停止 $name（PID $pid）..."
        # 先杀子进程（uvicorn worker），再杀主进程（uv run wrapper）
        local child
        for child in $(pgrep -P "$pid" 2>/dev/null); do
            kill -9 "$child" 2>/dev/null || true
        done
        kill "$pid" 2>/dev/null || true
        sleep 1
        if kill -0 "$pid" 2>/dev/null; then
            kill -9 "$pid" 2>/dev/null || true
        fi
    fi
    rm -f "$(pid_file $name)"
    # 等待端口释放，避免下次启动时误判"已在运行"
    for i in $(seq 1 5); do
        if ! is_port_listening; then
            break
        fi
        sleep 1
    done
}

show_status() {
    echo ""
    echo "=== 清水投研系统 - 服务状态 ==="
    echo ""

    for name in "$NAME_UVICORN"; do
        if is_running "$name"; then
            echo "  ✓ $name  运行中（PID $(get_pid $name)）"
        elif [ "$name" = "$NAME_UVICORN" ] && is_port_listening; then
            echo "  ✓ $name  运行中（端口 8000 监听中）"
        else
            echo "  ✗ $name  未运行"
        fi
    done

    echo ""
    echo "=== 最近日志片段 ==="
    echo ""

    for log in "$LOG_DIR/uvicorn.log"; do
        if [ -f "$log" ]; then
            echo "--- $(basename $log) ---"
            tail -3 "$log"
            echo ""
        fi
    done

}

# ── 主逻辑 ───────────────────────────────────────────

case "${1:-}" in
    --stop)
        echo "停止所有服务 ..."
        stop_service "$NAME_UVICORN"
        echo "✓ 已停止所有服务"
        ;;

    --status)
        show_status
        ;;

    --restart)
        echo "重启所有服务 ..."
        stop_service "$NAME_UVICORN"
        sleep 2
        start_uvicorn
        echo ""
        echo "重启完成："
        show_status
        ;;

    "")
        echo "=== 清水投研系统启动 ==="
        start_uvicorn
        echo ""
        echo "所有服务已启动。"
        echo "查看状态：bash scripts/start_all.sh --status"
        echo "停止服务：bash scripts/start_all.sh --stop"
        echo ""
        echo "日志目录：$LOG_DIR/"
        ;;

    *)
        echo "用法：$0 [--stop|--status|--restart]"
        exit 1
        ;;
esac
