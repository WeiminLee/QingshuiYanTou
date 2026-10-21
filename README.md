# QingShuiTouYan

QingShuiTouYan 是一个面向投研场景的知识构建与智能分析系统。系统目标不是直接给出交易指令，而是把公告、研报、互动易、行情、资讯等原始材料转化为可追溯、可检索、可推理的事实层知识，再由 Agent 在受控工具和上下文中完成研究辅助。

当前系统重点是后端知识构建层、混合检索、Agent 推理运行时，以及 Vue 前端交互界面。

## 系统定位

系统围绕三个核心问题设计：

- 投研材料来源复杂，必须先统一成稳定、可审计的证据对象。
- LLM 抽取结果必须能追溯回原文片段，不能直接沉淀不可解释结论。
- Agent 应基于事实、图谱、向量检索和工具调用进行研究辅助，而不是绕过知识层直接做投资判断。

因此，知识层只表达事实，不写入买入、卖出、错杀、预期差、补涨等投资结论。

## 总体架构

```text
Frontend
  Vue 3 / Vite / TDesign Chat / Element Plus
      |
      v
Backend API
  FastAPI / SSE / Tool APIs / Knowledge APIs
      |
      +--> Data Pipeline
      |      Tushare / Akshare / Baostock / 公告 / 研报 / 互动易
      |
      +--> Knowledge Construction
      |      Parser -> Chunker -> Evidence -> Extraction Jobs
      |      -> Link Layer (keyword / link) + Judgment Ledger -> Vector Index
      |
      +--> Agent Runtime（dsh + plugins/qingshui + Data MCP）
      |
      +--> Storage Layer
             PostgreSQL / MongoDB / Qdrant / Redis
```

### 组件分工

- `plugins/qingshui/`: dsh 插件（Agent 交互层 + 只读数据代理）。
- `backend/app/main.py`: FastAPI 应用入口，注册交易数据、知识、信号等 API。
- `backend/app/data_pipeline/`: 股票、行情、公告、研报、互动易等数据接入和调度。
- `backend/app/knowledge/`: 知识构建、链接层与判断台账、Evidence-first 管线、图谱与向量检索。
- `backend/app/mcp_data/`: 只读 Data MCP（dsh 插件的 MCP 服务端，薄包装 Knowledge HTTP）。
- `backend/scripts/`: 运维脚本、知识抽取脚本、worker、健康检查和批处理入口。
- `docs/`: 架构设计、知识图谱设计、Agent 设计和开发讨论记录。

## 核心设计原则

### Evidence-first

所有知识构建都先生成 Evidence。Evidence 是原始材料进入知识层后的最小审计锚点，包含原文片段、来源、发布时间、观察时间、置信度、校验和和状态。

```text
Raw Source
-> Parser
-> Chunker
-> Evidence
-> async Extraction Jobs
-> Link Layer + Judgment Ledger + Vector Index
```

### 事实和判断分离

知识层可以表达：

- 公司披露了什么事实
- 某产品是否量产
- 某客户是否导入
- 某订单是否排产
- 某财务指标是否低于预期
- 这些事实来自哪个 Evidence

知识层不表达：

- 是否买入或卖出
- 是否错杀
- 是否存在预期差机会
- 是否应该上调或下调推荐

### 幂等和可追溯

系统使用稳定 ID 减少重复写入：

- Evidence: `EV:` + SHA256
- Extraction Job: `JOB:` + SHA256
- Observation: `OB:` + SHA256（判断台账）
- Finding: `FD:` + SHA256（判断台账）

重复导入同一原文片段会 upsert 到同一 Evidence。抽取失败只影响 job 状态，不删除 Evidence。

### 多存储协同

不同类型的数据进入不同存储系统：

- PostgreSQL: 股票、行情、公告索引、业务表、链接层与判断台账。
- MongoDB: Evidence 原文片段、source_ref、异步抽取 job 状态。
- Qdrant: Evidence chunk 向量索引（`kg_entities`/`kg_relations` 为三元组时代冻结集合，仅 `search/semantic` entities scope 只读）。
- Redis: 缓存、运行时状态和队列类能力。

## 知识构建层

### Evidence Schema

MVP Evidence 字段包括：

```text
evidence_id
source_type
source_name
source_id
subject_hint
publish_date
observed_at
text_excerpt
source_ref
checksum
confidence
metadata
extraction_status
created_at
updated_at
```

第一版支持的 `source_type`：

- `announcement`
- `annual_report`
- `research_report`
- `irm`
- `market`
- `news`
- `upload`

默认来源置信度：

- 公告、年报: `0.95`
- 市场数据: `1.0`
- 互动易: `0.85`
- 研报: `0.80`
- 新闻: `0.65`
- 上传材料: `0.70`

### 异步抽取机制

Evidence 入库后会生成 extraction jobs。当前 job 类型：

- `vector`: Evidence chunk -> Qdrant vector
- `link`: Evidence -> LLM 浅提取 + 词典匹配 -> 链接层（`link_keywords` / `link_links`）

worker 入口（chemagent 上由 systemd `qingshui-worker` 托管；手动触发参数见
`python backend/scripts/knowledge_worker.py --help`）：

```bash
python backend/scripts/knowledge_worker.py --role evidence-extraction --once --limit 10
```

worker 会 claim pending job，执行抽取，写入 Qdrant/链接层，并把状态回写到 MongoDB。

### 链接层与判断台账（2026-09 重构）

知识构建层在 Evidence-first 之上引入链接层与判断台账，替代批量三元组抽取：

```text
L0 证据层    kg_evidence（Mongo，append-only 真源，全部保留）
L1 链接层    keyword / link（PostgreSQL）
             LLM 浅提取（Company/Product/Metric，单次 flash 调用，只出 surface form）
             + 词典匹配（subject 兜底 / dimension / stage，确定性）
L2 判断层    observation / finding / watermark（PostgreSQL）
             机械候选（共现 × 水位线，零 LLM）+ task-time 深判断（LLM 深判断唯一发生地）
```

要点：

- **批量侧只做浅任务**：类型受约束的关键字提取，可缓存、可全量重算；LLM 深判断只在 task-time。
- **检索原语**：`pull_history`（时间线）/ `scan_dimension`（横截面）/ `backlinks` / `lookup_products` / `lookup_players` / `lookup_customers`（单跳聚合）；`browse`（主题，向量概念层）为后续迭代。
- **写回原语**：`write_observation` / `write_finding` / `watermark`，句级锚定到 evidence span。
- **存储处置**：新结构全部入 PostgreSQL。Neo4j 与三元组管线已于 2026-10-13 整体除役（代码面零依赖，零数据迁移负担）；Qdrant `kg_entities`/`kg_relations` 为冻结只读集合。
- **后续迭代**：zhparser 全文检索、涌现聚类、embedding 概念层附着（见 `docs/superpowers/specs/2026-09-18-knowledge-layer-redesign-design.md`）。

## Agent 入口（dsh 硬切已完成）

**唯一投研对话入口：dsh**（`scripts/start-local-dsh-web.sh` / `headless` + `plugins/qingshui`）。  
Vue `/home` 聊天、`/api/v1/agent/*` LangChain 路径与 `backend/app/reasoning/` 旧运行时**已删除**（2026-10-13）。  
Knowledge HTTP、采集、抽取、worker **保留**。旧前端见 `archive/README.md`。

## Agent 运行机制（dsh + Data MCP）

- **Harness**：DeepSeek harness（dsh，submodule pin）+ Cordis 插件 `plugins/qingshui`；投研身份由
  部署 persona（`plugins/qingshui/cordis.patch.yml`）注入系统提示词。
- **工具面**：只读 Data MCP（`backend/app/mcp_data/`，:8100，21 个只读工具）+ Knowledge HTTP
  （`/api/v1/knowledge/{search/semantic, metrics/compare, agent/*, links/*, market/*, sources/*, ledger/*}`），

  工具名与评测金标对齐（v2 **11 案**）；**判断沉淀**（write_observation/write_finding）只经
  HTTP+插件写面（MCP 不注册写工具），语义见 `docs/开发文档/15_findings台账工具面落地.md`。
- **数据面**：knowledge 构建管线（evidence/链接层/图谱/向量）+ scheduler + worker 不变。
- **评测**：`scripts/run-golden-eval.sh` 跑 `backend/eval/expected_gap_cases_v2.json` 金标
  （默认 v2 11 案，`CASES=` 可回退 v1；headless 逐案 + session 工具归因 + `eval_dual_track.py` 判分）。

## API 服务

FastAPI 入口在 `backend/app/main.py`。主要路由类别：

- `/api/v1/stocks`: 股票搜索（插件选股用）。
- `/api/v1/knowledge`: 知识构建与知识查询接口（Data MCP 22 工具面的全部只读端点都在这里），
  其中 `knowledge/documents/*` 为产物阅读器（文档聚合 + 原文 PDF 流，见 AGENTS.md 2026-10-21 增量）。
- `/api/v1/signals`: 预期差信号接口。
- `/api/v1/readiness`: 数据就绪度接口。
- `/api/v1/auth`、`/api/v1/users`、`/api/v1/account`: 用户与持仓（旧 Vue 前端遗留，无在线客户端）。
- `/health`: 健康检查。

写操作默认需要 API Key。读操作按路由支持可选认证。

## 运行环境

### 部署编排（chemagent）

生产数据面（Mongo/PG/Qdrant/Redis、backend、scheduler、data-mcp）全部跑在 chemagent
机器的 docker compose 上，编排文件为
[`deploy/chemagent/docker-compose.yml`](deploy/chemagent/docker-compose.yml)
（数据一律落 `/data/qingshui/`，宿主端口只绑 `127.0.0.1`）。
云端（124.221.188.38）已冻结只读、待下线，仓库内云端编排与启动脚本已随下线决策清理。

本地 Mac 只跑 Agent 交互层（dsh web + `plugins/qingshui`），入口
[`scripts/start-local-dsh-web.sh`](scripts/start-local-dsh-web.sh)；访问 chemagent 的
Knowledge API / Data MCP 需先建 SSH 端口转发
（[`scripts/tunnel_chemagent.sh`](scripts/tunnel_chemagent.sh)）。

### 后端配置

后端配置通过 `backend/.env` 或环境变量提供。关键配置包括：

```text
DATABASE_URL
MONGODB_URL
REDIS_URL
LLM_API_KEY
LLM_BASE_URL
LLM_MODEL
QDRANT_URL
API_KEY
MASTER_PASSWORD
```

不要把真实密钥提交到仓库。

### 后端启动

推荐使用统一启动脚本：

```bash
bash backend/scripts/start_all.sh
bash backend/scripts/start_all.sh --status
bash backend/scripts/start_all.sh --stop
```

也可以直接启动 FastAPI：

```bash
cd backend
uv run python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### 前端启动

Agent 交互层 = dsh web + `plugins/qingshui`，本机运行：

```bash
pnpm install
./scripts/start-local-dsh-web.sh      # DSH_HOME=~/.dsh-qingshui，端口 8399
```

插件产物（`plugins/qingshui/lib/`）随仓库提交；改源码后重建：

```bash
pnpm build:plugin
```

## 常用命令

Evidence-first 管线测试：

```bash
python -m pytest backend/tests/test_evidence_service.py backend/tests/test_evidence_builders_simple.py backend/tests/test_evidence_worker.py -q
```

链接层 A/B 检索评估（需部署环境，先回填 gold set；完整流程见 [`docs/运维/链接层A-B评估操作手册.md`](docs/运维/链接层A-B评估操作手册.md)）：

```bash
cd backend && uv run python -m scripts.eval_retrieval --backend semantic --k 20
cd backend && uv run python -m scripts.eval_retrieval --backend link --k 20
```

链接层全量回填（幂等、可断点续跑）：

```bash
cd backend && uv run python -m scripts.backfill_keyword_links --dry-run
```

后端健康检查：

```bash
python backend/scripts/health_check.py
```

API 健康检查：

```bash
curl http://localhost:8000/health
```

前端测试：

```bash
cd frontend
pnpm test
```

## 项目特点

- Evidence-first: 先证据、后抽取、再推理，降低不可追溯知识污染。
- 审计友好: 每个事实可以回到 Evidence 原文片段和来源。
- 语义检索: Qdrant 向量 + 链接层结构化查询（横比/时间线/台账）互补。
- 异步抽取: Evidence 入库与 LLM/向量抽取解耦，支持失败重试和版本化重抽。
- Agent 可观察: SSE 事件、运行日志、工具调用和中间件让推理过程可调试。
- 投研边界明确: 系统服务研究辅助，不在知识层沉淀交易建议。

## 当前状态

当前主线已经实现 Evidence-first 知识构建层的基础设施：

- Evidence schema 与稳定 ID
- MongoDB EvidenceService
- IRM/PDF 入口的 Evidence-first 接入
- 异步 EvidenceExtractionWorker
- 链接层 keyword/link 与判断台账 observation/finding 追溯 `evidence_id`
- Evidence chunk 写入 Qdrant
- 针对 Evidence service、builders、worker 的测试覆盖

## 用户与持仓（Sub-Project 1）

系统支持多用户身份管理。每个用户可以维护自己的"持仓"列表（类似同花顺持仓栏的极简版）。

### 启用

1. 在 `backend/.env` 中设置 `MASTER_PASSWORD`（长度 ≥ 8）
2. 在 `backend/users.yaml` 中列出用户：
   ```yaml
   users:
     - user_id: lwm
       display_name: 老王
   ```
3. 重启后端。启动日志会打印"已同步 N 个用户"

### 使用

- 访问 `http://<host>:5173/login`，输入主密码
- 多个用户时选择身份，单个用户时直接进持仓
- 持仓页支持搜索/添加/删除；用户之间严格隔离

### API（用户态，cookie 鉴权）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/auth/login` | 登录（设 master_token cookie） |
| POST | `/api/v1/auth/switch-user` | 切换身份（设 user_id cookie） |
| GET | `/api/v1/auth/whoami` | 当前身份 + 可用用户 |
| POST | `/api/v1/auth/logout` | 登出 |
| GET | `/api/v1/users` | 可选身份列表 |
| GET | `/api/v1/account/portfolio` | 持仓列表 |
| POST | `/api/v1/account/portfolio` | 添加持仓 |
| DELETE | `/api/v1/account/portfolio/{ts_code}` | 删除持仓 |
| GET | `/api/v1/account/stocks/search` | 股票搜索 |

后续可继续扩展：

- 链接层词典与抽取提示词的持续净化、版本升级后的批量重算。
- 判断台账数值型 observation 的自动新颖度判定（环比/区间外）。
- finding supersede 工作流与跨主体预警订阅。
