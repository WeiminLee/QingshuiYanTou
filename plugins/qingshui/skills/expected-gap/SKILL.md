---
name: expected-gap
description: "预期差结论——先工具后措辞；优先 compare_metric → pull_history → fetch_evidence，禁止无工具空喊预期差"
version: 1.0.0
metadata:
  tags: [预期差, compare_metric, 双轨评测]
  category: finance
---

# 预期差（Expected Gap）— 工具优先

与 `divergence-mining` 同族；本 skill 强调**评测可对齐**的最短路径与硬禁令。

## 硬禁令
- **禁止**在未调用任何只读数据工具时输出「存在/不存在预期差」。
- **禁止**把「实际值 − 卖方一致预期」当作默认定义（除非用户明确要求共识差）。
- period / 单位不一致时，**不得**直接横比排名。

## 推荐工具顺序（P0 Data MCP / Knowledge HTTP 同名）
1. `data_readiness`（可选，degraded 时仍可出**弱结论**，须标明依据强度）
2. `compare_metric(dimension, scope=…)` — 横比主证据
3. `pull_history(subject, dimension=…)` — 时间线递进/变化
4. `fetch_evidence(EV:…)` — 结论必须能落到证据
5. `semantic_search` — 仅冷启动 / 补漏，不能替代 compare

行情辅助：`get_kline` / `get_stock_profile` 按需。

## 输出最低要求
- 明确回答是否存在预期差（或「依据不足」）
- 至少一张横比或时间线要点（主体 / 数值 / 期间）
- ≥1 个 `evidence_id`（`EV:…`）或明确说明工具返回缺失

## 与双轨评测
金标见 `backend/eval/expected_gap_cases_v1.json`。工具名以 bare name 断言（`mcp__qingshui_data__compare_metric` → `compare_metric`）。
