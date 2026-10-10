# Agent / Data MCP / DeepSeek Harness Implementation Plan（双轨 C）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在云端落地只读 **Data MCP**（P0：evidence / semantic_search / compare_metric / pull_history / lookup_* / get_kline / get_stock_profile / data_readiness），并用同一套 **DeepSeek harness（dsh）+ `plugins/qingshui`** 在本机与云端旁路接入；旧 `stream/report` LangChain Agent **原样保留**，直到预期差金标评测对齐后再切默认流量。

**Architecture:** 先补齐 Knowledge 薄只读 HTTP（semantic / compare_metric / pull_history 等今日缺口），再在同仓用 Python MCP Server 薄包装这些查询（部署在云端，与 Knowledge API 同机）。`plugins/qingshui` 经 `@deepseek-ai/dsh-mcp-client` 连 Data MCP（远程 Streamable HTTP；本机调试可用 stdio）。旧 Agent 继续进程内直连 DB，互不打断。查询逻辑优先下沉 `app.knowledge` / HTTP，禁止在 Node 插件复制 SQL。

**Tech Stack:** Python 3.13、FastAPI、pytest、httpx、官方 `mcp` SDK（Streamable HTTP）、Node ≥22.19、pnpm、TypeScript、tsdown、dsh submodule（pin `dsh-v0.1.1-rc.2` / `b150a551…`）、Cordis、`@deepseek-ai/dsh-mcp-client`、nginx（dsh web basic auth；MCP 用 `X-API-Key`）。

**Spec:** `docs/superpowers/specs/2026-10-10-agent-mcp-deepseek-harness-design.md`  
**Align:** `docs/superpowers/specs/2026-09-29-dsh-agent-runtime-cutover-design.md`、`docs/superpowers/plans/2026-09-29-dsh-vertical-slice.md`（脚手架可复用；本计划扩展为 MCP + 评测双轨，**取代「立刻硬切」**）

## Global Constraints

- **Approach C 双轨**：不删 `frontend/`、不归档 `langchain_agent/**`、不下线 `/api/v1/agent/*`，直到 §切流门禁达标且另开 cutover plan。
- **Data MCP 第一期只读**：禁止包装 write / job claim / vector|link upsert / scheduler 触发。
- **生产联通铁律（AGENTS.md）**：只云端 + chemagent；**禁止**生产依赖本机 Mac 隧道；本机 harness 仅 `dev-eval`。
- **插件不直连 DB**：Node 只打 MCP 或 Knowledge HTTP；MCP server 部署在云端同仓，可调用 Python 查询层。
- **P0 强制薄 HTTP**：`semantic_search` / `compare_metric` / `pull_history` / `lookup_players` / `lookup_products` / `get_kline` / `get_stock_profile` 必须有 Knowledge（或 `/api/v1/agent-data`）只读 HTTP；MCP 优先委托 HTTP/共享服务函数，避免「只有 MCP 能用」。
- **工具对外名**与现 `@tool` / `registry/config.yaml` **一致**（`fetch_evidence`、`semantic_search`、`compare_metric`…）。
- **不 fork `dsh/`**；投研能力只在 `plugins/qingshui`。
- **dsh pin**：`https://github.com/deepseek-ai/deepseek-harness.git` @ `b150a551b8d465e31e418e1b2eaf5e79bbb7d28e`（`dsh-v0.1.1-rc.2`，对齐 MatDiscovery）。
- **LLM**：本仓 LiteLLM；`apiKeyEnv=LLM_API_KEY`，`baseURL=http://127.0.0.1:4000/v1`，默认模型 `MiniMax-M2.7-highspeed`；不绑 memtensor / MatDiscovery Boyue。
- **Embedding**：`semantic_search` 只打 chemagent 稳定 endpoint；失败返回空结果 + `data_status=unavailable`，不得拖死结构化工具。
- **doc 13**（`docs/开发文档/13_云端知识底座与本机Agent解耦部署方案.md`）维持作废，不得引用为部署依据。
- **`dsh-agent-rpc`：本波不上。**
- Branch：`feat/agent-mcp-dsh-dual-track`（worktree 推荐）。
- Tests：Python `cd backend && .venv/bin/python -m pytest <path> -v`；Node `pnpm test:plugin`（或 VS plan 中的 tsx `--test`）。
- 每个 Task 结束一次 commit；`docs/superpowers/` 若被 ignore 则 `git add -f`。

---

## Locked decisions（关闭 design §12 开放问题）

| # | 问题 | 本计划锁定 |
|---|---|---|
| 1 | MCP 实现语言 | **Python 同仓**（`backend/app/mcp_data/`）；Node 只做 MCP client |
| 2 | P0 是否强制 HTTP | **是** — 先 HTTP，再 MCP 薄包装 |
| 3 | 金标断言强度 | 第一期以**正文关键短语 + 必调工具名**为主；`conclusions[]` 有则校验，无则不阻断 |
| 4 | dsh pin | 继续 `b150a551…` / `dsh-v0.1.1-rc.2` |
| 5 | 本机 embedding 代理 | **禁止**；单测可用 mock MCP（假数据），不得真连生产库做默认 CI |
| 6 | 旧轨热修回灌 | 不阻塞本计划；另开 hotfix PR；双轨期间旧入口回归由 eval runner 发现 |
| 7 | 网搜工具 | **不进** Data MCP；若需要，第二期作 harness 本地工具 |

---

## Deploy Authority

| Who | May do |
|---|---|
| Implementer（本机） | 改仓、本地测试、`git push` |
| Implementer（默认） | **不得** scp/ssh/systemd/改云上 nginx（除非用户 1:1 明确授权） |
| User / 1:1 | 云上拉码、起 MCP、起 dsh、nginx、smoke |

---

## OUT OF SCOPE（第一期）

- MCP 写路径 / 入队 / worker claim。
- 删除或归档 Vue / LangChain / 旧 Agent API。
- 改数据构建拓扑（scheduler / chemagent 分工）。
- 公网暴露 Neo4j/PG/Mongo/Qdrant。
- 完成 09-29 §9 硬切验收清单（Vue 退役等）— 顺延到切流后 cutover plan。
- `neo4j_*` 全量、`tavily_search` / `web_fetch` 进 Data MCP。
- fork / 改 `dsh/` 内核文件。

---

## Research notes（implementer 锁定）

| Item | Finding |
|---|---|
| `fetch_evidence` | LangChain：`tools/knowledge/evidence.py`；HTTP **已有** `GET /api/v1/knowledge/evidence/{evidence_id}`；正文截断 **8000** 字符 |
| `semantic_search` | 进程内 `vector_client`；**无 HTTP**（VS Task 3 未落地；`agent_search.py` 不存在） |
| `compare_metric` | `tools/knowledge/metric_ops.py` → PG linklayer；**无 HTTP** |
| `pull_history` / `lookup_*` | `linklayer/queries.py` + `link_queries.py`；**无 HTTP** |
| `get_kline` / `get_stock_profile` | 进程内 service；监控类 API 零散，**无 Agent 契约 HTTP** |
| `data_readiness` | **已有** `GET /api/v1/readiness/`（`app.readiness.api`） |
| VS 脚手架 | **未合入**：无 `.gitmodules`、无 `plugins/`、无 `dsh/` |
| MatDiscovery MCP | `plugins/matdiscovery` 用 `@deepseek-ai/dsh-mcp-client`；远程 FieldMat MCP URL 模式可参考，**禁止拷业务** |
| Gold | `backend/eval/gold_set_v1.json`（retrieval）；预期差案另建 `backend/eval/expected_gap_cases_v1.json` |
| Auth | `app.knowledge.api._auth.require_api_key`（`knowledge_api_key or api_key`） |

---

## HTTP gap map（必须进任务）

| Tool | HTTP today | Plan action |
|---|---|---|
| `fetch_evidence` | ✅ GET evidence | MCP wrap；截断对齐 8k |
| `semantic_search` | ❌ | **新增** `POST /api/v1/knowledge/search/semantic` |
| `compare_metric` | ❌ | **新增** `POST /api/v1/knowledge/metrics/compare` |
| `pull_history` | ❌ | **新增** `POST /api/v1/knowledge/links/history` |
| `lookup_players` / `lookup_products` | ❌ | **新增** `POST …/links/lookup_players` + `…/lookup_products` |
| `get_kline` | ❌ | **新增** `GET /api/v1/knowledge/market/kline` |
| `get_stock_profile` | ❌ | **新增** `GET /api/v1/knowledge/market/stock_profile` |
| `data_readiness` | ✅ `/api/v1/readiness/` | MCP wrap 现有 |

---

## File Structure

| Path | Responsibility |
|---|---|
| `.gitmodules` / `dsh/` | 只读 harness pin |
| `package.json` / `pnpm-workspace.yaml` / `scripts/dsh.mjs` | 根启动器（同 VS） |
| `patches/qingshui.yml` | 本机/云端 overlay（`MCP_BASE_URL` 等） |
| `plugins/qingshui/**` | Cordis 插件：MCP client 挂载 + 预期差 skill |
| `backend/app/knowledge/api/agent_search.py` | `POST /search/semantic` |
| `backend/app/knowledge/api/agent_metrics.py` | `POST /metrics/compare` |
| `backend/app/knowledge/api/agent_links.py` | `POST /links/history|lookup_players|lookup_products` |
| `backend/app/knowledge/api/agent_market.py` | `GET /market/kline` + `GET /market/stock_profile` |
| `backend/app/main.py` | include 上述 routers |
| `backend/app/mcp_data/__init__.py` | Data MCP 包 |
| `backend/app/mcp_data/server.py` | MCP server 入口（stdio + streamable HTTP） |
| `backend/app/mcp_data/tools_readonly.py` | P0 tool handlers（调共享查询 / HTTP 客户端） |
| `backend/app/mcp_data/auth.py` | API Key 校验（HTTP transport） |
| `backend/app/mcp_data/truncation.py` | evidence 8k 等截断 |
| `backend/tests/test_agent_search_api.py` | semantic HTTP |
| `backend/tests/test_agent_metrics_api.py` | compare_metric HTTP |
| `backend/tests/test_agent_links_api.py` | pull_history / lookup HTTP |
| `backend/tests/test_agent_market_api.py` | kline / profile HTTP |
| `backend/tests/test_mcp_data_tools.py` | MCP tool 单元（mock 下游） |
| `backend/eval/expected_gap_cases_v1.json` | 预期差金标 |
| `backend/scripts/eval_dual_track.py` | 旧轨 API vs 新轨 harness 对照 |
| `deploy/mcp/qingshui-data-mcp.service.example` | systemd 示例 |
| `deploy/mcp/README.md` | 云上起 MCP + 鉴权 |
| `deploy/nginx/dsh-web.conf.example` | dsh web basic auth（继承 VS） |
| `deploy/dsh/README.md` | 双端 harness 配置（`MCP_BASE_URL`） |
| `docs/superpowers/specs/2026-10-10-agent-mcp-deepseek-harness-design.md` | 已批准；实现中不改边界除非开新决策 |

---

### Task 1: Branch + 决策落盘指针

**Files:**
- Create/Modify: worktree on `feat/agent-mcp-dsh-dual-track`
- Modify: `docs/superpowers/specs/2026-10-10-agent-mcp-deepseek-harness-design.md`（仅在 §12 开放问题下追加「已由 plan 锁定」一行表，不改架构）

**Interfaces:**
- Consumes: approved design
- Produces: clean branch for all later tasks

- [x] **Step 1: 建 worktree / 分支**

```bash
cd /Users/lwm/code/QingshuiYanTou
git fetch origin
git worktree add /Users/lwm/code/QingshuiYanTou.worktrees/agent-mcp-dsh -b feat/agent-mcp-dsh-dual-track origin/main
cd /Users/lwm/code/QingshuiYanTou.worktrees/agent-mcp-dsh
```

Expected: 干净分支；勿夹带无关 WIP。

- [x] **Step 2: 在 design §12 末追加锁定表引用**

追加一段：

```markdown
### Plan lock (2026-10-10)

See `docs/superpowers/plans/2026-10-10-agent-mcp-deepseek-harness.md` §Locked decisions.
```

- [x] **Step 3: Commit**

```bash
git add docs/superpowers/specs/2026-10-10-agent-mcp-deepseek-harness-design.md
git add -f docs/superpowers/plans/2026-10-10-agent-mcp-deepseek-harness.md
git commit -m "docs: lock dual-track MCP/dsh plan decisions"
```

---

### Task 2: dsh submodule + 根 launcher（承接 VS Task 1）

> **Note:** Already on `origin/main` (dsh pin b150a551, package.json, scripts/dsh.mjs, patches/). Submodule initialized in this worktree; no new commit.

**Files:**
- Create: `.gitmodules`, `package.json`, `pnpm-workspace.yaml`, `scripts/dsh.mjs`, `patches/qingshui.yml`, `patches/README.md`

**Interfaces:**
- Consumes: none
- Produces: `pnpm dsh` 可调用 dsh CLI（插件尚空）

- [x] **Step 1: 写失败冒烟（脚本断言 submodule 缺失）**

```bash
test ! -d dsh && echo "NEED_SUBMODULE"
```

Expected: 打印 `NEED_SUBMODULE`（当前仓无 dsh）。

- [x] **Step 2: 添加 pin 的 submodule**

```bash
git submodule add https://github.com/deepseek-ai/deepseek-harness.git dsh
cd dsh && git checkout b150a551b8d465e31e418e1b2eaf5e79bbb7d28e && cd ..
git submodule status
```

Expected: `b150a551… dsh`。

- [x] **Step 3: 写入根 `package.json` / `pnpm-workspace.yaml` / `scripts/dsh.mjs`**

内容对齐 `docs/superpowers/plans/2026-09-29-dsh-vertical-slice.md` Task 1 Steps 3–5（`qingshui-yantou`、`build:plugin`、`dsh`、`test:plugin`、`$REPO_ROOT` patch rewrite）。**逐字复用 VS 计划中的 `scripts/dsh.mjs` 实现**，勿发明第二套 launcher。

- [x] **Step 4: 写空 overlay**

`patches/qingshui.yml`:

```yaml
[]
```

`patches/README.md`：说明云端/本机用 overlay 改 `MCP_BASE_URL`，生产 profile 不得写 Mac 隧道。

- [x] **Step 5: Commit**

```bash
git add .gitmodules dsh package.json pnpm-workspace.yaml scripts/dsh.mjs patches/
git commit -m "chore: add dsh submodule pin and root launcher"
```

---

### Task 3: 空壳 `plugins/qingshui`（承接 VS Task 2）

> **Note:** Already on `origin/main` — `plugins/qingshui` is beyond empty shell (Knowledge HTTP tools + research client). Dual-track keeps it; MCP client comes in Task 9.

**Files:**
- Create: `plugins/qingshui/package.json`, `cordis.patch.yml`, `tsconfig.json`, `tsdown.config.ts`, `src/index.ts`, `src/config.ts`

**Interfaces:**
- Consumes: Task 2 launcher
- Produces: `pnpm build:plugin` 产出 `lib/index.mjs`；dsh web 可加载空插件

- [x] **Step 1: 写失败测试（插件入口导出 apply）**

`plugins/qingshui/src/index.test.ts`:

```ts
import assert from 'node:assert/strict'
import test from 'node:test'

test('qingshui plugin module exports apply', async () => {
  const mod = await import('./index.ts')
  assert.equal(typeof mod.apply, 'function')
})
```

- [x] **Step 2: Run → 预期 FAIL（文件不存在）**

```bash
pnpm install
pnpm test:plugin
```

Expected: FAIL cannot find module / apply。

- [x] **Step 3: 最小实现**

按 VS Task 2：`package.json`（`dsh.bundle` name=`qingshui`）、`cordis.patch.yml`（插入插件 + LiteLLM provider：`baseURL: http://127.0.0.1:4000/v1`，`apiKeyEnv: LLM_API_KEY`，model `MiniMax-M2.7-highspeed`）、`src/config.ts`（Schemastery：`knowledgeBaseUrl`, `mcpBaseUrl`, `knowledgeApiKeyRef`, `toolCallTimeoutMs` 默认 120000）、`src/index.ts`：

```ts
export const name = 'qingshui'
export const inject = ['tool']
export function apply(ctx: any, config: any) {
  ctx.logger.info('qingshui plugin loaded (tools come in later tasks)')
}
```

- [x] **Step 4: Build + test PASS**

```bash
pnpm build:plugin && pnpm test:plugin
```

- [x] **Step 5: Commit**

```bash
git add plugins/qingshui
git commit -m "feat(qingshui): empty cordis plugin bundle"
```

---

### Task 4: Knowledge HTTP — `POST /api/v1/knowledge/search/semantic`

> **Note:** Already on `origin/main` (`agent_search.py` + tests). Verified pytest 4/4 PASS this session.

**Files:**
- Create: `backend/app/knowledge/api/agent_search.py`
- Create: `backend/tests/test_agent_search_api.py`
- Modify: `backend/app/main.py`

**Interfaces:**
- Consumes: `app.knowledge.vector_client.semantic_search_entities/chunks`；`require_api_key`
- Produces: HTTP body 形状与 LangChain `semantic_search` 返回对齐

- [x] **Step 1: 写失败测试**

```python
# backend/tests/test_agent_search_api.py
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_semantic_search_requires_api_key():
    r = client.post("/api/v1/knowledge/search/semantic", json={"query": "硅片 毛利率"})
    assert r.status_code in (401, 403)

def test_semantic_search_entities_shape(monkeypatch):
    from app.knowledge.api import agent_search as mod

    class Hit:
        entity_id = "E1"
        name = "中晶科技"
        type = "Company"
        ts_code = "003026.SZ"
        score = 0.9

    monkeypatch.setattr(
        "app.knowledge.vector_client.semantic_search_entities",
        lambda q, ts_code=None, top_k=5: [Hit()],
    )
    monkeypatch.setattr(mod, "require_api_key", lambda: None)
    # Prefer dependency override if router uses Depends(require_api_key)
    r = client.post(
        "/api/v1/knowledge/search/semantic",
        json={"query": "硅片", "scope": "entities", "top_k": 5},
        headers={"X-API-Key": "test"},
    )
    assert r.status_code == 200
    body = r.json()
    assert "entities" in body
    assert body["entities"][0]["ts_code"] == "003026.SZ"
```

（实现时用 FastAPI `dependency_overrides` 覆盖 `require_api_key`，与现有 knowledge 测试一致。）

- [x] **Step 2: Run → FAIL**

```bash
cd backend && .venv/bin/python -m pytest tests/test_agent_search_api.py -v
```

Expected: import/404 fail。

- [x] **Step 3: 实现 router**

```python
# backend/app/knowledge/api/agent_search.py
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from app.knowledge.api._auth import require_api_key

router = APIRouter(prefix="/api/v1/knowledge/search", tags=["knowledge-agent-read"])

class SemanticSearchIn(BaseModel):
    query: str
    scope: str = "entities"  # entities|chunks|both
    ts_code: str | None = None
    top_k: int = Field(default=5, ge=1, le=50)

@router.post("/semantic")
async def semantic_search(body: SemanticSearchIn, _: None = Depends(require_api_key)):
    from app.knowledge import vector_client
    # mirror tools/knowledge/semantic_search.py shaping; on embedding failure return empty lists
    ...
```

在 `main.py` `include_router(agent_search.router)`。

- [x] **Step 4: pytest PASS**

- [x] **Step 5: Commit**

```bash
git commit -am "feat(knowledge): POST /search/semantic for agent/MCP"
```

---

### Task 5: Knowledge HTTP — `compare_metric` + `pull_history` + `lookup_*`

> **Note:** `compare_metric` already existed at `POST /api/v1/knowledge/agent/compare_metric`; added plan-path alias `POST /api/v1/knowledge/metrics/compare`. New: `agent_links.py` for history/lookup_*. Pre-existing `test_link_tools_resolve_and_register` fail (`write_todos.use: null`) is unrelated.

**Files:**
- Create: `backend/app/knowledge/api/agent_metrics.py`, `agent_links.py`
- Create: `backend/tests/test_agent_metrics_api.py`, `test_agent_links_api.py`
- Modify: `backend/app/main.py`
- Optional extract: move `_collect_rows` / compare pure logic to `app.knowledge.linklayer.metrics` so LangChain tool 与 HTTP 共用（禁止复制 SQL）

**Interfaces:**
- Consumes: `app.knowledge.linklayer.queries.pull_history|lookup_*`；metric compare 逻辑
- Produces:
  - `POST /api/v1/knowledge/metrics/compare` → `{dimension,scope,as_of,count,items,missing_value,note}`
  - `POST /api/v1/knowledge/links/history` → pull_history dict
  - `POST /api/v1/knowledge/links/lookup_players` / `lookup_products`

- [x] **Step 1: 写失败测试（compare）**

```python
def test_compare_metric_http_shape(monkeypatch):
    # override auth; monkeypatch collector to return two subjects
    payload = {"dimension": "毛利率", "scope": "硅片", "top_k": 10}
    r = client.post("/api/v1/knowledge/metrics/compare", json=payload, headers={"X-API-Key": "test"})
    assert r.status_code == 200
    body = r.json()
    assert body["dimension"] == "毛利率"
    assert "items" in body and "count" in body
```

`pull_history` / `lookup_players` 同理：断言 status 200 + 关键字段（`events`/`items` 以现 `queries.py` 返回为准）。

- [x] **Step 2: pytest → FAIL**

- [x] **Step 3: 实现**

- 从 `metric_ops.compare_metric` **抽出**异步/同步可测的核心函数到 `app.knowledge.linklayer.metrics.compare_metric(...)`；LangChain `@tool` 改为调用该函数；HTTP 也调用它。
- `agent_links.py` 直接 `await pull_history(...)` 等。

- [x] **Step 4: pytest PASS**（含既有 `tests/test_linklayer_*.py` 无回归）

```bash
.venv/bin/python -m pytest tests/test_agent_metrics_api.py tests/test_agent_links_api.py tests/test_linklayer_queries.py tests/test_linklayer_tools.py -v
```

- [x] **Step 5: Commit**

```bash
git commit -am "feat(knowledge): read-only HTTP for compare_metric and link queries"
```

---

### Task 6: Knowledge HTTP — market `get_kline` + `get_stock_profile`

**Files:**
- Create: `backend/app/knowledge/api/agent_market.py`
- Create: `backend/tests/test_agent_market_api.py`
- Modify: `backend/app/main.py`

**Interfaces:**
- Consumes: `KlineService.get_stock_kline`, `StockService.get_stock_profile`
- Produces: JSON（优先结构化；可同时提供 `text` 字段对齐旧 tool 字符串，便于评测）

- [x] **Step 1: 写失败测试**

```python
def test_kline_requires_ts_code_and_auth():
    r = client.get("/api/v1/knowledge/market/kline", params={"ts_code": "300308.SZ"})
    assert r.status_code in (401, 403)

def test_stock_profile_ok(monkeypatch):
    # mock service → 200 + main_business
    ...
```

- [x] **Step 2: FAIL → 实现 → PASS**

```python
@router.get("/kline")
async def get_kline(ts_code: str, start_date: str = "", end_date: str = "", freq: str = "D", _: None = Depends(require_api_key)):
    ...

@router.get("/stock_profile")
async def get_stock_profile(ts_code: str, _: None = Depends(require_api_key)):
    ...
```

- [x] **Step 3: Commit**

```bash
git commit -am "feat(knowledge): read-only HTTP for kline and stock_profile"
```

---

### Task 7: Data MCP Server（只读 P0 tools）

> **Note:** Pinned `mcp>=1.9,<2` (FastMCP). mcp 2.x breaks FastAPI 0.115 via starlette 1.x.

**Files:**
- Create: `backend/app/mcp_data/{__init__,server,tools_readonly,auth,truncation}.py`
- Create: `backend/tests/test_mcp_data_tools.py`
- Modify: `backend/requirements.txt`（增加 `mcp` 官方包，pin 兼容版本）

**Interfaces:**
- Consumes: Task 4–6 HTTP 或同仓服务函数；`GET evidence`；`GET /api/v1/readiness/`
- Produces: MCP tools 名：`fetch_evidence`, `semantic_search`, `compare_metric`, `pull_history`, `lookup_players`, `lookup_products`, `get_kline`, `get_stock_profile`, `data_readiness`
- Transport: **stdio**（本机调试）+ **Streamable HTTP**（默认 `127.0.0.1:8100/mcp`，仅云内/本机隧道到云）

- [x] **Step 1: 写失败测试（tool registry + 截断）**

```python
import pytest
from app.mcp_data.truncation import truncate_evidence_text
from app.mcp_data.tools_readonly import TOOL_NAMES

def test_p0_tool_names_locked():
    assert set(TOOL_NAMES) >= {
        "fetch_evidence", "semantic_search", "compare_metric",
        "pull_history", "lookup_players", "lookup_products",
        "get_kline", "get_stock_profile", "data_readiness",
    }

def test_evidence_truncation_8k():
    text = "x" * 9000
    out = truncate_evidence_text(text)
    assert len(out) < 9000
    assert "截断" in out or "truncated" in out.lower() or len(out) <= 8000 + 80
```

- [x] **Step 2: pytest → FAIL**

- [x] **Step 3: 实现 MCP server**

要点：

1. `tools_readonly.py`：每个 tool 调内部 async 函数（优先 `httpx.AsyncClient` 打本机 Knowledge `http://127.0.0.1:8000`，便于与 HTTP 单测同源；也允许直接调 service 以减跳数——但**必须**有 HTTP 存在）。
2. `fetch_evidence`：GET evidence 后用与 LangChain 相同的 8k 截断文案。
3. `server.py`：

```python
# entry: python -m app.mcp_data.server --transport streamable-http --host 127.0.0.1 --port 8100
# and: python -m app.mcp_data.server --transport stdio
```

4. HTTP transport 校验 `X-API-Key`（与 Knowledge 同源设置）。
5. **拒绝**注册任何 write 工具；加测试 `test_no_write_tools_registered`。

- [x] **Step 4: pytest PASS**

```bash
.venv/bin/python -m pytest tests/test_mcp_data_tools.py -v
```

- [x] **Step 5: Commit**

```bash
git commit -am "feat(mcp_data): read-only Data MCP server for P0 tools"
```

---

### Task 8: MCP 健康检查 + 部署文件（不做云上不可逆操作）

**Files:**
- Create: `deploy/mcp/qingshui-data-mcp.service.example`, `deploy/mcp/README.md`
- Create: `backend/tests/test_mcp_data_health.py`（若暴露 `/health`）或文档化 `tools/list` 探活
- Modify: `plugins/qingshui/src/config.ts` 增加 `mcpBaseUrl` 默认 `http://127.0.0.1:8100/mcp`

**Interfaces:**
- Produces: 用户可按 README 在云上起 MCP；profile=`prod` vs `dev-eval` 写清

- [x] **Step 1: 写 README 验收清单（可执行命令）**

```bash
# on cloud (user applies)
cd backend && .venv/bin/python -m app.mcp_data.server --transport streamable-http --host 127.0.0.1 --port 8100
curl -s -H "X-API-Key: $KNOWLEDGE_API_KEY" http://127.0.0.1:8100/health
```

- [x] **Step 2: systemd example**（`WorkingDirectory=…/backend`，`Environment=KNOWLEDGE_API_KEY=…`，禁止 `0.0.0.0` 除非另有 nginx 鉴权）

- [x] **Step 3: Commit**

```bash
git add deploy/mcp plugins/qingshui/src/config.ts
git commit -m "docs(deploy): Data MCP systemd example and health notes"
```

---

### Task 9: `plugins/qingshui` 挂载 Data MCP client

**Files:**
- Modify: `plugins/qingshui/src/index.ts`, `config.ts`
- Create: `plugins/qingshui/src/mcp-mount.ts`, `mcp-mount.test.ts`
- Modify: `plugins/qingshui/cordis.patch.yml`（credentials / mcp url）

**Interfaces:**
- Consumes: `@deepseek-ai/dsh-mcp-client`（随 dsh workspace）；Task 7 server
- Produces: harness 会话中可见 MCP 工具（名称可能带 `mcp__qingshui_data__` 前缀——评测用 bare name 归一，参考 MatDiscovery `bareToolName`）

- [x] **Step 1: 写失败测试**

```ts
test('mcp mount config requires non-empty mcpBaseUrl for remote profile', () => {
  // validateConfig rejects empty mcpBaseUrl when mode=remote
})
```

- [x] **Step 2: FAIL → 实现 mount**

参考 MatDiscovery remote MCP（**只抄挂载形态**）：

```ts
import * as mcpClient from '@deepseek-ai/dsh-mcp-client'

// transport: 'http' or whatever dsh-mcp-client supports for Streamable HTTP
ctx.plugin(mcpClient, {
  transport: 'http',
  serverName: 'qingshui_data',
  url: config.mcpBaseUrl,
  headers: { 'X-API-Key': await resolveApiKey(config.knowledgeApiKeyRef) },
  toolCallTimeoutMs: config.toolCallTimeoutMs ?? 120000,
  failOnStartupError: false,
})
```

本机 `dev-eval`：`mcpBaseUrl` 指向云端 HTTPS MCP（经 nginx + API Key）；**不得**在默认 prod patch 写 Mac localhost 隧道。

- [x] **Step 3: `pnpm build:plugin && pnpm test:plugin` PASS**

- [x] **Step 4: Commit**

```bash
git commit -am "feat(qingshui): mount read-only Data MCP client"
```

---

### Task 10: 预期差 skill + 轨迹落盘钩子

**Files:**
- Create: `plugins/qingshui/skills/expected-gap/SKILL.md`（或 dsh 约定的 skill 目录结构，对齐 MatDiscovery skills 挂载方式）
- Create: `backend/scripts/dump_harness_trace_schema.md` 或 `plugins/qingshui/src/trace.ts`（若 dsh 暴露 session hooks）
- Create: `backend/eval/expected_gap_cases_v1.json`

**Interfaces:**
- Produces: 至少 3 条 case（硅片毛利横比、中晶相关、degraded-readiness 弱结论）；skill 指示优先 `compare_metric` → `pull_history` → `fetch_evidence`

- [x] **Step 1: 写入金标 JSON**

```json
[
  {
    "case_id": "gap-wafer-margin-001",
    "question": "生产8英寸抛光硅片的公司毛利率对比，是否存在预期差？",
    "must_call_tools": ["compare_metric"],
    "must_call_any_of": ["pull_history", "fetch_evidence", "semantic_search"],
    "answer_must_include_any": ["毛利率", "预期差", "硅片"],
    "notes": "对齐实跑 Case5；允许 degraded"
  },
  {
    "case_id": "gap-zj-margin-001",
    "question": "中晶科技相关毛利率横比与预期差结论",
    "must_call_tools": ["compare_metric"],
    "answer_must_include_any": ["中晶", "毛利"],
    "notes": "对齐实跑 Case3"
  },
  {
    "case_id": "gap-degraded-ok-001",
    "question": "在数据 readiness=degraded 时，仍基于 compare_metric 给出有依据的弱结论",
    "must_call_tools": ["compare_metric", "data_readiness"],
    "answer_must_include_any": ["预期差", "毛利", "依据"],
    "allow_degraded": true
  }
]
```

- [x] **Step 2: skill 文档**写明工具顺序与「禁止无工具空喊预期差」。

- [x] **Step 3: 轨迹**：若 dsh 已有 transcript API，写 `scripts/export_dsh_trace.mjs` 导出 JSONL（model/tool/name/args/result_excerpt/latency_ms/error）。若无稳定 API，第一期允许评测 runner 抓 stdout + tool 事件日志，并在 README 标明缺口。

- [x] **Step 4: Commit**

```bash
git add plugins/qingshui/skills backend/eval/expected_gap_cases_v1.json
git commit -m "feat(eval): expected-gap cases and qingshui skill stub"
```

---

### Task 11: 双轨评测 runner（旧 Agent API vs 新 harness）

**Files:**
- Create: `backend/scripts/eval_dual_track.py`
- Create: `backend/tests/test_eval_dual_track_unit.py`（纯函数：断言通过逻辑，不打真 LLM）

**Interfaces:**
- Consumes: `expected_gap_cases_v1.json`；旧轨 `POST /api/v1/agent/stream` 或 report 接口（按现 `agent.py` 实测路径）；新轨 CLI/`pnpm dsh` 非交互跑案（若仅 web，则用 dsh 提供的 headless/agent API——查阅 pin 版 dsh 文档；若无 headless，runner 先支持 **MCP-only tool oracle** + **人工粘贴新轨正文** 双模式，但必须自动跑旧轨）
- Produces: `backend/eval/out/dual_track_report.json`：每案 `{case_id, old_pass, new_pass, old_tools, new_tools, reasons}`

- [ ] **Step 1: 写单元测试（断言器）**

```python
from scripts.eval_dual_track import judge_case

def test_judge_requires_tool_and_phrase():
    case = {
        "must_call_tools": ["compare_metric"],
        "answer_must_include_any": ["预期差", "毛利率"],
    }
    assert judge_case(case, answer="存在预期差：毛利率横比…", tools_called=["compare_metric", "fetch_evidence"])
    assert not judge_case(case, answer="随便看看", tools_called=["compare_metric"])
    assert not judge_case(case, answer="存在预期差：毛利率", tools_called=["semantic_search"])
```

- [ ] **Step 2: FAIL → 实现 `judge_case` + CLI**

```bash
cd backend && .venv/bin/python scripts/eval_dual_track.py \
  --cases eval/expected_gap_cases_v1.json \
  --old-base http://127.0.0.1:8000 \
  --mode old-only
```

`old-only` 必须先绿（本地/云有后端时）；`both` 在 MCP+harness 就绪后启用。

- [ ] **Step 3: 文档化切流门禁引用**

在脚本 `--help` / 模块 docstring 写死：

1. 新轨通过率 ≥ 旧轨  
2. 旧轨已过案新轨无故失败 = 回归  
3. 失败案轨迹可定位层  
4. embedding 无 Mac 隧道  
5. 连续 **N≥3** 次定时评测无回退  

- [ ] **Step 4: Commit**

```bash
git commit -am "feat(eval): dual-track expected-gap judge and runner"
```

---

### Task 12: 本地烟雾 + 双轨观察 Runbook（文件 only）

**Files:**
- Create: `deploy/dsh/README.md`（或扩展）、`deploy/mcp/DUAL_TRACK_RUNBOOK.md`
- Create: `scripts/smoke_mcp_p0.sh`（curl 调 HTTP + 可选 MCP）
- Modify: root `README.md` 或 `AGENTS.md` **一行**：新轨旁路入口指针（不宣称已切流）

**Interfaces:**
- Produces: 用户按 runbook 在云上起 MCP、本机/云 harness 连同一 MCP；旧入口保持默认

- [ ] **Step 1: 写 `scripts/smoke_mcp_p0.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail
KEY="${KNOWLEDGE_API_KEY:?}"
BASE="${KNOWLEDGE_BASE_URL:-http://127.0.0.1:8000}"
curl -fsS -H "X-API-Key: $KEY" -H 'Content-Type: application/json' \
  -d '{"query":"硅片 毛利率","scope":"entities","top_k":3}' \
  "$BASE/api/v1/knowledge/search/semantic" | head -c 400
echo
curl -fsS -H "X-API-Key: $KEY" -H 'Content-Type: application/json' \
  -d '{"dimension":"毛利率","scope":"硅片","top_k":5}' \
  "$BASE/api/v1/knowledge/metrics/compare" | head -c 400
echo
curl -fsS -H "X-API-Key: $KEY" "$BASE/api/v1/readiness/" | head -c 400
echo
```

- [ ] **Step 2: Runbook 章节**

1. 起 Data MCP（Task 8）  
2. 本机 harness：`MCP_BASE_URL=https://<cloud>/mcp` + API Key  
3. 云端 harness：`MCP_BASE_URL=http://127.0.0.1:8100/mcp`  
4. 跑 `eval_dual_track.py --mode both`  
5. **未达标前默认流量仍走旧 `stream/report`**  

- [ ] **Step 3: Commit**

```bash
git add scripts/smoke_mcp_p0.sh deploy/mcp/DUAL_TRACK_RUNBOOK.md
git commit -m "docs: dual-track smoke and observe runbook"
```

---

### Task 13: P0.5 可选加厚（评测需要时再做；默认可延后）

**Files:**
- Extend: `agent_metrics.py` / MCP tools — `rollup_metric`, `metric_trend`
- Extend: `agent_links.py` — `scan_dimension`, `backlinks`
- Optional: `get_announcement` / `get_irm` / `find_events`（`find_events` 必须用隔离 async runner，防旧事件循环 bug）

**Gate:** 仅当 Task 11 金标显示缺工具导致系统性失败时实施；否则标记 defer，不阻塞第一期验收。

- [ ] **Step 1:** 用失败 case 证明缺哪个工具 → 只加那一个 HTTP+MCP  
- [ ] **Step 2:** 测试 + commit（message: `feat(knowledge): P0.5 <tool> for dual-track eval`）

---

## 切流门禁（实现计划引用；本波不执行切流）

同时满足才允许开 **另文** cutover plan（承 09-29 §9）：

1. `eval_dual_track.py`：新轨通过率 ≥ 旧轨（同一 `expected_gap_cases_v1.json`）  
2. 无关键回归（旧过新不过须 triaged）  
3. 失败案仅凭轨迹可定位 tool / MCP / 模型层  
4. `semantic_search` embedding = chemagent 稳定地址；无 Mac 隧道  
5. 连续 ≥3 次（或覆盖 ≥1 个交易日）定时评测无回退  

未达标：**默认流量仍旧轨**。

---

## Self-review（对照 design）

| Design 要求 | Task |
|---|---|
| 只读 Data MCP P0 | 7–8 |
| HTTP 缺口 semantic/compare/pull | 4–5（+ market 6） |
| dsh + plugins/qingshui 双端 | 2–3, 9–10 |
| 双轨保留旧 Agent | Global Constraints + 12 |
| 轨迹 + 评测对照 | 10–11 |
| 切流门禁写死 | Task 11 docstring + 切流门禁节 |
| 对齐 VS / 不硬切 | Task 2–4 承接 VS；OUT OF SCOPE |
| AGENTS 联通铁律 | Global Constraints + Runbook |
| P0.5 / neo4j 不膨胀 | Task 13 defer |

Placeholder scan: 无 TBD；开放问题已锁定表。

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-10-10-agent-mcp-deepseek-harness.md`.

执行前请用户选择：

1. **Subagent-Driven（推荐）** — 每 Task 新子代理 + 两段审查  
2. **Inline Execution** — 本会话按 executing-plans 批次推进  

默认从 Task 1 开始；云上不可逆步骤仍须用户授权。
