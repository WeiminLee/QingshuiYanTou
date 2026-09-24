#!/usr/bin/env python3
"""清水 worker 监督器：常驻，自动跟随 GPU 节点变化。

问题：knowledge_worker 是常驻进程，env 在启动时固化；rjob 重调度导致
      endpoints.json 的 node_ip 变化后，worker 会静默连旧地址直到人工重启。

做法：本进程持有 worker 子进程，周期性比对 endpoints.json：
  · node_ip 变化 → 重建 env 并重启 worker 子进程
  · GPU 探活失败 → 等待恢复
  · 子进程意外退出 → 重启
不依赖外部 systemd restart，故节点漂移可自愈。
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

M = Path("/mnt/shared-storage-user/liweimin/qingshui")
VENV = M / "worker" / "venv" / "bin" / "python"
CODE = Path("/root/wq/backend")
LOG = M / "logs"
ENDPOINTS = M / "endpoints.json"
ENV_FILE = M / "worker.env"
PROXY = "http://httpproxy-headless.kubebrain.svc.pjlab.local:3128"
JOB_TYPES = (sys.argv[1:] or ["link", "vector"])
CHECK_INTERVAL = 60

LOG.mkdir(parents=True, exist_ok=True)
_logf = open(LOG / "supervisor.log", "a", buffering=1)


def log(msg: str) -> None:
    line = f"[{time.strftime('%Y-%m-%dT%H:%M:%S%z')}][supervisor] {msg}"
    _logf.write(line + "\n")


def read_node() -> str | None:
    try:
        return json.loads(ENDPOINTS.read_text())["node_ip"] or None
    except Exception:
        return None


def gpu_alive(node: str) -> bool:
    try:
        with urllib.request.urlopen(f"http://{node}:23457/v1/models", timeout=5) as r:
            return r.status == 200
    except Exception:
        return False


def write_env(node: str) -> None:
    ENV_FILE.write_text(
        f"""KNOWLEDGE_API_URL=http://124.221.188.38:8080
KNOWLEDGE_API_KEY=sk-V-ZNidHIYdGK4rOXpPCsPw
EMBEDDING_BASE_URL=http://{node}:23456/v1
EMBEDDING_API_KEY=dummy
EMBEDDING_DIMENSION=1024
LLM_BASE_URL=http://{node}:23457/v1
LLM_API_KEY=dummy
LLM_MODEL=Qwen3.6-35B-A3B
LLM_EXTRACTION_MODEL=Qwen3.6-35B-A3B
LLM_DISABLE_THINKING=true
DATABASE_URL=postgresql+asyncpg://u:p@127.0.0.1:5432/none
MONGODB_URL=mongodb://127.0.0.1:27017
NEO4J_PASSWORD=dummy
PDF_STORAGE_ROOT={M}/qingshui-pdfs
WORKER_ROLE=evidence-extraction
WORKER_CONCURRENCY=24
WORKER_POLL_INTERVAL=5
"""
    )
    os.chmod(ENV_FILE, 0o600)


def worker_env() -> dict:
    env = dict(os.environ)
    for line in ENV_FILE.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip()
    node = read_node() or ""
    # httpx 不识别 CIDR：内网节点 IP 必须字面写入 no_proxy
    env.update({
        "http_proxy": PROXY, "https_proxy": PROXY,
        "no_proxy": f"127.0.0.1,{node},10.0.0.0/8,100.96.0.0/12,.pjlab.org.cn",
        "PYTHONPATH": str(CODE), "PYTHONUNBUFFERED": "1",
    })
    return env


children: dict[str, subprocess.Popen] = {}


def stop_all() -> None:
    for jt, p in children.items():
        if p.poll() is None:
            p.terminate()
    for jt, p in children.items():
        try:
            p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            p.kill()


def start_all(node: str) -> None:
    for jt in JOB_TYPES:
        out = open(LOG / f"worker-{jt}.log", "a", buffering=1)
        env = worker_env()
        env["WORKER_CONCURRENCY"] = "24"
        children[jt] = subprocess.Popen(
            [str(VENV), "-m", "scripts.knowledge_worker",
             "--role", "evidence-extraction", "--job-type", jt],
            cwd=str(CODE), env=env, stdout=out, stderr=subprocess.STDOUT,
        )
        log(f"started {jt} pid={children[jt].pid} node={node} conc=24")


def recover_orphan_leases() -> None:
    """回收上次进程遗留的 running 租约。

    进程被杀时租约不会释放，任务会卡在 running 直到 30 分钟 stale 超时。
    本机重启/切换并发后尤其明显，故启动时主动回收（只动本机 worker_id 前缀的）。
    """
    import glob
    try:
        import pymongo  # noqa: PLC0415  仅本机运维用途，缺失则跳过
    except ImportError:
        log("pymongo 不可用，跳过孤儿租约回收")
        return
    log("跳过孤儿租约回收（云端 Mongo 不可达，交由云端 stale 机制处理）")


def main() -> int:
    log(f"supervisor start job_types={JOB_TYPES}")
    signal.signal(signal.SIGTERM, lambda *_: (stop_all(), sys.exit(0)))
    current_node: str | None = None

    while True:
        node = read_node()
        if not node:
            log("endpoints.json 不可用，30s 后重试"); time.sleep(30); continue
        if not gpu_alive(node):
            # GPU 不可用：停掉子进程，避免它们反复连失效地址刷失败
            if children and any(p.poll() is None for p in children.values()):
                log(f"GPU {node} 不可用，停止 worker 子进程等待恢复")
                stop_all()
            log(f"GPU {node} 未就绪，30s 后重试"); time.sleep(30); continue
        if node != current_node:
            if current_node:
                log(f"节点变化 {current_node} -> {node}，重启 worker")
            stop_all()
            write_env(node)
            start_all(node)
            current_node = node
        else:
            # 常驻健康检查：子进程死了就补
            for jt, p in list(children.items()):
                if p.poll() is not None:
                    log(f"{jt} 意外退出 rc={p.returncode}，重启")
                    out = open(LOG / f"worker-{jt}.log", "a", buffering=1)
                    env = worker_env()
                    env["WORKER_CONCURRENCY"] = "24"
                    children[jt] = subprocess.Popen(
                        [str(VENV), "-m", "scripts.knowledge_worker",
                         "--role", "evidence-extraction", "--job-type", jt],
                        cwd=str(CODE), env=env, stdout=out, stderr=subprocess.STDOUT,
                    )
                    log(f"restarted {jt} pid={children[jt].pid}")
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    raise SystemExit(main())
