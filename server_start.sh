#!/usr/bin/env bash
# Cloud startup helper for QingShuiTouYan.
#
# Intended for a small Tencent Cloud server that should keep the knowledge
# base running while the local computer can be turned off.
#
# Usage:
#   ./server_start.sh start
#   ./server_start.sh stop
#   ./server_start.sh restart
#   ./server_start.sh status
#   ./server_start.sh logs backend
#   ./server_start.sh health
#
# Useful env overrides:
#   ENV_FILE=backend/.env
#   START_FRONTEND=0
#   PIP_INDEX_URL=https://mirrors.cloud.tencent.com/pypi/simple
#   PIP_TRUSTED_HOST=mirrors.cloud.tencent.com
#   DATA_JOB_WORKER_SCALE=1
#   EVIDENCE_WORKER_ENABLED=1
#   EVIDENCE_JOB_TYPES="combined vector"
#   EVIDENCE_MAX_CONCURRENCY=1
#   EVIDENCE_LIMIT_PER_LOOP=5
#   EVIDENCE_INTERVAL=60

set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/backend/.env}"
PROJECT_NAME="${COMPOSE_PROJECT_NAME:-qingshui}"
API_BASE="${API_BASE:-http://127.0.0.1:8080}"

START_FRONTEND="${START_FRONTEND:-0}"
DATA_JOB_WORKER_SCALE="${DATA_JOB_WORKER_SCALE:-1}"
PIP_INDEX_URL="${PIP_INDEX_URL:-https://mirrors.cloud.tencent.com/pypi/simple}"
PIP_TRUSTED_HOST="${PIP_TRUSTED_HOST:-mirrors.cloud.tencent.com}"
export PIP_INDEX_URL PIP_TRUSTED_HOST

EVIDENCE_WORKER_ENABLED="${EVIDENCE_WORKER_ENABLED:-1}"
EVIDENCE_JOB_TYPES="${EVIDENCE_JOB_TYPES:-combined vector}"
EVIDENCE_MAX_CONCURRENCY="${EVIDENCE_MAX_CONCURRENCY:-1}"
EVIDENCE_LIMIT_PER_LOOP="${EVIDENCE_LIMIT_PER_LOOP:-5}"
EVIDENCE_INTERVAL="${EVIDENCE_INTERVAL:-60}"

COMPOSE_ENV_ARGS=()
if [ -f "$ENV_FILE" ]; then
  COMPOSE_ENV_ARGS+=(--env-file "$ENV_FILE")
fi

cd "$ROOT_DIR"

info() { printf '[INFO] %s\n' "$*"; }
warn() { printf '[WARN] %s\n' "$*" >&2; }
err() { printf '[ERROR] %s\n' "$*" >&2; }

compose() {
  docker compose "${COMPOSE_ENV_ARGS[@]}" "$@"
}

usage() {
  cat <<'EOF'
Cloud startup helper for QingShuiTouYan.

Intended for a small Tencent Cloud server that should keep the knowledge
base running while the local computer can be turned off.

Usage:
  ./server_start.sh start
  ./server_start.sh stop
  ./server_start.sh restart
  ./server_start.sh status
  ./server_start.sh logs backend
  ./server_start.sh logs evidence
  ./server_start.sh health

Useful env overrides:
  ENV_FILE=backend/.env
  START_FRONTEND=0
  PIP_INDEX_URL=https://mirrors.cloud.tencent.com/pypi/simple
  PIP_TRUSTED_HOST=mirrors.cloud.tencent.com
  DATA_JOB_WORKER_SCALE=1
  EVIDENCE_WORKER_ENABLED=1
  EVIDENCE_JOB_TYPES="combined vector"
  EVIDENCE_MAX_CONCURRENCY=1
  EVIDENCE_LIMIT_PER_LOOP=5
  EVIDENCE_INTERVAL=60
EOF
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    err "Missing required command: $1"
    exit 1
  fi
}

preflight() {
  require_cmd docker

  if ! docker compose version >/dev/null 2>&1; then
    err "docker compose is not available"
    exit 1
  fi

  if ! docker info >/dev/null 2>&1; then
    err "Docker daemon is not running"
    exit 1
  fi

  if [ ! -f "$ENV_FILE" ]; then
    warn "Env file not found: $ENV_FILE"
    warn "Compose will use defaults from docker-compose.yml. This is not recommended for production."
  fi
}

cloud_services() {
  local services=("postgres" "mongo" "neo4j" "qdrant" "backend" "scheduler" "job-worker")
  if [ "$START_FRONTEND" = "1" ]; then
    services+=("frontend")
  fi
  printf '%s\n' "${services[@]}"
}

wait_for_container_health() {
  local service="$1"
  local timeout="${2:-90}"
  local elapsed=0
  local status=""

  info "Waiting for $service health..."
  while [ "$elapsed" -lt "$timeout" ]; do
    status="$(compose ps --format json "$service" 2>/dev/null | python3 -c '
import json, sys
raw = sys.stdin.read().strip()
if not raw:
    print("")
    raise SystemExit
try:
    rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
except Exception:
    print("")
    raise SystemExit
if not rows:
    print("")
else:
    print(rows[0].get("Health") or rows[0].get("State") or "")
')"
    if [ "$status" = "healthy" ] || [ "$status" = "running" ]; then
      info "$service is $status"
      return 0
    fi
    sleep 3
    elapsed=$((elapsed + 3))
  done

  warn "$service did not become healthy within ${timeout}s (last status: ${status:-unknown})"
  return 1
}

wait_for_backend() {
  if ! command -v curl >/dev/null 2>&1; then
    warn "curl not found; skipping backend health check"
    return 0
  fi

  local timeout="${1:-90}"
  local elapsed=0
  info "Waiting for backend health at $API_BASE/health..."
  while [ "$elapsed" -lt "$timeout" ]; do
    if curl -fsS --max-time 3 "$API_BASE/health" >/dev/null 2>&1; then
      info "backend health check passed"
      return 0
    fi
    sleep 3
    elapsed=$((elapsed + 3))
  done

  warn "backend health check did not pass within ${timeout}s"
  return 1
}

evidence_container_name() {
  local job_type="$1"
  printf '%s_evidence_%s_worker' "$PROJECT_NAME" "$job_type"
}

start_evidence_workers() {
  if [ "$EVIDENCE_WORKER_ENABLED" != "1" ]; then
    info "Evidence workers disabled (EVIDENCE_WORKER_ENABLED=$EVIDENCE_WORKER_ENABLED)"
    return 0
  fi

  local job_type
  for job_type in $EVIDENCE_JOB_TYPES; do
    local name
    name="$(evidence_container_name "$job_type")"

    info "Starting evidence worker: $job_type ($name)"
    docker rm -f "$name" >/dev/null 2>&1 || true

    compose run -d \
      --name "$name" \
      --no-deps \
      backend \
      python scripts/evidence_extraction_worker.py \
        --daemon \
        --interval "$EVIDENCE_INTERVAL" \
        --limit "$EVIDENCE_LIMIT_PER_LOOP" \
        --job-type "$job_type" \
        --max-concurrency "$EVIDENCE_MAX_CONCURRENCY" >/dev/null

    docker update --restart unless-stopped "$name" >/dev/null
  done
}

stop_evidence_workers() {
  local job_type
  for job_type in $EVIDENCE_JOB_TYPES combined vector signal; do
    docker rm -f "$(evidence_container_name "$job_type")" >/dev/null 2>&1 || true
  done
}

start_stack() {
  preflight

  local services=()
  while IFS= read -r service; do
    services+=("$service")
  done < <(cloud_services)

  info "Starting cloud knowledge stack..."
  info "Services: ${services[*]}"
  info "Data job-worker scale: $DATA_JOB_WORKER_SCALE"

  compose up -d \
    --scale "job-worker=$DATA_JOB_WORKER_SCALE" \
    "${services[@]}"

  wait_for_container_health postgres 90 || true
  wait_for_container_health mongo 90 || true
  wait_for_backend 120 || true

  start_evidence_workers

  info "Startup command finished. Use './server_start.sh status' to inspect containers."
}

stop_stack() {
  preflight
  info "Stopping evidence workers..."
  stop_evidence_workers
  info "Stopping compose services..."
  compose stop
}

down_stack() {
  preflight
  info "Removing evidence workers..."
  stop_evidence_workers
  info "Running docker compose down (volumes are kept)..."
  compose down
}

status_stack() {
  preflight
  compose ps
  printf '\nEvidence worker containers:\n'
  docker ps -a --filter "name=${PROJECT_NAME}_evidence_" --format 'table {{.Names}}\t{{.Status}}\t{{.Image}}'
}

logs_stack() {
  preflight
  if [ "${1:-}" = "evidence" ]; then
    docker logs -f "$(evidence_container_name combined)"
    return
  fi
  compose logs -f "${1:-backend}"
}

health_stack() {
  preflight
  status_stack
  printf '\nBackend health:\n'
  if command -v curl >/dev/null 2>&1; then
    curl -fsS "$API_BASE/health" || {
      printf '\n'
      exit 1
    }
    printf '\n'
  else
    warn "curl not found; cannot check $API_BASE/health"
  fi
}

cmd="${1:-start}"
shift || true

case "$cmd" in
  start)
    start_stack
    ;;
  stop)
    stop_stack
    ;;
  down)
    down_stack
    ;;
  restart)
    stop_stack
    start_stack
    ;;
  status)
    status_stack
    ;;
  logs)
    logs_stack "${1:-backend}"
    ;;
  health)
    health_stack
    ;;
  help|--help|-h)
    usage
    ;;
  *)
    err "Unknown command: $cmd"
    usage
    exit 2
    ;;
esac
