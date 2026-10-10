# Harness 轨迹落盘（第一期）

## 目标字段（JSONL 一行一事）

| field | 说明 |
|---|---|
| `ts` | ISO8601 |
| `case_id` | 金标案 id（runner 注入） |
| `role` | `model` \| `tool` \| `system` |
| `name` | 工具 bare name 或模型 id |
| `args` | 工具入参（可截断） |
| `result_excerpt` | 工具/模型输出前 N 字符 |
| `latency_ms` | 可选 |
| `error` | 可选 |

## 现状（dsh pin `b150a551` / `dsh-v0.1.1-rc.2`）

第一期**无**稳定的公开 transcript 导出 API 可被评测 runner 依赖。因此：

1. **harness**：优先解析 dsh headless stdout / tool 事件日志；评测用 `--answer-file` 提供 `{answer, tools}`。
2. **无旧轨**：LangChain `/api/v1/agent/*` 已删除，不再对照 stream/report。
3. 缺口关闭条件：上游 dsh 提供 session transcript 导出后，补 `scripts/export_dsh_trace.mjs`。

切流门禁仍以金标 `judge_case` 为准，不以轨迹完整性阻断第一期。
