# lwm-server-d Knowledge Extraction Migration Implementation Plan

> ⚠️ **已被取代（2026-09-23）**：本计划面向 `lwm-server-d`（sensecore），形态已由 **H 集群 chemagent**
> 取代（见 `AGENTS.md` 与 `docs/superpowers/specs/2026-09-23-chemagent-worker-deployment-design.md`）。
> API 契约部分仍有参考价值，部署部分仅作历史存档。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Enable remote PDF/Evidence workers to process jobs through authenticated HTTPS APIs.

**Architecture:** Cloud API owns PostgreSQL ingestion jobs and MongoDB Evidence; remote workers call claim/finish/upsert endpoints with X-API-Key. Stable IDs and lease-owner checks preserve idempotency and recovery.

**Tech Stack:** FastAPI, Pydantic, SQLAlchemy async, MongoDB/Motor.

**Spec:** `docs/运维/lwm-server-d知识抽取节点迁移实施方案.md`

## Global Constraints

- Worker and cloud communicate only via HTTPS + X-API-Key.
- Claim is lease-based and idempotent; success/failure validate lease owner.
- Evidence upsert uses stable Evidence ID and must be duplicate-safe.
- PDF storage remains local to the worker.

### Task 1: Add authenticated worker API boundary

- [x] Add `/api/v1/knowledge/jobs/claim`, `/{job_id}/success`, `/{job_id}/failure` and `/api/v1/knowledge/evidence/upsert`.
- [x] Register routes in `app.main`.
- [ ] Add endpoint tests with mocked queue/service and invalid-key cases.

### Task 2: Validate worker execution

- [ ] Run focused worker and queue tests.
- [ ] Run API import/route smoke check and document deployment commands.
