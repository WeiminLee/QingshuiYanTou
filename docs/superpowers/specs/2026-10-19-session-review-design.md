# 昨日复盘 · session-review 技能（第一版）

- 日期：2026-10-19
- 状态：已批准（2026-10-19 试用对话确认后实现）
- 仓库：`QingshuiYanTou`
- 决定：2026-10-19 试用对话。复盘对象是「最近一个已收盘交易日的市场结构，再落到主线里的少数主体」。做法是「先做技能，用现有只读工具」。

## 1. 目标

用户在本地 Agent（`http://127.0.0.1:8399`）说「复盘上个交易日」，或点空会话里的同名起步问题，得到一份六段复盘：

1. 交易日
2. 市场结构
3. 主线
4. 落到主体
5. 接着看
6. 依据与缺口

市场结构和成分涨幅对应该交易日。接着看只提出 1 到 3 个预期差问题，不在本稿展开预期差，不下买卖结论，不写判断台账。

## 2. 非目标

- 不新增 MCP 工具，不改 Knowledge API，不部署 chemagent。
- 不写 `write_finding` / `write_observation`。
- 不把复盘放进 11 案金标。
- 不做收盘后自动生成、逐只涨停名单、新闻工具、研报补齐。
- 不修改 `expected-gap` 与 `divergence-mining`。预期差仍由那两个技能在下一轮承担。

## 3. 取舍

| 做法 | 结论 |
|---|---|
| 技能 + 现有 22 个只读工具 | **本版**。当天可在 8399 试用。 |
| 聚合只读接口 | 不做。等试用证明模型漏调工具或口径不稳，再单独立项。 |
| 调度器每晚写固定复盘 | 不做。调整要动生产调度。 |

## 4. 工具事实（本版必须遵守）

`get_top_concepts` 的 `days` 下限是 2（`ConceptTopRequest.days` 为 `ge=2`）。`days=1` 会被拒绝。返回的 `items[].last_up_nums` 与 `last_pct_chg` 在聚合循环里被任意一行覆盖，不能当成「最近一个交易日的涨停家数 / 涨跌幅」。

因此主线不是单日涨停榜。技能调用 `get_top_concepts(days=2, top_n=5)`，正文写「最近两个有概念数据的交易日」，并列出返回的 `trade_dates`。概念行只使用 `concept_name`、`concept_code`、`total_score`、`appear_days`、`rank`。不引用 `last_up_nums` 和 `last_pct_chg`。

其余口径：

- 交易日 = `get_market_snapshot()` 空日期调用返回的 `trade_date`（`YYYYMMDD`）。不按日历昨天算。
- 市场结构用该快照的 `indices`（`name`、`close`、`pct_chg`）、`up`、`down`、`flat`、`amount_yi`。
- 只对排名第 1 的概念调用 `get_concept_stocks(concept_code, sort_by=pct_chg, limit=5)`。
- 成分涨幅是该接口的 `latest_trade_date` 与 `items[].pct_chg`。这是当日涨幅，不是涨停名单。若 `latest_trade_date` 与快照 `trade_date` 不同，两个日期都写出来。
- 公告：对涨幅前 2 名调用 `get_announcement(ts_code, start_date, end_date)`，起止都是快照 `trade_date`（8 位）。不足 2 名就对返回的那几名调用；0 名则该段写「没有」。
- 事件：对同一批名称调用 `find_events(query=股票名称, date_from, date_to, top_n=5)`。`query` 必填，日期用快照 `trade_date`（`YYYYMMDD` 或 `YYYY-MM-DD` 均可）。没有结果就写没有。

## 5. 技能契约

新文件 `plugins/qingshui/skills/session-review/SKILL.md`。工具名写法与 `expected-gap` 相同，使用 `mcp__qingshui_data__` 前缀加裸名。

触发语：`复盘上个交易日`、`昨日复盘`、`收盘复盘`。

调用顺序，未调用不得写对应段落：

1. `data_readiness`
2. `get_market_snapshot()`
3. `get_top_concepts(days=2, top_n=5)`
4. `get_concept_stocks`（仅第 1 名概念，`sort_by=pct_chg`，`limit=5`）
5. `get_announcement` 与 `find_events`（涨幅前 2 名）

输出固定这六个二级标题，顺序不变。某次调用失败或返回空时，该段写「缺失」或「没有」，其余段照常写。`data_readiness` 里 kline 或公告不是 fresh 时，仍按工具返回值写正文，并把状态写入「依据与缺口」。

接着看：1 到 3 个问题。每个问题的主体必须是本节已返回的股票名称或代码。没有公告和事件时，不编造毛利率、订单等维度，只问这只票有没有本日材料没覆盖的状态变化。不调用 `compare_metric`，不宣称存在或不存在预期差。

禁止：买卖、目标价、仓位；把成分涨幅或概念热度写成涨停名单；`write_finding`；`write_observation`。

## 6. 入口

`plugins/qingshui/src/client/ResearchStarts.tsx` 的 `RESEARCH_STARTS` 在现有三条之后增加 `复盘上个交易日`。空会话标题仍是「今天想看什么」。点按行为不变：填入输入框并发送。

页面加载的是已构建的 `plugins/qingshui/lib/client.js`。改起步文案后要构建插件，并重启 launchd 任务 `com.qingshui.dsh-web`，新按钮才会出现在 `8399`。技能目录由插件启动时挂上的 `qingshui-local` skill root 读取；重启后新技能才会进入技能列表。

## 7. 验证

- `plugins/qingshui/src/client/research-starts.test.ts` 断言 `RESEARCH_STARTS` 含原有三条和 `复盘上个交易日`。
- 同文件或相邻测试读取 `plugins/qingshui/skills/session-review/SKILL.md`，断言含 `data_readiness`、`get_market_snapshot`、`get_top_concepts(days=2, top_n=5)`、`get_concept_stocks`、`get_announcement`、`find_events`、禁止 `write_finding`，以及「不是涨停名单」。
- 构建并重启后，打开 `http://127.0.0.1:8399`，空会话能看见第四条，点开后回答含六个标题，且交易日等于快照的 `trade_date`。
- 不跑 `scripts/run-golden-eval.sh`。

## 8. 文件

| 文件 | 动作 |
|---|---|
| `plugins/qingshui/skills/session-review/SKILL.md` | 新增 |
| `plugins/qingshui/src/client/ResearchStarts.tsx` | 增加一条起步问题 |
| 插件内对应测试 | 新增或扩展，覆盖 §7 的两条断言 |
| `plugins/qingshui/lib/client.js` 及其 map | 构建产物 |

不改 `backend/`、`deploy/`、金标用例和 chemagent。
