#!/usr/bin/env bash
# Apply Qingshui's durable mintRpcId fix onto the dsh submodule (HTTP / non-secure origins).
# Does NOT modify upstream deepseek-harness remotes — local working-tree only.
#
# Usage (from Qingshui repo root):
#   ./deploy/dsh/apply-mint-rpc-id-patch.sh           # apply if needed
#   ./deploy/dsh/apply-mint-rpc-id-patch.sh --rebuild  # apply + rebuild connection client + web
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DSH="${ROOT}/dsh"
PATCH="${ROOT}/patches/dsh-web-api-mint-rpc-id.patch"
TARGET="packages/client/connection/src/client/web-api-client.ts"
REBUILD=0

for arg in "$@"; do
  case "$arg" in
    --rebuild) REBUILD=1 ;;
    -h|--help)
      sed -n '2,10p' "$0"
      exit 0
      ;;
    *)
      echo "unknown arg: $arg" >&2
      exit 2
      ;;
  esac
done

if [[ ! -f "$PATCH" ]]; then
  echo "missing patch: $PATCH" >&2
  exit 1
fi
if [[ ! -d "$DSH/.git" && ! -f "$DSH/.git" ]]; then
  echo "dsh submodule missing at $DSH" >&2
  exit 1
fi

cd "$DSH"

# Already applied?
if grep -q 'protected override mintRpcId' "$TARGET" 2>/dev/null; then
  echo "mintRpcId override already present in $TARGET"
else
  if git apply --check "$PATCH" 2>/dev/null; then
    git apply "$PATCH"
    echo "applied $PATCH"
  else
    echo "patch does not apply cleanly to current dsh tree (pin expected: b150a551)" >&2
    echo "inspect: git -C dsh status; git -C dsh diff -- $TARGET" >&2
    exit 1
  fi
fi

if [[ "$REBUILD" -eq 1 ]]; then
  echo "rebuilding dsh client connection + web…"
  export CI=true
  export pnpm_config_verify_deps_before_run=false
  # Prefer nvm node when available (cloud path)
  if [[ -s "${NVM_DIR:-$HOME/.nvm}/nvm.sh" ]]; then
    # shellcheck disable=SC1090
    . "${NVM_DIR:-$HOME/.nvm}/nvm.sh"
    nvm use 24 >/dev/null 2>&1 || true
  fi
  pnpm run build:lib:client
  pnpm run build:web
  echo "rebuild done"
fi
