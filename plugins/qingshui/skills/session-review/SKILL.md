---
name: session-review
description: "昨日复盘——最近一个已收盘交易日的市场结构，再落到主线概念里涨幅靠前的成分；先工具后正文，禁止买卖结论和判断沉淀"
version: 1.1.0
metadata:
  tags: [复盘, 市场结构, get_market_snapshot]
  category: finance
---

# 昨日复盘（session-review）

## 触发

用户说「复盘上个交易日」「昨日复盘」或「收盘复盘」。

## 硬禁令

- 禁止买卖、目标价、仓位。
- 禁止 write_finding。
- 禁止 write_observation。
- 禁止调用 `compare_metric`。禁止宣称存在或不存在预期差。
- 成分涨幅不是涨停名单。禁止把概念热度写成涨停名单。
- 不引用 last_up_nums。不引用 last_pct_chg。这两项不能写成昨日涨停家数或昨日涨跌幅。
- `get_top_concepts` 的 days 下限是 2。不要传 `days=1`。
- 工具返回空写「没有」。调用失败写「缺失」。
- 未调用对应工具，不得写该段。

## 工具顺序

第 1 到第 5 步的工具名使用 `mcp__qingshui_data__` 前缀。`web_search` 和 `web_fetch` 没有这个前缀。

1. `mcp__qingshui_data__data_readiness`
2. `mcp__qingshui_data__get_market_snapshot`，不传 `trade_date`。返回的 `trade_date`（`YYYYMMDD`）是本篇交易日。不按日历昨天算。
3. `mcp__qingshui_data__get_top_concepts(days=2, top_n=5)`
4. 只对 `rank` 为 1 的概念调用 `mcp__qingshui_data__get_concept_stocks`，参数 `sort_by=pct_chg`，`limit=5`。
5. 取涨幅前 2 名。不足 2 名就对返回的那几名调用；0 名则公告和事件写「没有」。对每一名调用：
   - `mcp__qingshui_data__get_announcement`，`start_date` 与 `end_date` 都是快照 `trade_date`
   - `mcp__qingshui_data__find_events`，`query` 为股票名称，`date_from` 与 `date_to` 都是快照 `trade_date`，`top_n=5`。query 必填。
6. `web_search`。`queries` 只放一条：第 1 名概念名称，加上快照交易日（写成 `YYYY-MM-DD`）。这是公开新闻资讯。没有第 1 名概念就跳过，主线里的公开新闻写「没有」。

## 输出

固定以下六个二级标题，顺序不变：

## 交易日

写明快照 `trade_date`。

## 市场结构

指数写 `name`、`close`、`pct_chg`。另写 `up`、`down`、`flat`、`amount_yi`（亿元）。表后写一句读法：哪些指数的 `pct_chg` 为正、哪些为负，以及 `up` 和 `down` 谁更大。只用这些返回值。

## 主线

写「最近两个有概念数据的交易日」，并列出返回的 `trade_dates`。概念行只用 `concept_name`、`concept_code`、`total_score`、`appear_days`、`rank`。这不是单日涨停榜。`total_score` 为 0 的概念不进表；第 1 名即使为 0 也保留。`total_score` 写原值，不解释算法。

概念表之后写公开新闻。最多 3 条，每条写标题和链接，材料只来自 `web_search`。返回空写「没有」。这是网页资讯，不是 EV，也不是公告。要看其中一条正文，再用 `web_fetch`。

## 落到主体

只展开第 1 名概念里按涨幅排序的成分：名称、代码、`industry`、`pct_chg`。写明这是当日涨幅，不是涨停名单。写返回的 `stock_count`。`stock_count` ≥ 100 时，表下写「成分过宽」：前 5 名是大桶里按涨幅取出的票。某一行的 `industry` 与概念名称不是一类时，该行标「行业与概念不一致」。若成分接口的 `latest_trade_date` 与快照 `trade_date` 不同，两个日期都写出来。

引用事件时，只把快照交易日当天的句子写成当日。正文里更早的日期原样标出，不并进当日材料。

若事件写明的题材与第 1 名 `concept_name` 不是同一个名称，开头写明：热度榜是该概念；当日材料写的是事件里的题材。

## 接着看

1 到 3 个问题。每个问题的主体必须是第 5 步查过公告和事件的名称或代码。事件正文里出现、但第 5 步没查的名称，不做成问题；要提到就写「未查」。

有事件的主体，问题对着该事件里的事实问。公告和事件都为空的主体，问这只票有没有本日材料没覆盖的状态变化。多个问题各自跟着自己的材料，不复用同一句。不编造毛利率、订单等维度。不在本篇做预期差分析。

## 依据与缺口

列出已调用的工具。空和失败的用词见硬禁令。`data_readiness` 里 kline 或公告不是 fresh 时，仍按工具返回值写正文，并把状态写在这里。
