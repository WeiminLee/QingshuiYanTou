# Phase 10: 并发性能修复 - Context

**Gathered:** 2026-05-24
**Status:** Ready for planning

## Phase Boundary

修复 Evidence Worker 的并发控制缺陷，包括 Semaphore 位置错误和批量 Job Claim 实现，提升知识构建层的并发性能和效率。

## Implementation Decisions

### 批量Claim实现方式
- **D-01:** 批量Claim实现 — MongoDB单次批量操作 (`find` + `updateMany` 原子操作)
- **D-02:** 批量大小限制 — 固定数量 N，由调用方指定
- **D-03:** 返回结构 — 返回列表 `[job1, job2, ...]`

### 并发测试策略
- **D-04:** 测试环境 — 集成测试 + 真实MongoDB (`mongomock`)
- **D-05:** 测试覆盖范围 — 核心场景 (Semaphore修复 + 批量claim原子性)

### 配置参数设计
- **D-06:** Semaphore位置 — `self._sem` 在 `__init__` 创建，作为实例变量
- **D-07:** max_concurrency — 2 (2C4G服务器保守配置)
- **D-08:** batch_size — 3 (内存/并发平衡)

### Claude's Discretion
- 参数默认值可通过环境变量或配置文件覆盖，支持运行时调整

## Canonical References

Downstream agents MUST read these before planning or implementing.

### 核心代码
- `backend/app/knowledge/evidence_worker.py` — Worker实现，Semaphore位置修复目标
- `backend/app/knowledge/evidence_service.py` — Service层，claim_next_job实现

### 相关文档
- `.planning/REQUIREMENTS.md` §PERF-01/02 — Semaphore位置修复 + 批量claim需求
- `.planning/STATE.md` — 项目当前状态

## Existing Code Insights

### Reusable Assets
- `EvidenceService.claim_next_job()` — 现有claim逻辑，可参考实现模式
- `asyncio.Semaphore` — Python原生并发控制，已使用

### Established Patterns
- Async/await 模式 — 所有数据库操作都是 async
- MongoDB `find_one_and_update` — 原子更新操作

### Integration Points
- `EvidenceExtractionWorker.run_once()` — 需要改造使用新的 claim_batch_jobs
- `EvidenceService` — 需要新增 `claim_batch_jobs` 方法

## Specific Ideas

**服务器约束：2C4G（2核CPU，4GB内存）**
- CPU限制：2核，并发数不宜过高
- 内存限制：4GB，batch不宜太大，防止OOM
- 推荐配置：`batch_size=3, max_concurrency=2`

## Deferred Ideas

None — discussion stayed within phase scope

---

*Phase: 10-并发性能修复*
*Context gathered: 2026-05-24*