# QingShuiTouYan

这是一套围绕知识构建层和投研检索的后端工程。

## 当前重点

当前实现的是 `Phase 08` 的 Evidence-first 知识构建层管线：

- `Raw Source -> Parser -> Chunker -> Evidence`
- `Evidence -> 异步 Extraction Jobs`
- `Extraction Jobs -> Entity / Relation / StructuredFact`
- `Evidence chunk / 实体 / 关系 -> Qdrant 向量索引`

知识层只保存事实和证据，不写入买卖建议、预期差判断或其他投资结论。

## 主要模块

- `backend/app/knowledge/evidence.py`: Evidence 与 Job 的稳定 ID、状态和输入结构
- `backend/app/knowledge/evidence_service.py`: MongoDB 持久化与 job 调度
- `backend/app/knowledge/evidence_worker.py`: Evidence 异步消费 worker
- `backend/app/knowledge/structured_fact_service.py`: 结构化事实写入
- `backend/app/knowledge/vector_client.py`: Qdrant 向量写入与检索

## 运行

后端入口在 `backend/` 下。常见命令：

```bash
python backend/scripts/evidence_extraction_worker.py --once --limit 0
python -m pytest backend/tests/test_evidence_service.py backend/tests/test_evidence_builders.py backend/tests/test_evidence_worker.py -q
```

## 说明

这个仓库的知识构建层采用幂等写入：

- Evidence ID 稳定
- Job ID 稳定
- StructuredFact 以 `evidence_id` 追溯
- 向量写入按固定 `collection` 组织
