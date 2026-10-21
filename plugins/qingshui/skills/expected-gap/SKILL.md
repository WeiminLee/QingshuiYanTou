---
name: expected-gap
description: "预期差结论——先写下表面句再删掉；用开放算子问原理、拆因、供给、传导、证伪，清单不封闭；三点齐全时附 a = d2 - d1"
version: 1.4.0
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
1. `mcp__qingshui_data__data_readiness`（**必调**；degraded 时仍可出**弱结论**，须标明依据强度）
2. `mcp__qingshui_data__compare_metric(dimension, scope=…)` — 横比主证据
3. `mcp__qingshui_data__pull_history(subject, dimension=…)` — 时间线递进/变化。加速度另调 `metric_trend`，只读它返回的 `acceleration`，不要对时间线心算。
4. `mcp__qingshui_data__fetch_evidence(EV:…)` — 结论必须能落到证据
5. `mcp__qingshui_data__semantic_search` — 仅冷启动 / 补漏，不能替代 compare

行情辅助：`mcp__qingshui_data__get_kline` / `mcp__qingshui_data__get_stock_profile` 按需。
大盘复盘用 `mcp__qingshui_data__get_market_snapshot(trade_date=YYYYMMDD)`：涨跌家数、两市成交额（`amount_yi` 为亿元）、主要指数收盘。指数自身的 K 线仍走 `get_kline`。不要用个股 K 线代替指数。

> 21 个 `mcp__qingshui_data__*` 工具在**首轮请求**即已挂载（含 `data_readiness`）。禁止以「工具未暴露 / 不可用」跳过必调工具。

## 二阶导（用户可见的结论）
开放信息、新闻表面、水平值、上台阶、环比都是表面句。先写下表面句，是为了删掉它。结论只留删完之后、且能落到 `EV:` 的句子。
用算子往下问。没有证据的跳过，不许凑满。清单不封闭：证据指向清单外的一层，照写，并说明它相对表面句新在哪里。
- 加速度：d1 = y2 - y1，d2 = y3 - y2，a = d2 - d1。`metric_trend` 返回的 `acceleration` 已给出 d1、d2、a。用这个字段，不要心算。`status` 不是 `ok` 时写「二阶导不可计算」。点数不足只说明加速度算不出，继续问别的算子。
- 拆因：价、量、结构、一次性。拆不开，就不要把比率升降当结论。
- 原理：哪一个约束变了。
- 传导与时滞，再问「然后呢」。
- 供给响应：资本开支、进入、退出。需求叙事谁都会说。
- 言数不符：措辞和数字谁先变。说明会、调研里和水位不一样的那一句归这里。
- 外部基准：这条序列自己的历史上，这种变化后来延续还是回头。
- 识别差：证据里有、水位里没有。行情只引用 `get_kline`。
- 反身：只有披露或行情表明价格、融资条件已经在改基本面时才写。
删句：去掉「变化的变化」之后仍然成立的句子，不进入结论。`history_findings` 里已有同一句，不复读。
没有新的一层是合格结论。不要为了填算子而编一句。此时不铺水平表。
证伪：下一档哪一个观测会让这句改号。写不出来就标「依据不足」，不升级成判断。
横比表和时间线放在依据里。

## 输出最低要求
- 结论段只留过了删句的句子；三个可比点齐全时写上 a = d2 - d1
- 点数不足时写明「二阶导不可计算」，结论不因此留空
- 每条判断带一句证伪，或标明「依据不足」
- 有新的一层时，依据里至少一张横比或时间线要点（主体 / 数值 / 期间）；没有新的一层时不铺水平表
- ≥1 个 `evidence_id`（`EV:…`）或明确说明工具返回缺失

## 与双轨评测
金标见 `backend/eval/expected_gap_cases_v2.json`。工具名以 bare name 断言（`mcp__qingshui_data__compare_metric` → `compare_metric`）。

## 判断沉淀
与 `divergence-mining` 的沉淀段对齐：分析前先 `mcp__qingshui_data__history_findings`。`write_finding` 只在过了删句、相对水位是新的、并且写得出证伪或标明依据不足时落笔。只复述表面句的，不落笔。

引用段必须在期间、指标口径（综合毛利率与扣非毛利率这类变体）、单位上支撑结论，对不上就不写 `write_finding`。主体、指标、期间或数值已经填好时走 `compare_metric` 和 `pull_history`。语义搜索只补原因和措辞，不用假想文档去对数字。
