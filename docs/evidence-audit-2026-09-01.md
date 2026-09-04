# 公告 Evidence 数据质量审计（2026-09-01）

本次审计为只读核对，未删除或覆盖已有 Evidence。

## 当前统计

| 指标 | 数值 |
|---|---:|
| 公告 Evidence | 38,771 |
| 覆盖公告 source_id | 37,897 |
| 空文本 Evidence | 0 |
| 缺少 chunk_index | 0 |
| 重复 source_id + chunk_index 组 | 194 |
| 公告库中有 PDF 的公告 | 451,442 |

## 判断

- 现有 Evidence 未被清空，且包含历史数据；不能按“全量重建”假设处理。
- 194 组重复位置需要按 checksum/text 内容进一步归并，不能直接删除。
- 当前优先任务是补齐缺失公告 Evidence，而不是清空集合。
- IRM Evidence 不纳入 PDF 下载重建范围。

## 执行策略

1. 保留旧 Evidence。
2. 对缺失公告按 PDF 任务增量下载、解析和 upsert。
3. 对重复组按文本 checksum 归并，保留稳定 Evidence ID 和最新解析结果。
4. 每批处理后验证覆盖率、失败率和重复组数量。
