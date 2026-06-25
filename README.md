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
      |      -> Entity / Relation / StructuredFact -> Vector Index
      |
      +--> Reasoning Runtime
      |      Agent / Tool Registry / Middleware / Subagents / Memory / Journal
      |
      +--> Storage Layer
             PostgreSQL / MongoDB / Neo4j / Qdrant / Redis
```

### 组件分工

- `frontend/`: Vue 3 前端，提供聊天、图谱、投研交互和可视化入口。
- `backend/app/main.py`: FastAPI 应用入口，注册数据、知识、Agent、日志等 API。
- `backend/app/data_pipeline/`: 股票、行情、公告、研报、互动易等数据接入和调度。
- `backend/app/knowledge/`: 知识构建、实体关系抽取、Evidence-first 管线、图谱与向量检索。
- `backend/app/reasoning/`: Agent 运行时、工具注册、推理中间件、SSE 事件、子任务和记忆机制。
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
-> Entity / Relation / StructuredFact
-> Vector Index
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
- StructuredFact: `SF:` + SHA256

重复导入同一原文片段会 upsert 到同一 Evidence。抽取失败只影响 job 状态，不删除 Evidence。

### 多存储协同

不同类型的数据进入不同存储系统：

- PostgreSQL: 股票、行情、公告索引、业务表和结构化数据。
- MongoDB: Evidence 原文片段、source_ref、异步抽取 job 状态。
- Neo4j: Entity、Relation、StructuredFact 以及可遍历图谱关系。
- Qdrant: Evidence chunk、实体描述、关系描述等向量索引。
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

- `combined`: Evidence -> entities + relations + structured_facts
- `vector`: Evidence chunk -> Qdrant vector

worker 入口：

```bash
python backend/scripts/evidence_extraction_worker.py --once --limit 10
python backend/scripts/evidence_extraction_worker.py --daemon --interval 30 --job-type combined
python backend/scripts/evidence_extraction_worker.py --daemon --interval 30 --job-type vector
```

worker 会 claim pending job，执行抽取，写入 Neo4j/Qdrant，并把状态回写到 MongoDB。

### 结构化事实

StructuredFact 用于表达从 Evidence 中抽取出的状态事实：

```text
subject_id
subject_type
dimension
state_value
observed_at
valid_from
valid_to
evidence_id
evidence_text
confidence
metadata
```

示例：

- `production / mass_production_started`
- `customer / customer_introduction`
- `order / order_scheduled`
- `financial / earnings_below_expectation`

`StructuredFact` 会引用 `evidence_id`，保证每个结构化状态可以追溯到原文。

## Agent 与推理运行机制

Reasoning 子系统位于 `backend/app/reasoning/`。它把用户请求拆成可观测的运行过程：

- API 层接收用户问题并通过 SSE 返回过程事件。
- Tool Registry 管理可用工具和工具调用边界。
- Middleware 负责上下文压缩、内存、重试、事件过滤和安全边界。
- Tool Executor 执行数据查询、知识检索、图谱查询、行情查询等工具。
- Run Journal 记录关键事件，方便调试和回放。
- Subagents 支持较复杂任务的拆分与轮询。

Agent 的设计重点是让推理过程可观察、可测试、可恢复，而不是把所有逻辑藏在单次 LLM 调用里。

## API 服务

FastAPI 入口在 `backend/app/main.py`。主要路由类别：

- `/api/v1/agent`: Agent 对话和推理接口。
- `/api/v1/data`: 数据查询接口。
- `/api/v1/stocks`: 股票数据写入和管理接口。
- `/api/v1/concept`: 概念评分接口。
- `/api/v1/knowledge`: 知识包和知识查询接口。
- `/api/v1/information`: 资讯接口。
- `/api/v1/logs`: 日志查询接口。
- `/health`: 健康检查。

写操作默认需要 API Key。读操作按路由支持可选认证。

## 运行环境

### 基础服务

使用 Docker Compose 启动依赖服务：

```bash
docker compose up -d
```

包含：

- Neo4j: `7474`, `7687`
- PostgreSQL: host `5433`, container `5432`
- MongoDB: host `27018`, container `27017`
- Redis: `6379`
- Qdrant: `6333`, `6334`

### 后端配置

后端配置通过 `backend/.env` 或环境变量提供。关键配置包括：

```text
DATABASE_URL
MONGODB_URL
REDIS_URL
LLM_API_KEY
LLM_BASE_URL
LLM_MODEL
NEO4J_URL
NEO4J_USER
NEO4J_PASSWORD
QDRANT_URL
API_KEY
HUNYUAN_API_KEY
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

```bash
cd frontend
pnpm install
pnpm dev
```

构建：

```bash
pnpm build
```

## 常用命令

Evidence worker smoke test：

```bash
python backend/scripts/evidence_extraction_worker.py --once --limit 0
```

Evidence-first 管线测试：

```bash
python -m pytest backend/tests/test_evidence_service.py backend/tests/test_evidence_builders.py backend/tests/test_evidence_worker.py -q
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
- 混合检索: Neo4j 图谱关系与 Qdrant 语义向量互补。
- 异步抽取: Evidence 入库与 LLM/向量抽取解耦，支持失败重试和版本化重抽。
- Agent 可观察: SSE 事件、运行日志、工具调用和中间件让推理过程可调试。
- 投研边界明确: 系统服务研究辅助，不在知识层沉淀交易建议。

## 当前状态

当前主线已经实现 Evidence-first 知识构建层的基础设施：

- Evidence schema 与稳定 ID
- MongoDB EvidenceService
- IRM/PDF 入口的 Evidence-first 接入
- 异步 EvidenceExtractionWorker
- Entity / Relation / StructuredFact 追溯 `evidence_id`
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

- 更细粒度 job 类型，例如 `entity_relation`、`structured_fact`、`metric`。
- 面向 Agent 的 ResearchContext 工具层。
- StructuredFact 的更多行业状态维度和验证集。
- 抽取版本升级后的批量重抽和质量评估。
