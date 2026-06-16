# Evidence Pipeline 设计文档

> 2026-06-16 | 知识构建层第一阶段：数据 → Evidence → 追踪

## 背景

PostgreSQL 已有 35 万公告 + 1 万研报 + 23 条互动易。Neo4j/Qdrant 为空。
需要将 PostgreSQL 源数据转为 MongoDB Evidence，再由 Worker 消费抽取到 KG。

## 数据特征分析

| 数据源 | 数量 | 文本特征 | Chunk 策略 |
|--------|------|----------|------------|
| 公告 (minishare_announcements) | 351,345 | title 平均 26 字符，无正文 | 不分块，1 条 = 1 Evidence |
| 互动易 (announcements irm:) | 23 | 问题平均 63 字符，最长 199 | 不分块，1 条 = 1 Evidence |
| 研报 (research_report_meta) | 10,170 | 需从 PDF 解析正文，几千字 | 后续阶段，用 chunker |

**公告和互动易都是短文本，不需要分块。** 每条源记录直接映射为一个 Evidence。

## 架构

```
PostgreSQL                    MongoDB                     Neo4j / Qdrant
┌──────────────────┐    ┌──────────────────────┐    ┌──────────────────┐
│minishare_        │    │ kg_evidence           │    │ KG Extractor     │
│announcements ────┼───►│ {evidence_id,         │    │ (已有)           │
│                  │    │  source_type: ann,    │    │                  │
│announcements     │    │  text_excerpt,        │    │ Worker 消费 job  │
│(irm:*) ──────────┼───►│  extraction_status:   │───►│ → 实体/关系      │
│                  │    │   pending, ...}       │    │ → 向量           │
├──────────────────┤    ├──────────────────────┤    └──────────────────┘
│evidence_tracking │    │ kg_extraction_jobs    │
│(新增 PG 追踪表)  │    │ {job_id, status, ...} │
└──────────────────┘    └──────────────────────┘
```

## Chunk Size 决策

**公告和互动易不分块**，理由：
- 公告 title 平均 26 字符、83% < 40 字符 — 远小于任何合理 chunk size
- 互动易问题平均 63 字符 — 也是一条完整语义单元
- 分块会导致语义碎片化（一条公告标题拆成多个 chunk 没意义）

**研报后续阶段**才需要 chunker，届时根据实际 PDF 文本长度再定 chunk size。

## evidence_tracking 表设计 (PostgreSQL)

```sql
CREATE TABLE IF NOT EXISTS evidence_tracking (
    id SERIAL PRIMARY KEY,
    source_table VARCHAR(100) NOT NULL,       -- 'minishare_announcements' | 'announcements'
    source_id INTEGER NOT NULL,               -- 源表主键
    evidence_id VARCHAR(100) NOT NULL,        -- MongoDB evidence_id (EV:sha256...)
    chunk_index INTEGER DEFAULT 0,            -- 分块序号（公告/IRM 始终为 0）
    extraction_status VARCHAR(20) DEFAULT 'pending',  -- pending|running|done|failed
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now(),
    UNIQUE(source_table, source_id, chunk_index),
    UNIQUE(evidence_id)
);
CREATE INDEX IF NOT EXISTS idx_et_status ON evidence_tracking(extraction_status);
CREATE INDEX IF NOT EXISTS idx_et_source ON evidence_tracking(source_table, source_id);
```

## 数据流

1. **Builder**: 读 PostgreSQL → 构造 EvidenceInput → EvidenceService.upsert → MongoDB
2. **Tracker**: 同时写 evidence_tracking 表，记录 source → evidence 映射
3. **Worker** (已有): claim_next_job → process → mark_job_done → 同步更新 tracking 状态

## 不包含的内容

- 研报 PDF 解析和分块（后续阶段）
- 新的 chunk size 参数（短文本不需要）
- API 端点（先用脚本/命令行触发）
