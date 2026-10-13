# 清水投研 · Agent / 数据 MCP / DeepSeek Harness 解耦设计（双轨）

- 日期：2026-10-10
- 状态：**已批准（用户锁定 Approach C）** → 可进入 `writing-plans`
- 仓库：`QingshuiYanTou`
- 关联：
  - `docs/superpowers/specs/2026-09-29-dsh-agent-runtime-cutover-design.md`（dsh 硬切总纲；本文件在**切流策略**上改为双轨，其余边界对齐）
  - `docs/superpowers/plans/2026-09-29-dsh-vertical-slice.md`（当晚 vertical slice：≤2 Knowledge HTTP tools；本文件在其上扩展为 MCP 契约 + 评测对齐）
  - `AGENTS.md`（云端存储/调度 + chemagent 处理；**禁止**生产依赖本机 Mac 隧道）
- 作废对照：`docs/开发文档/13_云端知识底座与本机Agent解耦部署方案.md` 已于 2026-09-23 标注作废（半解耦 + 本机 Agent 常驻形态），**不得**再作为部署依据。

---

## 1. 背景与动机

当前投研 Agent（LangChain / `stream/report`）与云端数据构建层同仓、且大量工具**进程内直连** PG / Mongo / Neo4j / Qdrant。结果是：

1. Agent 运行时与数据拓扑耦合，本机/云端难以共用同一套推理入口。
2. 预期差主路径已验证（如 `compare_metric` 能出横比），但被 readiness 门禁、墙钟超时、embedding 通道抖动等运行时问题拖垮。
3. 2026-09-29 已锁定 DeepSeek Harness（`dsh`）方向与 Knowledge HTTP 边界，但当晚仅 vertical slice（`semantic_search` + `fetch_evidence`），且总纲倾向**硬切** Vue/LangChain。

用户于 2026-10-10 确认新路径：

> 解耦 Agent 与云端数据构建；云端做成**只读数据 MCP**；Agent 整栈重构成官方/社区 **DeepSeek harness**（工具循环、轨迹、评测）；**同一套 harness 本机与云端都能跑**，统一连数据 MCP；**Approach C：新旧双轨**，预期差评测对齐后再切流。

本设计把上述决议落成可实施边界，并与既有 dsh spec / vertical slice **对齐而非忽略**。

---

## 2. 目标

1. **数据面与推理面解耦**：云端继续承担存储、调度、Knowledge / 采集 API；Agent 不再依赖进程内 DB 直连作为主路径。
2. **只读数据 MCP（第一期）**：将投研查询能力以 MCP tools 暴露；协议稳定、可被本机与云端 harness 共用。
3. **DeepSeek harness 统一运行时**：采用官方/社区 dsh（工具调用循环 + 轨迹 + 评测），本机与云端同一镜像/同一插件包，配置指向同一数据 MCP。
4. **双轨并行（Approach C）**：旧 `stream/report` / LangChain Agent **原样保留**；新 harness 旁路接入；用同一批预期差 gold cases 对照，达标后再切默认流量。
5. **可验收**：切流条件写死（通过率、无回归、轨迹可回放），避免「感觉能用」式切换。

---

## 3. 非目标（第一期明确不做）

1. **不**经 MCP 暴露写路径 / 入队（evidence upsert、job claim、vector/link upsert、scheduler 触发等）。
2. **不**删除或归档旧 Agent（`backend/app/reasoning/langchain_agent/**`、`/api/v1/agent/*`、现有 Vue 聊天壳）。
3. **不**改变数据构建拓扑（云端 Mongo/PG/Qdrant/Neo4j/Redis + chemagent workers 的分工仍以 `AGENTS.md` 为准）。
4. **不**把 Neo4j/PG/Mongo/Qdrant 端口对公网或对 Node 插件直连。
5. **不**在本波完成 Vue 全量退役或 dsh 硬切验收清单（那是 2026-09-29 hard-cut 全文目标；本波用双轨取代「立刻硬切」）。
6. **不**引入第三台专用 harness 机；不恢复 Mac 作为生产联通中转。
7. **不** fork `dsh/` 内核；投研能力放清水自有插件（延续 `plugins/qingshui` 方向）。

---

## 4. 与既有规格的关系

| 文档 | 关系 |
|---|---|
| `2026-09-29-dsh-agent-runtime-cutover-design.md` | **继承**：dsh submodule、Cordis 插件 `qingshui`、Knowledge 保留面、工具命名映射、禁止插件直连 DB、LLM 走本仓 LiteLLM。**修订**：切流由「硬切」改为「双轨 → 评测对齐 → 切」；本机允许跑**同一套** harness 作开发/评测客户端（生产默认仍在云）。 |
| `2026-09-29-dsh-vertical-slice.md` | **继承并扩展**：当晚 ≤2 HTTP tools 是 MCP 落地的最小先证；本设计要求把 P0 查询工具补齐到 MCP，并加上轨迹/评测对照。vertical slice 未完成项（如 `POST .../search/semantic`）仍须完成或被 MCP 等价层覆盖。 |
| `AGENTS.md` | **不可违背**：生产联通不得依赖 Mac；chemagent 处理 evidence；云端只存取与编排。 |
| `docs/开发文档/13_…解耦部署方案.md` | **已作废**；其中「本机 Agent 常驻依赖云底座」的半解耦叙事不再使用。 |

决策一句话：**用 MCP 把「Knowledge 查询边界」产品化；用双轨代替立刻硬切；用预期差评测门禁决定何时废弃旧路径。**

---

## 5. 架构

```text
┌──────────────────────────────┐     ┌──────────────────────────────┐
│ 旧轨（保留）                  │     │ 新轨（第一期建设）              │
│ Vue + FastAPI Agent SSE      │     │ DeepSeek harness (dsh)        │
│ LangChain tools              │     │ 本机 或 云端，同一插件包         │
│ 进程内 PG/Mongo/Neo4j/Qdrant │     │ 只通过 Data MCP Client 调工具   │
└──────────────┬───────────────┘     └──────────────┬───────────────┘
               │ 旁路，互不打断                        │ MCP (stdio/SSE/HTTP)
               │                                     ▼
               │                       ┌─────────────────────────────┐
               │                       │ Data MCP Server（云端）       │
               │                       │  Phase1：只读查询 tools       │
               │                       └──────────────┬──────────────┘
               │                                      │
               │              ┌───────────────────────┼───────────────────────┐
               │              ▼                       ▼                       ▼
               │     薄 HTTP（优先补齐缺口）    既有 Knowledge HTTP      必要时装配层
               │     或直接复用 Python 服务      /api/v1/knowledge/**     （只读包装）
               └─────────────►│◄──────────────────────┘
                              ▼
                    云端存储与调度（不变）
                    PG / Mongo / Neo4j / Qdrant / Redis
                    scheduler + chemagent workers
```

### 5.1 部署落点

| 组件 | 落点 | 说明 |
|---|---|---|
| Data MCP Server | **云端**（与 Knowledge API 同机或同 VPC） | 唯一数据查询入口给新 harness |
| dsh harness（生产） | **云端**（可与 API 同机，127.0.0.1 + nginx） | 对齐 09-29 部署铁律 |
| dsh harness（开发/评测） | **本机也可** | 同一镜像/插件；只连云端 MCP；**不得**把本机写成生产依赖 |
| 旧 Agent | 云端现状不变 | 双轨期间继续服务 |
| chemagent workers | H 集群 | 不变 |

### 5.2 为什么是 MCP 而不仅是 Knowledge HTTP

- Knowledge HTTP 已是 chemagent / worker 契约；适合机器拉取与运维。
- MCP 面向 **Agent 工具循环**：统一 schema、宿主无关（本机 CLI / 云端 web）、天然带工具发现与轨迹挂钩。
- 实现上 **MCP 应薄**：优先委托已有 Knowledge HTTP；对尚无 HTTP 的 Agent 工具，先补薄只读 HTTP 或在 MCP server 内同仓调用 Python 查询层（仍部署在云端，不把 DB 暴露给客户端）。

---

## 6. 现状缺口（必须写进计划）

### 6.1 工具实现形态

当前 `backend/app/reasoning/registry/config.yaml` 中的业务工具，绝大多数是 LangChain `@tool`，在 Agent 进程内访问存储：

| 类别 | 代表工具 | 现状访问方式 | Knowledge HTTP |
|---|---|---|---|
| 证据 | `fetch_evidence` | 进程内 `EvidenceService` → Mongo | **已有** `GET /api/v1/knowledge/evidence/{evidence_id}` |
| 语义检索 | `semantic_search` | 进程内 `vector_client` → Qdrant + embedding | **无**（vertical slice 已规划 `POST /api/v1/knowledge/search/semantic`，需落地） |
| 链接/指标 | `compare_metric` / `rollup_metric` / `metric_trend` / `pull_history` / `scan_dimension` / `lookup_products` / `lookup_players` / `backlinks` | 进程内 PG linklayer | **无** |
| 图谱导航 | `resolve` / `expand` / `neo4j_*` | 进程内 Neo4j | 部分实体/关系 API 存在，**不等价**于现工具语义 |
| 行情 | `get_kline` / `get_concept_hot` / `get_market_breadth` / `find_events` / `get_event_detail` | 进程内 PG/服务 | 监控/概念等有零散 API，**未按 Agent 工具契约暴露** |
| 财务/互动 | `get_stock_profile` / `get_irm` | 进程内 | **无对等 Agent 契约** |
| 公告/研报 | `get_announcement` / `get_research_report` | 进程内 | **无对等 Agent 契约** |
| Worker 写入 | — | — | 有 upsert/claim；**第一期 MCP 禁止包装为 Agent 可写工具** |

结论：**MCP 不能假设「HTTP 已齐」**。第一期交付必须显式包含「补薄只读 HTTP **或** MCP server 同仓只读装配」二选一（可按工具混用），并保持工具**对外名称**与现 Agent 一致，便于评测对照。

### 6.2 近期实跑暴露的运行时风险（新轨必须规避）

- **Embedding 通道**：语义检索依赖 chemagent `23456`；云端历史 `11434` / 双跳隧道不可作为生产依赖。
- **Readiness 门禁**：过严会直接掐死预期差结论；新轨应支持 `ready | degraded | blocked` 分级（degraded 可出结论但降权），与旧轨热修方向一致。
- **墙钟超时**：旧轨 150s 过短；新轨默认预算需按预期差多工具循环重估（实跑约 5min 量级可完成一条 case）。

---

## 7. 第一期 MCP 工具清单（草图）

命名与现 `registry/config.yaml` / `@tool` **对齐**，便于旧案重放。

### 7.1 P0（第一期必交付）

| MCP tool | 对齐现工具 | 数据源 | 备注 |
|---|---|---|---|
| `fetch_evidence` | 同名 | Mongo evidence | 直接映射已有 GET；注意正文截断策略与旧工具一致（约 8k 字符） |
| `semantic_search` | 同名 | Qdrant + embedding | 需先有 HTTP 或 MCP 内装配；embedding 只打 chemagent 稳定地址 |
| `compare_metric` | 同名 | PG links/keywords | 预期差横比主路；**优先补 HTTP** |
| `pull_history` | 同名 | PG linklayer | 时间线 |
| `lookup_players` / `lookup_products` | 同名 | PG | 标的/产品定位 |
| `get_kline` | 同名 | PG kline | 行情只读 |
| `get_stock_profile` | 同名 | PG/画像 | 基础画像 |
| `data_readiness`（可选新名） | 现 readiness API | readiness | 供 harness 在开写结论前感知 stale/degraded |

### 7.2 P0.5（第一期强烈建议，评测用得到）

| MCP tool | 对齐现工具 | 说明 |
|---|---|---|
| `rollup_metric` / `metric_trend` | 同名 | 与 `compare_metric` 同属预期差三件套 |
| `scan_dimension` / `backlinks` | 同名 | 证据溯源与维度扫描 |
| `get_announcement` / `get_irm` | 同名 | 公告与互动易 |
| `find_events` / `get_event_detail` | 同名 | 事件层；注意旧实现曾有事件循环问题，装配层需用隔离 runner |

### 7.3 明确排除（第一期）

- 一切 `write_*`、job claim/success/failure、vector/link upsert。
- `tavily_search` / `web_fetch`（外部网搜；可第二期作 harness 本地工具，不一定进数据 MCP）。
- sandbox 文件工具、HITL/`AskUserQuestion`（属 harness 运行时，不属数据 MCP）。
- `neo4j_*` 全量（等 P0 评测过后再纳入，避免第一期范围膨胀）。

### 7.4 MCP 传输与鉴权

- 传输：优先 **Streamable HTTP / SSE**（便于本机与云端远程连同一 server）；stdio 仅作同机调试。
- 鉴权：复用 Knowledge 约定 **`X-API-Key`**（`settings.knowledge_api_key or settings.api_key`）；公网入口另加 nginx 层（与 dsh web basic auth 可分立）。
- 超时与分页：每个 tool 声明 `timeout_ms` 与结果大小上限；超限返回可续取句柄或截断说明（对齐旧 `BudgetEnforcer` 精神，实现可简化）。

---

## 8. Harness 放置与形态

### 8.1 运行时

- **内核**：DeepSeek 官方/社区 harness（`dsh`），以 **git submodule 只读 pin** 接入（延续 09-29 pin 策略；具体 commit 在 implementation plan 锁定）。
- **插件**：`plugins/qingshui`（Cordis）——注册 MCP client 或「MCP↔defineTool」桥，承载投研 skills（预期差挖掘等）。
- **LLM**：本仓 LiteLLM（`LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL`），默认与 backend Settings 对齐；**不**绑 MatDiscovery Boyue / memtensor。

### 8.2 双端同一套

| 环境 | 行为 |
|---|---|
| 云端 | 生产入口；连本机回环或内网 Data MCP |
| 本机 | 开发与评测；连云端 Data MCP（TLS + API Key） |
| 配置 | 同一 `cordis.patch.yml` / env 模板，仅 `MCP_BASE_URL` 等端点不同 |

### 8.3 轨迹与评测钩子

Harness 必须落盘（或可导出）：

1. **轨迹**：每轮模型消息、tool 调用名/参数、tool 结果摘要、耗时、错误。
2. **结论工件**：最终报告正文 +（若有）结构化 `conclusions[]`；第一期允许正文优先、结构字段后补，但评测脚本要有稳定抽取规则。
3. **对照 ID**：同一 `case_id` 在旧轨与新轨各跑一次，共享金标期望。

---

## 9. 评测与切流标准

### 9.1 金标集

以现有预期差 / gold cases 为基线（至少覆盖已实跑类型）：

- 单标的指标横比（如硅片毛利、中晶相关毛利案）
- 需要 `pull_history` + `compare_metric` 组合的时间线案
- readiness=degraded 仍应产出「有依据的弱结论」的案

具体 case 文件路径与断言在 implementation plan 中钉死；本 design 要求**新旧共用同一断言脚本**。

### 9.2 通过定义（切流门禁）

同时满足才允许把默认产品路径切到新 harness：

1. **通过率**：新轨在金标集上通过率 **≥ 旧轨**（按同一断言）。
2. **无关键回归**：旧轨已通过的 case，新轨不得无故失败（允许标注「旧轨假阳性」并双方更新金标）。
3. **轨迹完备**：失败 case 可仅凭轨迹定位到 tool/MCP/模型哪一层。
4. **依赖健康**：`semantic_search` 所依赖 embedding 在 chemagent 稳定可达；无 Mac 隧道。
5. **双轨观察期**：建议至少连续 N 次定时评测（N 在 plan 中钉，建议 ≥3 次或覆盖 ≥1 个交易日）无回退。

未达标前：**默认流量仍走旧 `stream/report`**；新轨仅显式入口 / 内部评测使用。

### 9.3 与 09-29「硬切验收」的关系

09-29 §9 硬切清单（退役 `frontend/`、归档 LangChain 等）**顺延**到本门禁之后的单独 cutover plan，不在第一期 MCP 交付内宣称完成。

---

## 10. 风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| Embedding 不稳 / 地址漂移 | `semantic_search` 全挂，语义案失败 | MCP 健康检查；只配置 chemagent 稳定 endpoint；失败时明确 `data_status=unavailable`，结构化工具仍可用 |
| Readiness 过严 | 有数却无结论 | MCP/harness 统一 degraded 语义；评测区分 blocked vs degraded |
| HTTP 缺口大 | 第一期拖期 | 按 P0 表逐个补；允许 MCP server 同仓调用 Python 查询层作过渡，但**客户端仍只见 MCP** |
| 双轨双维护 | 修 bug 修两遍 | 查询逻辑下沉到 `app.knowledge` / HTTP，旧 `@tool` 与 MCP 共后台；禁止在插件里复制 SQL |
| 本机可跑被误当成生产 | 违反 AGENTS 联通铁律 | 文档与 compose 标明 profile=`dev-eval`；生产 runbook 只写云端 |
| 工具语义漂移 | 评测不可比 | 名称与主参数保持与旧 `@tool` 一致；变更走版本字段 |
| `find_events` 事件循环类 bug | 工具偶发失败 | 装配层统一 async runner；单测覆盖 |
| 结论结构化为空（`conclusions[]`） | 自动断言弱 | 第一期以正文关键断言为主，并行补结构输出 |

---

## 11. 迁移步骤（建议顺序）

1. **补齐只读查询缺口（云端）**  
   - 落地 `POST /api/v1/knowledge/search/semantic`（vertical slice Task 3）。  
   - 为 `compare_metric` / `pull_history` /（建议）`lookup_*` 增加薄只读 HTTP，或确认由 MCP server 同仓调用。  
   - 回归：HTTP 层单测不经过 LangChain。

2. **实现 Data MCP Server（只读）**  
   - 包装 P0 工具；鉴权、超时、截断、readiness 元数据。  
   - 与 chemagent **隔离**：MCP 不承担抽取算力。

3. **接入 dsh harness + `plugins/qingshui`**  
   - 延续 09-29 submodule/插件骨架；工具改为 MCP client 调用，而非进程内 DB。  
   - 本机与云端用同一包，不同 `MCP_BASE_URL`。

4. **轨迹 + 评测脚手架**  
   - case runner：旧轨 API vs 新轨 harness；输出对比报告。  
   - 先跑通 09-29 vertical slice 两工具，再扩到 `compare_metric` 预期差案。

5. **双轨观察**  
   - 旧轨默认；新轨评测入口；修 MCP/装配层直至门禁达标。

6. **切流（另开 cutover plan）**  
   - 达标后切换默认入口；再处理 Vue/LangChain 退役（回承 09-29 硬切清单）。

回滚：随时关掉新入口即可；MCP 与 harness 不写入构建队列，对数据面无破坏性。

---

## 12. 开放问题

1. **MCP server 实现语言**：Python（同仓 FastAPI 旁路 / mcp SDK）还是 Node（贴 dsh 插件）？倾向 Python 同仓复用查询层，Node 只做 client——需在 plan 锁定。  
2. **`compare_metric` 等是否必须先 HTTP**：纯 MCP 内装配更快，但 chemagent/其他非 MCP 客户端无法复用；是否规定「凡 P0 必须有 HTTP」？  
3. **金标 case 清单与断言强度**：正文关键词 vs 结构化字段 vs 数值表比对，第一期以哪级为准？  
4. **dsh submodule pin**：继续 `dsh-v0.1.1-rc.2` 还是跟随上游更新？  
5. **本机 harness 是否允许缓存 embedding 代理**：默认禁止；若开发体验差，是否提供**可选**本地 mock MCP（假数据）而非真连生产库？  
6. **旧轨热修（degraded readiness、超时、embedding）是否回灌主仓镜像**：与新轨并行，避免双轨期间旧入口回退。  
7. **第二期是否把网搜类工具放进 MCP 还是 harness 本地**：保持数据 MCP「只读事实层」纯度更有利于边界清晰。

---

## 13. 验收清单（本 design 完成态）

- [ ] P0 MCP tools 可在本机 harness 与云端 harness 各调用成功（同一 API Key 体系）。  
- [ ] `fetch_evidence` / `semantic_search` / `compare_metric` / 至少一种行情工具有自动化测试。  
- [ ] 新旧轨对比 runner 能输出金标通过率。  
- [ ] 文档与 runbook 明确：生产不依赖 Mac；doc 13 不作废引用。  
- [ ] 切流门禁条文被实现计划引用，无「感觉对齐」模糊词。

---

## 14. 下一步

1. Owner 确认开放问题中的实现语言与「P0 是否强制 HTTP」。  
2. 开 `docs/superpowers/plans/2026-10-10-agent-mcp-deepseek-harness.md`（implementation plan），按 §11 拆任务。  
3. 优先承接并完成 vertical slice 未竟的 semantic HTTP，避免 MCP 对 Qdrant 直连诱惑。

---

## 15. 决策日志

| 日期 | 决策 |
|---|---|
| 2026-10-10 | Approach **C** 双轨；评测对齐再切 |
| 2026-10-10 | DeepSeek **官方/社区 harness**（工具循环 + 轨迹 + 评测） |
| 2026-10-10 | 本机与云端 **同一套 harness**，统一连数据 MCP |
| 2026-10-10 | 第一期 MCP **只读**：evidence、语义检索、`compare_metric`、行情等查询 |
| 2026-10-10 | 不做：MCP 写/入队、删旧 Agent、改数据构建拓扑 |
| 2026-10-10 | 与 09-29 dsh design / vertical slice **对齐并修订切流策略**；doc 13 维持作废 |
