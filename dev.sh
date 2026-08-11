#!/bin/bash
# =============================================================================
# 清水投研系统 — 一键开发启动脚本
# =============================================================================
# 用法:  ./dev.sh
#
# 启动顺序：
#   1. Docker 基础设施 (PostgreSQL + Redis + MongoDB)
#   2. Alembic 数据库迁移
#   3. 后端 API (uvicorn)
#   4. 前端 Dev Server (vite)
# =============================================================================
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"

# 颜色
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; }

# 清理函数
cleanup() {
    info "正在关闭服务..."
    # 关闭后端
    if [ -n "${UVICORN_PID:-}" ]; then
        kill "$UVICORN_PID" 2>/dev/null || true
    fi
    # 关闭前端
    if [ -n "${VITE_PID:-}" ]; then
        kill "$VITE_PID" 2>/dev/null || true
    fi
    info "服务已关闭"
}
trap cleanup EXIT

# ── 1. 检查环境 ────────────────────────────────────────────────

info "检查环境..."

# Python venv
if [ ! -f "$BACKEND_DIR/.venv/bin/activate" ]; then
    error "Python venv 不存在，请先创建: cd $BACKEND_DIR && python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
    exit 1
fi

# Node 依赖
if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
    warn "前端依赖未安装，正在安装..."
    cd "$FRONTEND_DIR" && npm install
fi

# Colima / Docker
if ! docker info >/dev/null 2>&1; then
    warn "Docker 未运行，尝试启动 Colima..."
    if command -v colima &> /dev/null; then
        colima start
    else
        error "Docker 不可用，请先启动 Docker 或 Colima"
        exit 1
    fi
fi

# ── 2. 启动基础设施 ────────────────────────────────────────────

info "启动基础设施 (PostgreSQL + Redis + MongoDB)..."
cd "$ROOT_DIR"
docker compose up -d postgres redis mongo 2>&1 | grep -v "platform does not match" || true

# 等待 PostgreSQL 就绪
info "等待 PostgreSQL 就绪..."
for i in $(seq 1 30); do
    if docker compose exec postgres pg_isready -U qingshui >/dev/null 2>&1; then
        info "PostgreSQL 就绪"
        break
    fi
    if [ "$i" -eq 30 ]; then
        error "PostgreSQL 启动超时"
        exit 1
    fi
    sleep 2
done

# 等待 Redis 就绪
info "等待 Redis 就绪..."
for i in $(seq 1 15); do
    if docker compose exec redis redis-cli ping >/dev/null 2>&1; then
        info "Redis 就绪"
        break
    fi
    if [ "$i" -eq 15 ]; then
        warn "Redis 未响应，继续启动..."
    fi
    sleep 1
done

# ── 3. 数据库迁移 ──────────────────────────────────────────────

info "执行数据库迁移..."
cd "$BACKEND_DIR"
source .venv/bin/activate
alembic upgrade head 2>&1 || warn "迁移执行失败，可能已是最新"
deactivate

# ── 4. 启动后端 ────────────────────────────────────────────────

info "启动后端 API (localhost:8000)..."
cd "$BACKEND_DIR"
source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload &
UVICORN_PID=$!
deactivate

# 等待后端就绪
info "等待后端就绪..."
for i in $(seq 1 15); do
    if curl -s http://localhost:8000/health >/dev/null 2>&1; then
        info "后端就绪"
        break
    fi
    if [ "$i" -eq 15 ]; then
        warn "后端未响应，继续启动前端..."
    fi
    sleep 1
done

# ── 5. 启动前端 ────────────────────────────────────────────────

info "启动前端 Dev Server (localhost:3000)..."
cd "$FRONTEND_DIR"
npx vite --host &
VITE_PID=$!

# ── 完成 ───────────────────────────────────────────────────────

echo ""
info "================================================"
info "  清水投研系统 开发环境已启动"
info "  前端:  http://localhost:3000"
info "  后端:  http://localhost:8000"
info "  健康:  http://localhost:8000/health"
info "  API:   http://localhost:8000/api/v1/readiness"
info "================================================"
echo ""
info "按 Ctrl+C 停止所有服务"

# 等待子进程
wait