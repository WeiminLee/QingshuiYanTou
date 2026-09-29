# 清水投研 · Agent 运行时硬切到 dsh（design）

- 日期：2026-09-29
- 状态：**Reviewer Approve（nits 已修）** → 进入 `writing-plans`；plan 批准前不开码
- 仓库：`QingshuiYanTou`（monorepo 落点已定）
- 对照：`MatDiscovery` 的挂载法（**只学形态，不搬 `plugins/matdiscovery`**）

---

## 1. 目标 / 非目标

### 目标

1. **产品主路径**改为 DeepSeek Harness（`dsh`）**web profile**；**`frontend/` 整树**与 LangChain/LangGraph Agent **退出主路径**（硬切）。
2. 在本仓以 **只读 `dsh/` submodule + 清水自有 Cordis 插件** 组合能力（对齐 MatDiscovery：不 fork harness）。
3. 投研检索 / 证据 / 行情等能力以 **tool + skill** 挂在清水插件上；批量与循环进 `scripts/`，闸门可脚本化验收。
4. LangChain 相关代码仅保留为 **短期回滚分支 / 目录归档**，不再被生产调度或默认入口引用。

### 非目标

1. **不**迁移或重写知识构建 / 采集管线（Evidence、ingestion jobs、pdf/link/vector worker、H 集群 chemagent）。
2. **不**把 `MatDiscovery/plugins/matdiscovery`（材料技能、FieldMat、alloy 等）拷进本仓。
3. **不** fork 或长期 patch `dsh/` 内核；需要的接线放 `plugins/core/` 或清水插件 + `patches/` overlay。
4. **不**在本波把 Neo4j/PG/Mongo/Qdrant 直连塞进浏览器或 Electron；插件侧默认经 **Knowledge HTTP API**（`X-API-Key`）访问云端事实层。
5. **不**在本 design 里做桌面 Electron 打包（若后续要对齐 dsh-desktop，另开 spec）。

---

## 2. Locked (2026-09-29 evening)

Tonight **vertical slice only** (not full P0 hard cutover). Locked for `writing-plans` / implementer:

| 项 | 今晚锁定 |
|---|---|
| 范围 | 可证明路径：鉴权后的 dsh web → `qingshui` 插件 → ≤2 Knowledge HTTP tools → 证据回包。**不**删 `frontend/`、**不**归档 LangChain、**不**上 `dsh-agent-rpc`、**不**迁满 P0 工具表 |
| Auth | **nginx basic auth** 护 dsh web 公网入口；Knowledge tools 继续 **`X-API-Key`**（与 worker 同源约定） |
| Tools | **仅** `semantic_search` + `fetch_evidence`（均经 Knowledge HTTP，插件不直连 DB）。**今晚不做 `resolve`**；若日后加 resolve，先抽到 `app.knowledge`，禁止从 Knowledge HTTP 调 `graph_navigator._search_entity_by_name` |
| LLM | **Boyue Gateway**（今晚硬目标）：`apiKeyEnv=OPENAI_API_KEY`，`baseURL=http://35.220.164.252:3888/v1`，模型 `deepseek-v4-flash`。密钥只进 gitignored `.env.dsh.local` / 云 `.env.dsh` |
| Deploy | **今晚 GRANTED**：云 `root@124.221.188.38:/home/lwm/code/QingShuiTouYan`；验收 = dsh headless 跑出硅片预期差报告（对齐 `docs/reports/2026-09-28-silicon-wafer-divergence-v2.md` 结构） |
| Tools | **预期差三件套** `compare_metric` / `metric_trend` / `rollup_metric` + `fetch_evidence`（经 Knowledge HTTP）；`semantic_search` 冷启动可选；`related_nodes`/`propagate_along` 传导面。禁止 Node 直连 DB |
| Shell | dsh web；**今晚保留 `frontend/`** |
| 会话 | 不迁移；dsh 新会话从零 |

完整硬切仍以本 design 正文决策表为准；今晚验收 = 上表 vertical slice，不等于 §9 全量清单。

---

## 2. 已锁定决策

| 决策 | 选择 |
|---|---|
| 产品壳 | **dsh web profile**；**`frontend/` 整树退役**（含非聊天页） |
| 仓库形态 | **本仓 monorepo**：加 `dsh/` submodule + `plugins/*` |
| 上线节奏 | **硬切**：dsh 成主聊天路径；LangChain 仅回滚 |
| 挂载法 | dsh 只读 + **清水自有** Cordis 插件；禁止搬 matdiscovery |
| 知识 / 采集 | **保留面**（见 §3.2）；不进「放弃前后端」砍刀 |
| dsh 部署落点 | **与 Knowledge API 同云机**跑 dsh web；插件打本机/内网 Knowledge（`X-API-Key`） |
| Vue 去留 | **`frontend/` 全量退役**；非聊天页亦不保留；日后经 dsh 再造 |
| 会话/报告 | **不迁移**；dsh 新会话从零；旧 task/报告归档或忽略 |
| 插件包名 | **`qingshui`** → `plugins/qingshui/` |
| dsh-agent-rpc | **本波不上**；web + qingshui 插件足够硬切 |

「放弃之前的前后端」在本 spec 中的精确定义：

- **放弃**：**整个 `frontend/`**（聊天 + Dashboard / Portfolio / Report / StockDetail / Login 等）、`backend/app/reasoning/langchain_agent/**` 主路径、面向 Agent 的 `/api/v1/agent/*` SSE 编排（可删或冻结）。
- **不放弃**：FastAPI 上的 Knowledge / 采集 / worker 契约、存储与调度、数据 pipeline。
- **鉴权**：Login 页随 `frontend/` 退役后，**云上 dsh web 对外鉴权**在 implementation plan 中落地（本 design 不另开闸门；不得变成无鉴权公网聊天）。

---

## 3. 两张清单（砍壳 vs 保留）

### 3.1 聊天壳清单（硬切 / 可退役）

| 项 | 现状 | 硬切后 |
|---|---|---|
| `frontend/`（聊天 + Dashboard/Portfolio/Report/StockDetail/Login…） | 主 UI | **整树退役**；归档/删目录在实现 plan 定；不留只读壳 |
| `backend/app/reasoning/langchain_agent/` | `run_lead_agent` / create_agent | 移出主路径；tag/branch 回滚 |
| `backend/app/reasoning/api/agent.py` | `/api/v1/agent/chat|stream|…` | 默认下线；回滚分支可暂留 |
| LangChain middleware 链 | clarification / compressor / … | 由 dsh + 插件策略替代或分期补齐 |
| 前端 SSE 事件映射 | `agent.js` ↔ SSE | 改由 dsh web 原生会话 / 事件 |

### 3.2 Knowledge / 采集保留面（不可误伤）

| 面 | 代表路径 / 契约 | 说明 |
|---|---|---|
| Knowledge HTTP | `/api/v1/knowledge/**`（entity/relation/kg/evidence/jobs/writes…） | H 集群 worker 与插件 tool 的共用边界 |
| 采集调度 | `data_pipeline/scheduler.py`、ingestion job queue | 云侧编排；含 IRM/cninfo drain |
| Worker 拉取 | `qingshui-*-worker`、chemagent GPU 服务 | 按 `AGENTS.md` 铁律 |
| 存储 | PG / Mongo / Neo4j / Qdrant / Redis | 事实与向量底座 |
| 运维脚本 | `backend/scripts/`、deploy/chemagent | 与聊天壳无关 |

**收档规则**：FastAPI 只允许收到「Knowledge + 采集 + 账号/运维所需最小 API」；**不是删库、不是把 Evidence 处理搬进 dsh 进程**。

---


### 3.3 Vue 全量退役（已钉）

- **决定**：`frontend/` **整树退役**（含 Dashboard / Portfolio / Report / StockDetail / Login / 聊天壳等），不再作为生产或默认入口。
- **需要时再造**：看板/个股/报告等能力若仍要，后续用 **dsh web 自定义页 / skill** 重建；本波不做 Vue 只读残留。
- **含义**：硬切后用户面只认云上 dsh web（+ 运维/Knowledge API，无浏览器壳）。

## 4. 目标架构

```text
┌─────────────────────────────────────────────────────────┐
│ QingshuiYanTou (monorepo)                               │
│  dsh/                    # submodule，只读 pin          │
│  plugins/core/           # 可选：harness 接线 adapter    │
│  plugins/qingshui/       # 投研能力 Cordis 插件（自有）  │
│    skills/               # 配方（编排说明，非新检索算法） │
│    src/                  # tool 注册、config、HTTP client │
│  patches/                # cordis.patch.yml overlay      │
│  backend/                # FastAPI：Knowledge + 采集保留 │
│  frontend/               # 退役（硬切后非主路径）         │
└─────────────────────────────────────────────────────────┘
         │ HTTPS + API Key（插件 tool）
         ▼
   云端 Knowledge API / 调度 / DB
         │
         ▼
   H 集群 chemagent workers（evidence 处理）
```

### 4.1 部署落点（已钉）

- **生产拓扑（铁律）**：真正对外服务只跑在 **云上（API / 调度 / dsh web / 存储）** 与 **chemagent（embedding + 抽取 + evidence workers）**。**禁止**任何常驻通道或生产路径依赖本地 Mac（与 `AGENTS.md`「联通铁律」一致）。
- **dsh web**：与 Knowledge API **同云机**；插件 tool 打本机/内网 Knowledge HTTP，不新开公网 DB 端口。
- **本地 Mac**：仅用于编码、git push、对齐 GitHub；**不是**运行时的一部分。本机临时起 dsh 只可作开发调试，不得写入生产依赖或运维手册主路径。
- **非目标**：本波不引入第三台专用 harness 机；不恢复 Mac 隧道。

运行入口（对齐 MatDiscovery 习惯，名称可微调）：

```sh
# 一次性：submodule + build（细节在 implementation plan）
pnpm dsh plugin --profile web add ./plugins/qingshui
OPENAI_API_KEY=… pnpm dsh --profile web
```

---

## 5. 插件边界（清水自有）

### 5.1 包名与职责

- **包名已钉**：`plugins/qingshui`（Cordis 包名 `qingshui`）。
- **承载**：投研 skills、调用 Knowledge/行情的 tools、web settings 里与投研相关的配置卡。
- **不承载**：材料发现、FieldMat、MatDiscovery 品牌与 bench 用例。

### 5.2 Tool vs Skill vs scripts/

沿用 MatDiscovery / CAPABILITY 分层精神（清水语境表述）：

| 层 | 放什么 | 示例 |
|---|---|---|
| **Tool（硬能力）** | 单次、可测、对 Knowledge API 或外部源的调用 | `semantic_search`、`fetch_evidence`、`get_stock_profile`、`get_irm` |
| **Skill（配方）** | 多步投研套路、引用与验收说明 | 「公司深挖」「互动易追踪」「公告事件时间线」 |
| **scripts/** | 循环 / 批处理 / 门禁（机器可跑） | 链接层回填、检索回归、skill `--selftest` 类检查 |

### 5.3 现有 LangChain `@tool` → 迁移映射（初版）

以下来自当前 `backend/app/reasoning/tools/**`，硬切时按优先级迁入插件（名字可保持稳定，便于对照）：

**P0（主路径投研检索）**

- `semantic_search`
- `fetch_evidence`
- `resolve` / `expand`（图谱导航）
- `pull_history` / `scan_dimension` / `lookup_products` / `lookup_players` / `backlinks`
- `get_announcement` / `get_research_report`
- `get_stock_profile` / `get_irm`

**P1（辅助）**

- `find_events` / `get_event_detail`
- `tavily_search` / `web_fetch`
- `present_chart`
- sandbox `ls` / `read_file` / `write_file`（若 dsh 已有文件系统能力则不重复造）

**P2 / 运行时改由 dsh 原生**

- `write_todos`、`task`、`AskUserQuestion` / `ask_clarification` — 优先用 dsh 会话 / HITL 原语，避免再实现一套 LangChain middleware。

实现约束：插件内 tool **默认 HTTP 调保留面 API**，不在 Node 插件里直连云端 DB 端口（与 chemagent「只走 Knowledge API」一致）。

### 5.4 本波不含 `dsh-agent-rpc`（已钉）

- 硬切只依赖云上 **dsh web** + `plugins/qingshui`。
- `plugins/core/dsh-agent-rpc` **本波不引入**；若未来需要非 web 宿主再单独立项。


---

## 6. 硬切与回滚

### 6.1 硬切定义（验收用语）

1. 默认文档 / README / 运维入口指向 `pnpm dsh --profile web`（或等价启动器）。
2. 生产与日常开发**不再**启动 Vue 聊天依赖的 Agent SSE 主路径。
3. `run_lead_agent` / LangChain `create_agent` **无**被默认进程 import 执行。
4. 新投研对话只经过 dsh web 会话。

### 6.2 回滚分支

- Git：保留含 LangChain 主路径的 tag / branch（例如切点前 `pre-dsh-cutover`）。
- 代码：可将 `langchain_agent/` 移至 `archive/` 或留在分支，但 **main 默认不挂载**。
- 数据：Knowledge DB 与会话存储策略在 plan 阶段单列（dsh 会话 vs 旧 task_id）；**禁止**回滚时要求重建 Evidence。

### 6.4 会话与报告（已钉）

- **不迁移**旧 Agent 会话 / `task_id` / 分析报告进入 dsh。
- dsh **新会话空间从零**；旧表可 DB 归档或只读忽略，**本波不做导入工具**。
- **Evidence / 知识库不受影响**（会话≠事实层）。
- 旧 `/api/v1/agent/*` 报告查询不作为硬切后的产品能力保留（与「不迁」一致；回滚分支另论）。

### 6.3 退役顺序（实现期遵循，本 spec 只定序）

1. Pin `dsh` submodule + 空壳 `plugins/qingshui` 可 `web` 启动。  
2. 迁 P0 tools（HTTP client + 契约测试）。  
3. 迁 1～N 个核心 skill；门禁脚本。  
4. 切换 README / 部署入口到 dsh web；下线 Vue Agent 入口。  
5. 归档 LangChain；FastAPI 路由表只留保留面。

---

## 7. 与 MatDiscovery 的同 / 异

| | MatDiscovery | 清水（本设计） |
|---|---|---|
| dsh submodule 只读 | ✓ | ✓ |
| 自有 Cordis 插件 | `plugins/matdiscovery` | **`plugins/qingshui`**（已钉） |
| 拷贝对方插件 | — | **禁止** |
| 领域 | 材料 / FieldMat | 投研 Evidence / 链接层 |
| 事实后端 | 工具包 / MCP / 本地 scripts | **现有 FastAPI Knowledge + 云存储** |
| 产品壳 | dsh web / desktop 路线 | **本波：dsh web**；desktop 另议 |

---

## 8. 风险

| 风险 | 缓解 |
|---|---|
| 硬切后 HITL/澄清/长任务体验回退 | P2 明确用 dsh 原语；缺能力则开 follow-up issue，不偷偷加回 LangChain |
| Tool 直连 DB 破坏安全边界 | 规范：插件只打 Knowledge HTTP；CI/审查拒绝对云 DB 的新连接串 |
| 误删 Knowledge 路由 | PR 清单强制对照 §3.2；Reviewer 验收项 |
| dsh pin 漂移 | submodule 锁 commit；升级另开变更 |
| `frontend/` 退役不彻底（残留路由/镜像） | 验收要求仓库与部署均无 Vue 默认入口；目录归档或删除按 plan |

---

## 9. 验收清单（Reviewer）

- [ ] 主路径无 LangChain/LangGraph 执行（默认入口与生产进程）。
- [ ] 产品壳为 dsh web；**`frontend/` 整树**已退役（含非聊天页），无 Vue 默认入口。
- [ ] 云上 dsh web **对外有鉴权**（Login 退役后不得裸奔公网）。
- [ ] 存在清水自有插件；**无** matdiscovery 插件目录/依赖。
- [ ] P0 投研 tools 经 Knowledge（或文档记载的）HTTP 契约可测。
- [ ] §3.2 保留面路由 / worker / 调度仍可用；无「删库式」FastAPI 收档。
- [ ] 回滚路径文档化（branch/tag + 不伤 Evidence）。
- [ ] 无旧会话强制迁移；产品不依赖旧 `task_id` 历史。
- [ ] `dsh/` 无业务 fork；改动仅 submodule pin / 官方升级流程。

---

## 10. Open questions（Reviewer 五项闸门 — 已全部钉死）

1. ~~插件包名~~ → **已钉**：`qingshui`（`plugins/qingshui/`）。  
2. ~~Vue 非聊天页~~ → **已钉**：整树退役；需要时经 dsh 再造（见 §3.3）。  
3. ~~会话/task_id/报告~~ → **已钉**：不迁移；dsh 从零（见 §6.4）。  
4. ~~dsh-agent-rpc~~ → **已钉**：本波不上（见决策日志）。  
5. ~~dsh 部署落点~~ → **已钉**：prod 同云机；dev 可本机打云 API（见 §4.1）。

---

## 11. 下一步

1. ~~Reviewer 终审~~ → **Approve（带 nits）**；nits 已于 2026-09-29 回写。  
2. 走 `writing-plans`（仍不动代码直到 plan 批准）。  
3. 开码第一刀：云上可起的 `dsh` pin + 空壳 `plugins/qingshui` + P0 一两个 Knowledge HTTP tool + **dsh web 鉴权**。

---

## 12. 指针

- 本仓铁律：`AGENTS.md`（云 = 存储调度；H = evidence 处理）
- 现 Agent 入口：`backend/app/reasoning/api/agent.py` → `langchain_agent.client.run_lead_agent`
- 现工具树：`backend/app/reasoning/tools/`
- 对照挂载法：`/Users/lwm/code/MatDiscovery/AGENTS.md`、`plugins/matdiscovery/`（只读参考）

---

## 13. 决策日志

| 时间 | 项 | 决定 |
|---|---|---|
| 2026-09-29 | 产品壳 | dsh web；**`frontend/` 整树**硬切退役 |
| 2026-09-29 | 仓库 | 本仓 monorepo + dsh submodule |
| 2026-09-29 | 节奏 | 硬切；LangChain 仅回滚 |
| 2026-09-29 | 部署落点 | **prod：dsh web 与 Knowledge API 同云机** |
| 2026-09-29 | 运行时拓扑 | **只云 + chemagent**；Mac 仅编码/GitHub，生产不依赖本机 |
