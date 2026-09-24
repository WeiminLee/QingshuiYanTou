# chemagent 部署资产

H 集群 chemagent 形态的运维脚本（2026-09-23 落地）。形态说明见
`docs/superpowers/specs/2026-09-23-chemagent-worker-deployment-design.md`。

## 拓扑

```
云端（存储/队列/编排）  ←──HTTP/代理──  dev 机 lwm-server-chemagent  ──内网──▶  H200 rjob
                    worker_supervisor.py 常驻（唯一枢纽）        vllm-openai:v0.28.0
```

**不变量**：云端连不到 GPU；GPU 断网只暴露内网 API；dev 机是唯一枢纽。

## 文件

| 文件 | 位置（运行时） | 职责 |
|---|---|---|
| `serve.sh` | shared storage，rjob 里执行 | 单卡双服务：`:23457` Qwen3.6 / `:23456` bge-m3；写 `endpoints.json` |
| `worker_supervisor.py` | shared storage，systemd 托管 | 常驻守护 knowledge_worker（link/vector），自动跟随 GPU 节点漂移 |
| `status.sh` | shared storage | 全栈状态一览 |

## 部署步骤

```bash
M=/mnt/shared-storage-user/liweimin/qingshui

# 1. 启动 GPU 推理（单卡，2 万-3 万端口）
rjob submit --name=qingshui-infer-1gpu --charged-group=chemagent_gpu_pool \
  --private-machine=group --image=registry.h.pjlab.org.cn/ailab/vllm-openai:v0.28.0 \
  --gpu=1 --cpu=16 --memory=128000 --auto-restart=true \
  --mount=gpfs://gpfs1/liweimin:/mnt/shared-storage-user/liweimin \
  -- bash $M/serve.sh

# 2. worker venv（Python 3.13，PyPI 直连经代理）
/root/miniconda3/bin/python3.13 -m venv --copies $M/worker/venv
$M/worker/venv/bin/pip install --index-url https://pypi.org/simple \
  -r <过滤掉 minishare/tinyshare 的 requirements>

# 3. systemd 单元（开机自启 + 崩溃重启）
#    ExecStart=$M/worker/venv/bin/python $M/worker_supervisor.py link vector

# 4. 状态
bash $M/status.sh
```

## 关键约束（踩坑定稿）

| 项 | 值/说明 |
|---|---|
| 推理镜像 | `registry.h.pjlab.org.cn/ailab/vllm-openai:v0.28.0`（不自建） |
| 必加参数 | `--language-model-only`（0.19.1 或漏此参数会挂死） |
| 单卡显存 | LLM `0.62`（KV 47.6GiB / 62× 并发）+ embedding `0.03` |
| thinking 关闭 | vLLM 须 `chat_template_kwargs.enable_thinking=False`；DeepSeek 格式无效（差 14 倍） |
| `no_proxy` | httpx 不识别 CIDR，GPU 节点 IP 必须**字面**写入 |
| worker 并发 | 24/24（GPU 可撑 62，但云端 PG 池是瓶颈） |
| Python | 3.13（3.10 缺 `datetime.UTC`） |
| pip 源 | PyPI 直连经代理（内网镜像大 wheel 硬 504） |
| 缓存持久化 | `TRITON_CACHE_DIR`/`DG_JIT_CACHE_DIR`/`VLLM_CACHE_ROOT`/`TORCH_EXTENSIONS_DIR` → shared storage |

## 自愈能力

| 事件 | 行为 |
|---|---|
| worker 崩溃 | supervisor 重启 |
| GPU 节点漂移 | supervisor 比对 `endpoints.json` → 重启 worker |
| GPU 不可用 | supervisor 停子进程等待 |
| rjob 被 kill | 平台 `--auto-restart` 重拉，缓存命中后秒级 |
| dev 机重启 | systemd `enabled` 自启 |
| 孤儿租约 | 云端 crontab 每 10 分钟回收 running > 5min |
