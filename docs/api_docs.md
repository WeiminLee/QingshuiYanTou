# 清水投研 · API 参考

> **权威来源**：运行时 `GET /openapi.json`（以及交互式 `GET /docs`）。
> 本文是人工维护的速查表，**与代码不一致时以 `openapi.json` 为准**。
> 最后核对：2026-10-28（`backend/app/main.py` 实际注册 66 条路由）。

## 1. 认证与通用约定

| 项 | 说明 |
|---|---|
| 鉴权 | Header `X-API-Key: <API_KEY>`；worker 侧写接口读 `KNOWLEDGE_API_KEY`，回落 `API_KEY` |
| 部署位置 | chemagent `127.0.0.1:8001`，只经 SSH 隧道访问；浏览器不直连，走插件 loopback 代理 |
| 错误格式 | `{"detail": "..."}`；接口层自定义错误为 `{"detail": {"code": "..."}}` |
| 时间 | 一律 ISO 8601（`YYYY-MM-DD` / 带时区的时间戳） |

模块划分：

- **Agent 只读面**：`/api/v1/knowledge/{search,metrics,agent,links,market,sources,ledger,documents}`——
  DeepSeek harness 经 Data MCP（22 工具）调用，**不注册写工具**。
- **Agent 写面**：`/api/v1/knowledge/ledger/{observation,finding}`，由插件在 HTTP 侧调用，
  用于把研究判断沉淀进台账。
- **Worker 面**：`/api/v1/knowledge/{jobs,evidence/jobs,evidence/upsert,link/upsert,vector/upsert,signal/{prior-lines,upsert},announcement/mark-stored}`，
  只给 chemagent 上的 worker 轮询领取，不对外。
- **运维/业务面**：`/api/v1/{signals,readiness,stocks}`，以及历史遗留的 `auth/users/account`。

## 2. 健康与就绪

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/health` | 进程健康检查，无需鉴权 |
| GET | `/api/v1/readiness` | 各数据源就绪度汇总（新鲜度/缺口） |
| GET | `/api/v1/readiness/{source}` | 单个数据源的就绪度明细 |

## 3. 知识检索与判断（Agent 读面）

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/v1/knowledge/search/semantic` | 语义检索 evidence（Qdrant + 路由） |
| POST | `/api/v1/knowledge/metrics/compare` | 跨主体/跨期指标对比 |
| POST | `/api/v1/knowledge/agent/compare_metric` | 单指标对比（含口径校验） |
| POST | `/api/v1/knowledge/agent/metric_trend` | 指标时间序列 |
| POST | `/api/v1/knowledge/agent/rollup_metric` | 按主体/概念聚合指标 |
| POST | `/api/v1/knowledge/agent/related_nodes` | 关联节点（产业链/概念） |
| POST | `/api/v1/knowledge/agent/propagate_along` | 沿链路传播推演 |

## 4. 源材料与链接层

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/v1/knowledge/sources/events` | 事件检索（按主体/时间/类型） |
| POST | `/api/v1/knowledge/sources/events/recent` | 最近事件流（插件资讯条） |
| POST | `/api/v1/knowledge/sources/event_detail` | 单事件详情 |
| POST | `/api/v1/knowledge/sources/announcement` | 公告查询 |
| POST | `/api/v1/knowledge/sources/irm` | 互动易问答查询（非法参数忽略并在 note 说明，不返回 422） |
| POST | `/api/v1/knowledge/links/lookup_products` | 产品 → 主体 |
| POST | `/api/v1/knowledge/links/lookup_players` | 环节 → 玩家 |
| POST | `/api/v1/knowledge/links/scan_dimension` | 按维度扫描产业链 |
| POST | `/api/v1/knowledge/links/backlinks` | 反向链接 |
| POST | `/api/v1/knowledge/links/history` | 链接变更历史（游标拉取） |

## 5. 判断台账（只写不删）

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/v1/knowledge/ledger/observation` | 记录观察（事实层） |
| POST | `/api/v1/knowledge/ledger/finding` | 记录判断（含 supports 证据锚点） |
| POST | `/api/v1/knowledge/ledger/search` | 检索判断 |
| POST | `/api/v1/knowledge/ledger/history` | 判断历史（游标） |
| POST | `/api/v1/knowledge/ledger/watermark` | 读取当前水位 |

## 6. 行情与概念

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/knowledge/market/kline` | 个股/指数 K 线 |
| GET | `/api/v1/knowledge/market/stock_profile` | 个股概况 |
| GET | `/api/v1/knowledge/market/snapshot` | 某交易日涨跌家数、成交额、主要指数（空日期取最新） |
| POST | `/api/v1/knowledge/market/concept_top` | 最近 N 日最强概念（指数衰减 + 涨停加成） |
| POST | `/api/v1/knowledge/market/concept_stocks` | 概念成分股 |
| POST | `/api/v1/knowledge/market/stock_concepts` | 个股所属概念 |
| GET | `/api/v1/stocks/search` | 股票名称/代码模糊搜索（插件选股用） |

## 7. 产物阅读器

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/knowledge/documents/{ann_id}` | 文档聚合：章节列表 + PDF 存在性（不返回正文；已生成时附 `summary` / `summary_updated_at`） |
| GET | `/api/v1/knowledge/documents/{ann_id}/pdf` | 原文 PDF 字节流，手写 Range（200/206/416） |

`ann_id` 类型不统一：老公告是 PG 整数，新采集是 `{ann_date}_{ts_code}_{标题}` 复合串，
服务端 int + str 双查。详见 `AGENTS.md` 2026-10-21 增量。

`summary` / `chapters[].summary` 由 `backend/scripts/summarize_documents.py` 用本地 GPU
批量生成（文档级 / 章节级；只含事实摘要，不写买卖/估值结论）；未生成时字段省略。

## 8. Worker 面（仅 chemagent 内部）

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/v1/knowledge/jobs/claim` | 领取 link/vector 作业 |
| POST | `/api/v1/knowledge/jobs/{job_id}/success` · `/failure` | 回写作业结果 |
| POST | `/api/v1/knowledge/evidence/jobs/claim` | 领取抽取作业 |
| POST | `/api/v1/knowledge/evidence/jobs/{job_id}/success` · `/failure` | 回写抽取结果 |
| GET | `/api/v1/knowledge/evidence/{evidence_id}` | 读取单条 evidence（插件大卡/阅读器） |
| POST | `/api/v1/knowledge/evidence/upsert` | 写入 evidence |
| POST | `/api/v1/knowledge/link/upsert` | 写入链接 |
| POST | `/api/v1/knowledge/vector/upsert` | 写入向量 |
| POST | `/api/v1/knowledge/signal/prior-lines` | 读取 signal 水位（worker 推导用） |
| POST | `/api/v1/knowledge/signal/upsert` | 写入 signal / propagation |
| POST | `/api/v1/knowledge/announcement/mark-stored` | PDF worker 回写 minishare 台账（file_path/download_status/evidence_at） |

## 9. 信号（预期差）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/signals` | 信号列表（按 scope 过滤） |
| GET | `/api/v1/signals/{signal_id}` | 单条信号 |
| POST | `/api/v1/signals/{signal_id}/status` | 更新信号状态 |
| POST | `/api/v1/signals/backfill/{evidence,events,catalysts}` | 回补信号 |

**只出研究结论，不产出买卖/仓位建议。**

## 10. 用户与持仓（历史遗留）

旧 Vue 前端时代的能力，当前**无在线客户端**；保留是因为尚未决定是否随产品形态一起退役。

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/v1/auth/login` | 主密码登录（设 `master_token` cookie） |
| POST | `/api/v1/auth/switch-user` | 切换身份（设 `user_id` cookie） |
| GET | `/api/v1/auth/whoami` | 当前身份 |
| POST | `/api/v1/auth/logout` | 登出 |
| GET | `/api/v1/users` | 可选身份列表 |
| GET/POST | `/api/v1/account/portfolio` | 持仓列表 / 添加 |
| DELETE | `/api/v1/account/portfolio/{ts_code}` | 删除持仓 |
| GET | `/api/v1/account/stocks/search` | 股票搜索 |

## 11. 2026-10-21 已下线端点

以下路由已删除（零客户端调用），**不要按旧文档调用**：

`/api/v1/information/*`、`/api/v1/data/*`、`/api/v1/monitor/*`、`/api/v1/logs/*`、
`/api/v1/sync/*`、`/api/v1/concept/*`（3 个查询函数保留在模块内，经
`/api/v1/knowledge/market/*` 暴露）、`/api/v1/stocks/{list,watchlist,package,material,kline,capital-flow,{ts_code}}`。

手工触发同步、查任务日志改走：scheduler 容器日志、`/api/v1/readiness`、Data MCP。
