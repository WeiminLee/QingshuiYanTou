# Evidence Pipeline 设计文档

> 2026-06-16 | 知识构建层第一阶段：数据 → Evidence → 追踪

## 背景

PostgreSQL 已有 35 万公告 + 1 万研报 + 23 条互动易。Neo4j/Qdrant 为空。
需要将 PostgreSQL 源数据转为 MongoDB Evidence，再由 Worker 消费抽取到 KG。

## 数据特征分析

| 数据源 | 数量 | 文本特征 | Chunk 策略 |
|--------|------|----------|------------|
| 公告 (minishare_announcements) | 351,345 | PDF 正文 100-700 chars/页，1-10 页，有"一、二、三"章节标题 | 下载 PDF → 解析正文 → 按章节/段落分块 |
| 互动易 (announcements irm:) | 23 | 问题平均 63 字符 | 不分块，1 条 = 1 Evidence |
| 研报 (research_report_meta) | 10,170 | 需从 PDF 解析正文，几千字，URL 未入库 | 后续阶段 |

### 公告 PDF 实测

cninfo 无频率限制，10 个 PDF 全部 HTTP 200，0.1-0.2s/个。
正文格式清晰，pymupdf 解析正常。典型结构：

```
证券代码：000088  证券简称：盐田港  公告编号：2026-27
深圳市盐田港股份有限公司 2025 年度分红派息实施公告

一、股东会审议通过的权益分派方案等情况
...
二、本次实施的2025年度权益分派方案
...
三、分红派息日期
...
七、备查文件
```

## Chunk Size 决策

**公告**: 下载 PDF（cninfo 无限制）→ pymupdf 解析正文 → 按"一、二、三"等中文序号标题切分章节。每个章节作为一个 chunk。公告正文通常 500-2000 字符、3-7 个章节，chunk 大小自然落在 200-500 字符范围。

**互动易**: 1 条 Q&A = 1 Evidence，不分块。

**研报**: 后续阶段，先要补 URL 入库。

## 架构

```
PostgreSQL                    MongoDB                     Neo4j / Qdrant
┌──────────────────┐    ┌──────────────────────┐    ┌──────────────────┐
│minishare_        │    │ kg_evidence           │    │ KG Extractor     │
│announcements ────┼───►│ {evidence_id,         │    │ (已有)           │
│ source_url(PDF)  │    │  source_type: ann,    │    │                  │
│                  │    │  text_excerpt,        │    │ Worker 消费 job  │
│announcements     │    │  extraction_status:   │───►│ → 实体/关系      │
│(irm:*) ──────────┼───►│   pending, ...}       │    │ → 向量           │
│                  │    │                       │    │                  │
├──────────────────┤    ├──────────────────────┤    └──────────────────┘
│evidence_tracking │    │ kg_extraction_jobs    │
│(新增 PG 追踪表)  │    │ {job_id, status, ...} │
└──────────────────┘    └──────────────────────┘
```

## evidence_tracking 表设计 (PostgreSQL)

```sql
CREATE TABLE IF NOT EXISTS evidence_tracking (
    id SERIAL PRIMARY KEY,
    source_table VARCHAR(100) NOT NULL,
    source_id INTEGER NOT NULL,
    evidence_id VARCHAR(100) NOT NULL,
    chunk_index INTEGER DEFAULT 0,
    extraction_status VARCHAR(20) DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now(),
    UNIQUE(source_table, source_id, chunk_index),
    UNIQUE(evidence_id)
);
```

## 数据流

1. **下载**: 从 source_url 下载 PDF → pymupdf 解析正文
2. **分块**: 按中文序号标题（一、二、三）切分章节
3. **Builder**: 构造 EvidenceInput → EvidenceService.upsert → MongoDB
4. **Tracker**: 写 evidence_tracking 表，记录 source → evidence 映射
5. **Worker** (已有): claim_next_job → process → mark_job_done

## 不包含的内容

- 研报 PDF 下载和分块（后续阶段，需先补 URL）
- 批量 PDF 下载的并发控制（第一阶段单线程）
