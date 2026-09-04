# Cloud Knowledge Boundaries Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立云端知识底座与本机 Agent 的单仓强边界基础骨架。

**Architecture:** 通过配置契约和 Compose profiles 区分 cloud-knowledge 与 local-agent；复用现有 IngestionJobWorker、EvidenceExtractionWorker 和 Knowledge API，不改变持久化模型。

**Tech Stack:** Python 3、Pydantic Settings、Docker Compose、pytest、MongoDB/PostgreSQL/Qdrant。

**Spec:** `docs/superpowers/specs/2026-09-01-cloud-knowledge-boundaries-design.md`

## Global Constraints

- 不拆仓库，不执行全量 Evidence 删除或重建。
- 数据库和 Qdrant 不新增公网暴露。
- Evidence 构建不调用 LLM，写入必须幂等。
- 密钥仅通过环境变量注入。

---

### Task 1: Worker 配置契约与启动校验

**Files:**
- Modify: `backend/app/config.py`
- Create: `backend/app/ops/worker_config.py`
- Create: `backend/tests/ops/test_worker_config.py`

**Interfaces:**
- Produces `WorkerSettings.from_environment()` and `validate_worker_role()` for CLI workers.

- [ ] Add tests for defaults, invalid role, and environment overrides.
- [ ] Run `pytest backend/tests/ops/test_worker_config.py -q` and observe initial failure.
- [ ] Implement typed settings and role validation without importing database clients.
- [ ] Re-run the focused test and then the existing config-related tests.

### Task 2: 独立 Evidence Worker CLI

**Files:**
- Modify: `backend/scripts/evidence_extraction_worker.py`
- Create: `backend/scripts/knowledge_worker.py`
- Create: `backend/tests/ops/test_knowledge_worker_cli.py`

**Interfaces:**
- `python -m scripts.knowledge_worker --role evidence-extraction` starts `EvidenceExtractionWorker` with validated settings.

- [ ] Write CLI parsing and dry-run tests.
- [ ] Run focused tests to verify failure.
- [ ] Implement role dispatch, signal-safe loop, and JSON startup summary.
- [ ] Run focused tests and existing Evidence worker tests.

### Task 3: Compose profiles 与环境样例

**Files:**
- Modify: `docker-compose.yml`
- Create: `docker-compose.cloud.yml`
- Create: `backend/.env.cloud.example`
- Create: `backend/.env.local-agent.example`
- Create: `backend/tests/ops/test_compose_contract.py`

- [ ] Add tests asserting cloud profile has one ingestion worker and bounded extraction concurrency.
- [ ] Run tests to verify failure.
- [ ] Add profile-specific services and remove duplicated secrets from examples.
- [ ] Validate with `docker compose -f docker-compose.yml -f docker-compose.cloud.yml config`.

### Task 4: Queue health and lock recovery command

**Files:**
- Create: `backend/scripts/knowledge_health.py`
- Modify: `backend/app/knowledge/evidence_service.py`
- Create: `backend/tests/knowledge/test_knowledge_health.py`

- [ ] Write tests for status counts and stale-running recovery.
- [ ] Run focused tests to verify failure.
- [ ] Implement read-only health JSON and bounded stale lock reset.
- [ ] Run focused tests plus the complete backend test suite.

### Task 5: Documentation and verification

**Files:**
- Modify: `README.md`
- Create: `docs/运维/云端知识底座Phase1.md`

- [ ] Document startup, env separation, health command, rollback and security invariants.
- [ ] Run compose config validation and full test suite.
- [ ] Review diff against spec and record evidence.
