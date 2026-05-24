# Phase 10: 并发性能修复 - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-24
**Phase:** 10-并发性能修复
**Areas discussed:** 批量Claim实现方式, 并发测试策略, 配置参数设计

---

## 批量Claim实现方式

| Option | Description | Selected |
|--------|-------------|----------|
| MongoDB单次批量操作 | find + updateMany 单次操作，原子性最强 | ✓ |
| 多次串行claim | 重用一个claim_next_job，简单但多次往返 | |
| 混合方式 | 先批量查询再逐个更新 | |

**User's choice:** MongoDB单次批量操作
**Notes:** 原子性最强，减少网络往返

| Option | Description | Selected |
|--------|-------------|----------|
| 固定批量 | 传入固定数量 N，claim 最多 N 个 jobs | ✓ |
| 自适应批量 | 根据 pending 数量动态调整 | |
| 可配置批量 | 构造函数或参数传入 batch_size | |

**User's choice:** 固定批量
**Notes:** 简单明确

| Option | Description | Selected |
|--------|-------------|----------|
| 返回列表 | 简单直接，与现有 run_once 逻辑兼容 | ✓ |
| 返回字典带元数据 | 包含元数据但增加复杂度 | |
| 返回生成器 | 适合大批量但实现复杂 | |

**User's choice:** 返回列表
**Notes:** 简单直接

---

## 并发测试策略

| Option | Description | Selected |
|--------|-------------|----------|
| 集成测试 + 真实MongoDB | 使用 mongomock 或真实容器，完全验证原子性 | ✓ |
| 单元测试 + Mock | Mock MongoDB操作，测试逻辑正确性 | |
| 混合策略 | 单元测试验证逻辑 + 集成测试验证并发安全 | |

**User's choice:** 集成测试 + 真实MongoDB
**Notes:** 并发测试需要真实环境验证原子性

| Option | Description | Selected |
|--------|-------------|----------|
| 核心场景 | 测试 Semaphore 位置修复 + 批量 claim 原子性 | ✓ |
| 扩展场景 | 核心 + 并发执行时 job 不重复 + 错误恢复 | |
| 完整覆盖 | 扩展 + 多 worker 竞争 + 重试场景 | |

**User's choice:** 核心场景
**Notes:** 优先验证核心功能

---

## 配置参数设计

**User's choice:** 一次性确认所有决策，并考虑服务器约束

**关键约束：** 2C4G服务器（2核CPU，4GB内存）
- max_concurrency = 2 (保守配置)
- batch_size = 3 (内存/并发平衡)
- Semaphore 位置：`self._sem` 在 `__init__` 创建

**Notes:** 用户强调服务器配置是重要约束，需要在实现时考虑

---

## Claude's Discretion

参数默认值可通过环境变量或配置文件覆盖，支持运行时调整。

## Deferred Ideas

None — discussion stayed within phase scope