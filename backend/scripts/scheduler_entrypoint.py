#!/usr/bin/env python
"""Resolve the scheduler LLM endpoint before starting APScheduler.

Priority:
  1. Self-hosted GPU from endpoints.json (rjob writes it).
  2. Gateway extraction model already configured, if /v1/models still lists it.
  3. Gateway fallback token order from LLM_EXTRACTION_FALLBACK_ORDER.

The scheduler must still start when the GPU node is down: collection tasks
(kline/concept/news) keep running, and extraction keeps using whatever model
the gateway serves. Resolution happens once per container start; after an rjob
reschedule, restart the scheduler container so it follows the new node IP.
"""
from __future__ import annotations

import json
import os
import urllib.request

ENDPOINTS_FILE = os.environ.get("GPU_ENDPOINTS_FILE", "/data/qingshui/endpoints.json")
GPU_MODEL = os.environ.get("GPU_LLM_MODEL", "Qwen3.6-35B-A3B")
GPU_PORT = os.environ.get("GPU_LLM_PORT", "23457")


def _models(base: str, key: str = "", timeout: float = 5.0) -> list[str]:
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    req = urllib.request.Request(base.rstrip("/") + "/models", headers=headers)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=timeout) as resp:
        payload = json.loads(resp.read())
    return [item["id"] for item in payload.get("data", []) if item.get("id")]


def _gpu_base() -> str | None:
    try:
        with open(ENDPOINTS_FILE, encoding="utf-8") as fh:
            node = json.load(fh)["node_ip"]
    except Exception as exc:  # noqa: BLE001 — endpoints.json is optional
        print(f"[entrypoint] GPU endpoints unavailable ({exc}); keeping configured LLM", flush=True)
        return None
    base = f"http://{node}:{GPU_PORT}/v1"
    try:
        if GPU_MODEL in _models(base):
            return base
        print(f"[entrypoint] GPU {base} does not serve {GPU_MODEL}; keeping configured LLM", flush=True)
    except Exception as exc:  # noqa: BLE001 — node down / not scheduled yet
        print(f"[entrypoint] GPU {base} unreachable ({exc}); keeping configured LLM", flush=True)
    return None


def _gateway_model(available: list[str]) -> str | None:
    current = os.environ.get("LLM_EXTRACTION_MODEL", "")
    if current in available:
        return current
    order = os.environ.get("LLM_EXTRACTION_FALLBACK_ORDER", "flash,minimax,*")
    for token in (part.strip() for part in order.split(",")):
        if not token:
            continue
        if token == "*":
            return available[0] if available else None
        hit = next((name for name in available if token.lower() in name.lower()), None)
        if hit:
            return hit
    return available[0] if available else None


def main() -> None:
    base = _gpu_base()
    if base:
        os.environ["LLM_BASE_URL"] = base
        os.environ["LLM_MODEL"] = GPU_MODEL
        os.environ["LLM_EXTRACTION_MODEL"] = GPU_MODEL
        os.environ["LLM_API_KEY"] = "dummy"
        print(f"[entrypoint] scheduler LLM -> {base} model={GPU_MODEL}", flush=True)
    else:
        gateway = os.environ.get("LLM_BASE_URL", "")
        key = os.environ.get("LLM_API_KEY", "")
        try:
            available = _models(gateway, key) if gateway else []
        except Exception as exc:  # noqa: BLE001 — keep configured env
            available = []
            print(f"[entrypoint] gateway model list failed ({exc})", flush=True)
        chosen = _gateway_model(available) if available else None
        if chosen:
            os.environ["LLM_EXTRACTION_MODEL"] = chosen
            print(f"[entrypoint] scheduler LLM -> gateway {gateway} model={chosen}", flush=True)
        else:
            print("[entrypoint] no reachable extraction model; starting with configured env", flush=True)

    os.execvp("python", ["python", "-m", "app.data_pipeline.scheduler"])


if __name__ == "__main__":
    main()
