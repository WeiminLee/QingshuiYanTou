# Cloud Knowledge Boundaries Refactor Design

## Goal

在保持单仓的前提下，建立云端知识底座与本机 Agent 的运行边界，为远程 PDF/Evidence Worker 提供可观测、可回滚的 Phase 1 基础骨架。

## Architecture

系统划分为 Data Foundation、Evidence Fabric、Knowledge Extraction、Knowledge API、Agent Runtime 和 Ops 六个边界。云端持续运行 API、scheduler、ingestion worker 与低并发 extraction worker；本机 Agent 通过 Knowledge API 访问云端，数据库直连仅作为显式开发 fallback。

## Scope

- 新增 cloud/local-agent 配置样例与 compose profiles。
- 统一 Worker 运行参数与启动校验。
- 将 job-worker 默认资源调整为云端小规格安全值，并提供独立 Evidence worker 服务。
- 增加健康检查、队列状态统计和锁超时恢复入口。
- 保留旧 Evidence，不在本阶段执行全量删除或重建。

## Non-goals

- 不拆分仓库或引入完整微服务平台。
- 不迁移数据库、不暴露数据库公网端口。
- 不在本阶段执行全量 Evidence 重建或远程机器变更。

## Invariants

- Evidence 构建不调用 LLM；公告章节过滤 `_classify_announcement_chapter()` 保持不变。
- Evidence/job 写入幂等，重复运行不产生重复 ID。
- Worker 离线或异常时任务可恢复，不永久停留在 running。
- 密钥只通过环境变量注入，不进入 Git。

## Interfaces

Worker 配置提供 `WORKER_ROLE`、`WORKER_CONCURRENCY`、`WORKER_POLL_INTERVAL`、`WORKER_JOB_TIMEOUT`、`PDF_STORAGE_ROOT`。健康检查命令返回 JSON，至少包含数据库连通性、Evidence 数量和各 job 状态计数。

## Testing

新增配置契约、job claim/锁恢复、健康检查和 compose 配置测试；运行现有 backend 单元测试与新增测试。
