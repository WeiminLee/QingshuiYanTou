# Agent 阻塞项修复（2026-10-09）

## 1. HybridSearch Embedding（云端 Connection refused）

- **现象**：云端 backend `EMBEDDING_BASE_URL=http://172.18.0.1:11434/v1`，但 11434 无人监听；云端直连 chemagent GPU `100.103.242.214:23456` 超时。
- **铁律**：H 集群→云可走实验室 HTTP 代理；云→H 集群 GPU 无直连；禁止依赖 Mac 作**长期**隧道。
- **本次过渡通道**（验收用）：
  1. Mac：`ssh -N -L 127.0.0.1:23456:100.103.242.214:23456 lwm-server-chemagent`
  2. Mac：`ssh -N -R 172.18.0.1:11434:127.0.0.1:23456 root@124.221.188.38`
  3. 验证：`curl -s -m 5 http://172.18.0.1:11434/v1/models`（云端与 backend 容器均 200）
- **未改** `.env` 中的 `EMBEDDING_BASE_URL`（仍指向 bridge）；长期应改为 chemagent 常驻反向隧道或云侧 embedding 旁路，去掉 Mac。

## 2. readiness → conclusion_policy=blocked

- **原因**：`research_report` 空表且 `required_for_reasoning=True` → overall=`unavailable` → policy=`blocked`；`announcement` PG 非 IRM max 停在 2026-08-16（正式公告主池已迁 Mongo）。
- **修复**：
  - `research_report.required_for_reasoning=False`（未接 token 前不作硬门禁；仍出现在 sources）。
  - announcement 最新日 = max(PG 非 IRM, cninfo 同步成功日, Mongo `kg_evidence` 限时查询)。

## 3. agent_wall_timeout_seconds

- 默认 `150` → `450`；`agent_synthesis_timeout_seconds` → `120`。云端 `.env` 同步注入。

## 4. find_events asyncpg different-loop

- `events.py` 改为 `async_session()`（走 `_async_runner` 隔离 NullPool），不再直接 `engine.connect()`。

## 5. 墙钟截断后无结论（收尾合成超时）

- **现象**：`compare_metric` 等工具已成功，但墙钟用尽后 `收尾合成失败: TimeoutError()`，用户只看到 450s 提示。
- **修复**：收尾改为压缩工具结果摘要喂模型（不再塞全量 messages）；`agent_synthesis_timeout_seconds=180`；合成仍失败时确定性回退工具摘要正文。
