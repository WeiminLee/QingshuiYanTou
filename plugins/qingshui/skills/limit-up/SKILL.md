---
name: limit-up
description: "某只股票为什么涨停。先用 search_stock 定代码，再看本地日线、公告和事件。日线没有今天就写日线未入库。原因只写工具返回里的句子。"
version: 1.0.0
metadata:
  tags: [涨停, search_stock]
  category: finance
---

# 为什么涨停

## 触发

用户问某只股票「为什么涨停」「涨停原因」或「今天为什么涨」。

## 硬禁令

- 禁止买卖、目标价、仓位。
- 禁止 write_finding。禁止 write_observation。
- 禁止宣称存在或不存在预期差。
- 公司名用 `search_stock`。不要猜代码，也不要猜板块。不要用 `semantic_search` 找代码。
- 一轮之后就写。不要为了超级周期、概念成分、龙虎榜或历史高点再开检索。原文没有时，用事件标题和摘要作答，不要为了补一条 EV 再检索。
- `volume` 只写返回原值，不另标单位。成交额换算以 `get_kline` 工具说明为准。
- 工具返回空写「没有」。调用失败写「缺失」。`fetch_evidence` 返回 404 写「原文没有」。

## 工具顺序

`search_stock`、`web_search`、`web_fetch`、`anysearch` 没有 `mcp__qingshui_data__` 前缀。下面第 2 步和第 6 步的工具带这个前缀。

1. `search_stock`，`q` 为用户给的公司名或代码。名称完全一致的只有一条，就用那条 `ts_code`。否则列出 `ts_code`、`name`、`industry`，停下来，不要猜。
2. 定下代码后，同一轮调用：
   - `mcp__qingshui_data__data_readiness`
   - `mcp__qingshui_data__get_kline`：`end_date` 为用户说的今天（`YYYYMMDD`），`start_date` 约为今天往前 60 个自然日
   - `mcp__qingshui_data__get_announcement`：`start_date` 为今天往前 15 个自然日，`end_date` 为今天
   - `mcp__qingshui_data__find_events`：`query` 为 `search_stock` 返回的名称，`date_from` 与公告起始日相同，`date_to` 为今天，`top_n=5`。query 必填
3. 公告或事件已经写出原因，就进入输出。没有，再调用一次 `web_search`。`queries` 只放一条：公司名加「涨停」。
4. `web_search` 报错，立刻 `anysearch`，`command` 为 `search`，只传 `query`，不传 `domain`。`domain` 为 `general` 也按普通检索。这次不要先 `get_sub_domains`。
5. 正文最多再打开一页：`web_fetch` 或 `anysearch` 的 `extract`，二选一。
6. `mcp__qingshui_data__fetch_evidence` 最多一次，只取事件列表里已经给出的 `EV:`。404 写「原文没有」。标题和摘要仍可引用，不要写成已经取到的原文。

空日期的 `get_market_snapshot` 给出的是最近一个已收盘交易日。本问题不用它代替用户说的今天。

## 输出

固定以下五个二级标题，顺序不变。未调用对应工具，不得写该段里的数字。

## 代码

写 `ts_code`、名称、行业。代码只来自 `search_stock`。

## 涨停事实

本地日线最后一根的 `trade_date` 早于用户说的今天，写「日线未入库」，并写出这两天的日期。不要把上一根的涨跌写成今天的涨停。快讯里的涨停价、时间和跟涨名称可以写，标明是快讯。两个来源的涨停价不一致，两个数字和来源都写。

## 原因

只写公告、事件或那一页新闻里的原句。公司公告为空就写「公司公告没有」。同业名称只写快讯或事件里点名的。

## 推论

最多三句。工具原文已经说明原因，这里写「没有」。工具原文没有写出的资金切换、筹码、证伪、预期差，不要写进来。

## 缺口

列出已调用的工具。空和失败的用词见硬禁令。日线最后一根的日期写在这里。
