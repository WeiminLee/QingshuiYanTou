# dsh Vertical Slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal (tonight hard):** Cloud dsh headless 「对硅片板块做预期差分析」→ report matching `docs/reports/2026-09-28-silicon-wafer-divergence-v2.md` (横向/纵向/层次 + 判断要点 with EV:). Plugin tools via Knowledge HTTP: `compare_metric`/`metric_trend`/`rollup_metric`/`fetch_evidence` (+ optional semantic, related/propagate). LLM = Boyue deepseek-v4-flash. Wave1-only two tools = FAIL.

**Architecture:** Add read-only `dsh/` git submodule (pin MatDiscovery’s `dsh-v0.1.1-rc.2`) and a new Cordis plugin `plugins/qingshui/` that registers tools via `defineTool` and calls FastAPI Knowledge over HTTP with `X-API-Key`. Because LangChain tools today call Qdrant/Mongo/Neo4j in-process, add a thin Knowledge HTTP endpoint for semantic search; `fetch_evidence` already has `GET /api/v1/knowledge/evidence/{id}`. Prod: dsh web listens `127.0.0.1:3080` on the Knowledge API host; nginx terminates TLS + basic auth and proxies to it. Mac = code/GitHub only.

**Tech Stack:** Node ≥22.19, pnpm 11, TypeScript, tsdown, `@deepseek-ai/dsh-tools` / Cordis (from dsh), Python 3.11+, FastAPI, pytest, httpx, nginx basic auth.

**Spec:** `docs/superpowers/specs/2026-09-29-dsh-agent-runtime-cutover-design.md` (§2 Locked 2026-09-29 evening + full cutover context).

## Global Constraints

- Monorepo: add `dsh/` as **git submodule (read-only)**; create `plugins/qingshui/` — **do NOT copy** `plugins/matdiscovery`.
- Shell: **dsh web**; tonight **do NOT delete `frontend/`**.
- Runtime: **cloud + chemagent only**; Mac = code / git push only.
- Prod: dsh web **same host** as Knowledge API; dsh CLI does **not** support `--host 0.0.0.0` — bind `127.0.0.1:3080`, expose via nginx.
- Sessions: **no migration**; fresh dsh sessions.
- Plugin package name: **`qingshui`** → `plugins/qingshui/`.
- **`dsh-agent-rpc`: NOT this wave.**
- Retain Knowledge FastAPI `/api/v1/knowledge/**`, scheduler, chemagent, storage.
- Auth: **nginx basic auth** for dsh web; Knowledge tools keep **`X-API-Key`** (`settings.knowledge_api_key or settings.api_key`).
- Tonight tools: **≤2** — `semantic_search`, `fetch_evidence` only. **No `resolve` tonight.**
- Tonight acceptance: **vertical slice ONLY** — NOT full P0, NOT delete `frontend/`, NOT archive LangChain.
- Plugin tools **must HTTP** Knowledge API; never open cloud DB ports from Node.
- Copy **patterns** from MatDiscovery (`defineTool`, `cordis.patch.yml`, `scripts/dsh.mjs`, package `dsh.bundle`), not FieldMat/skills/client UI.
- Pin dsh submodule to commit `b150a551b8d465e31e418e1b2eaf5e79bbb7d28e` (`dsh-v0.1.1-rc.2`), same as MatDiscovery.
- **LLM = this repo’s LiteLLM** (not memtensor, not MatDiscovery Boyue):
  - `apiKeyEnv: LLM_API_KEY`
  - `baseURL: http://127.0.0.1:4000/v1` (matches `Settings.llm_base_url` default; prefer `127.0.0.1` in cordis patch)
  - Default chat model: `Settings.llm_model` default **`MiniMax-M2.7-highspeed`** (`backend/app/config.py`)
  - Cloud should set `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` to match whatever LiteLLM serves; cordis patch `baseURL`/model must stay aligned with backend defaults unless overlay overrides.
- Test commands: Python `cd backend && .venv/bin/python -m pytest <path> -v`; Node `node --import tsx --test plugins/qingshui/src/*.test.ts` (after dsh deps exist).
- Each task ends with a commit on branch `feat/dsh-vertical-slice`.
- If `docs/superpowers/**` or plan path ever appears gitignored: `git add -f` (today `docs/superpowers/` is tracked; `.superpowers/` is ignored — do **not** put the plan under `.superpowers/`).

---

## Deploy Authority

| Who | May do |
|---|---|
| **Implementer (agent / Mac)** | Edit repo, run local tests, `git push` to GitHub on `feat/dsh-vertical-slice`. |
| **Implementer (default)** | **MUST NOT** scp, ssh, systemd, or edit live nginx on the cloud host. Group-chat Auto-review often blocks production SSH/scp. |
| **User / 1:1 DM** | Apply cloud steps in Task 7 handoff (pull, build, htpasswd, nginx reload, systemd unit, smoke). |

If a future 1:1 explicitly grants cloud SSH for a named host + commands, that grant overrides this default for that session only — still document every irreversible step before running it.

---

## OUT OF SCOPE tonight

- Do **not** delete or archive `frontend/`.
- Do **not** archive / move `backend/app/reasoning/langchain_agent/**` off main path.
- Do **not** introduce `plugins/core/dsh-agent-rpc`.
- Do **not** migrate P0 tool table beyond the ≤2 listed (no 3rd+ tool: no `resolve`, `expand`, `get_irm`, `tavily_search`, etc.).
- Do **not** add `POST /resolve` or a resolve client/tool tonight.
- Do **not** migrate old Agent sessions / `task_id` / reports into dsh.
- Do **not** fork or edit files under `dsh/` (submodule read-only).
- Do **not** copy MatDiscovery FieldMat / alloy / skills / client UI into `qingshui`.
- Do **not** claim full §9 hard-cutover acceptance.
- Do **not** use memtensor or MatDiscovery Boyue as the default LLM gateway.

---

## Research notes (locked for implementer)

| Item | Finding |
|---|---|
| `semantic_search` LangChain | `backend/app/reasoning/tools/knowledge/semantic_search.py` → in-process `vector_client.semantic_search_entities/chunks` (Qdrant + embedding). **No HTTP today.** |
| `fetch_evidence` LangChain | `…/evidence.py` → in-process `EvidenceService.get_evidence`. **HTTP already exists:** `GET /api/v1/knowledge/evidence/{evidence_id}` (`worker_jobs.py` `evidence_router`, `X-API-Key`). |
| `resolve` LangChain | `…/graph_navigator.py` → Neo4j via `app.core.neo4j_client.run`. **Deferred tonight.** If resolve is added later: extract to `app.knowledge` first — **never** call `graph_navigator._search_entity_by_name` from Knowledge HTTP. |
| Auth helper | `app.knowledge.api._auth.require_api_key` — same as workers. |
| LiteLLM defaults | `Settings.llm_base_url=http://localhost:4000/v1`, `Settings.llm_model=MiniMax-M2.7-highspeed`, key env `LLM_API_KEY`. Cordis patch uses `http://127.0.0.1:4000/v1`. |
| MatDiscovery pin | submodule `https://github.com/deepseek-ai/deepseek-harness.git` @ `b150a551…` |
| dsh web bind | Default `127.0.0.1:3080`; **no** `--host 0.0.0.0`. |
| Existing nginx | `frontend/nginx.conf` is Vue SPA → backend:8000; tonight add **new** stub under `deploy/nginx/`, do not delete Vue conf. |

---

## File Structure

| Path | Responsibility |
|---|---|
| `.gitmodules` | Declare `dsh` submodule URL |
| `dsh/` | Read-only harness checkout (pin commit) |
| `package.json` | Root scripts: `dsh`, `build:plugin`; engines Node ≥22.19 |
| `pnpm-workspace.yaml` | `allowBuilds.esbuild: true` (dsh/pnpm needs) |
| `scripts/dsh.mjs` | Launcher: cwd=repo root, `$REPO_ROOT` patch rewrite, invoke `dsh/apps/cli` via tsx |
| `patches/qingshui.yml` | Empty overlay `[]` for per-checkout overrides |
| `patches/README.md` | One-paragraph how overlays work |
| `plugins/qingshui/package.json` | Bundle name `qingshui`, `dsh.bundle.patch`, `main: lib/index.mjs` |
| `plugins/qingshui/cordis.patch.yml` | Insert plugin + LiteLLM OpenAI-compatible provider + default model |
| `plugins/qingshui/tsconfig.json` | Strict TS for plugin src |
| `plugins/qingshui/tsdown.config.ts` | Bundle `src/index.ts` → `lib/index.mjs` (host only tonight) |
| `plugins/qingshui/src/index.ts` | Cordis `apply`: register tools |
| `plugins/qingshui/src/config.ts` | Schemastery config: `knowledgeBaseUrl`, `knowledgeApiKeyRef`, timeouts |
| `plugins/qingshui/src/knowledge-client.ts` | Thin `fetch` client: semanticSearch / fetchEvidence |
| `plugins/qingshui/src/tools.ts` | `defineTool` for the two tools |
| `plugins/qingshui/src/tool-output.ts` | `renderJson` helper |
| `plugins/qingshui/src/knowledge-client.test.ts` | Node tests with mocked `fetch` |
| `plugins/qingshui/src/tools.test.ts` | Tool execute → client wiring tests |
| `backend/app/knowledge/api/agent_search.py` | **New** HTTP: `POST /search/semantic` only |
| `backend/app/main.py` | Include `agent_search` router |
| `backend/tests/test_agent_search_api.py` | FastAPI TestClient tests for semantic endpoint |
| `deploy/nginx/dsh-web.conf.example` | TLS + `auth_basic` + `proxy_pass http://127.0.0.1:3080` |
| `deploy/dsh/qingshui-dsh.service.example` | systemd user/system unit sketch |
| `deploy/dsh/README.md` | Cloud handoff steps for user |
| `docs/superpowers/specs/2026-09-29-dsh-agent-runtime-cutover-design.md` | Already updated § Locked evening |

---

### Task 1: Branch + dsh submodule + root launcher scaffolding

**Files:**
- Create: `.gitmodules`
- Create: `package.json`
- Create: `pnpm-workspace.yaml`
- Create: `scripts/dsh.mjs`
- Create: `patches/qingshui.yml`
- Create: `patches/README.md`
- Create: `.gitignore` entries only if missing (`node_modules/`, already present)

**Interfaces:**
- Consumes: none
- Produces: `pnpm dsh …` runnable after Task 2 builds plugin and dsh host libs; submodule present at pin

- [ ] **Step 1: Create branch from a clean base**

```bash
cd /Users/lwm/code/QingshuiYanTou
git fetch origin
# Prefer clean main via worktree; do NOT commit unrelated WIP from other branches.
# Worktree path: /Users/lwm/code/QingshuiYanTou.worktrees/dsh-vertical-slice
git worktree add /Users/lwm/code/QingshuiYanTou.worktrees/dsh-vertical-slice -b feat/dsh-vertical-slice origin/main
```

Expected: on `feat/dsh-vertical-slice` in the worktree. Do not commit unrelated WIP from `feat/ingestion-drain-limit-20`.

- [ ] **Step 2: Add dsh submodule pinned to MatDiscovery’s commit**

```bash
git submodule add https://github.com/deepseek-ai/deepseek-harness.git dsh
cd dsh && git checkout b150a551b8d465e31e418e1b2eaf5e79bbb7d28e && cd ..
git add .gitmodules dsh
```

Expected: `git submodule status` shows `b150a551… dsh`.

- [ ] **Step 3: Write root `package.json`**

```json
{
  "name": "qingshui-yantou",
  "private": true,
  "type": "module",
  "engines": {
    "node": ">=22.19.0"
  },
  "scripts": {
    "build:plugin": "tsdown -c plugins/qingshui/tsdown.config.ts",
    "dsh": "node scripts/dsh.mjs",
    "test:plugin": "TSX_TSCONFIG_PATH=$PWD/dsh/tsconfig.base.json node --import tsx --test plugins/qingshui/src/*.test.ts"
  },
  "devDependencies": {
    "tsx": "^4.22.4",
    "tsdown": "^0.22.2",
    "typescript": "^5.9.3",
    "@types/node": "^22.10.0"
  }
}
```

- [ ] **Step 4: Write `pnpm-workspace.yaml`**

```yaml
allowBuilds:
  esbuild: true
```

- [ ] **Step 5: Write `scripts/dsh.mjs`** (MatDiscovery pattern; `$REPO_ROOT` rewrite)

```js
#!/usr/bin/env node
import { spawn } from 'node:child_process'
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { basename, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const repoRoot = resolve(fileURLToPath(new URL('.', import.meta.url)), '..')
const dshDir = resolve(repoRoot, 'dsh')
const generatedDir = join(tmpdir(), 'qingshui-patches', String(process.pid))

function materializePatch(file) {
  let text
  try {
    text = readFileSync(file, 'utf8')
  } catch {
    return file
  }
  if (!text.includes('$REPO_ROOT')) return file
  mkdirSync(generatedDir, { recursive: true })
  const out = join(generatedDir, basename(file))
  writeFileSync(out, text.split('$REPO_ROOT').join(repoRoot))
  return out
}

const raw = process.argv.slice(2)
const args = []
for (let i = 0; i < raw.length; i += 1) {
  const arg = raw[i]
  if (arg === '--patch' && i + 1 < raw.length) {
    args.push('--patch', materializePatch(resolve(process.cwd(), raw[i + 1])))
    i += 1
    continue
  }
  if (arg.startsWith('--patch=')) {
    args.push(`--patch=${materializePatch(resolve(process.cwd(), arg.slice('--patch='.length)))}`)
    continue
  }
  args.push(arg)
}

const child = spawn(process.execPath, ['--import', 'tsx/esm', 'dsh/apps/cli/src/bin.ts', ...args], {
  cwd: repoRoot,
  env: { ...process.env, TSX_TSCONFIG_PATH: join(dshDir, 'tsconfig.json') },
  stdio: 'inherit',
})

child.on('error', (error) => {
  process.stderr.write(`dsh launcher: ${error.message}\n`)
  process.exit(1)
})

child.on('exit', (code, signal) => {
  if (signal) process.kill(process.pid, signal)
  else process.exit(code ?? 0)
})
```

- [ ] **Step 6: Write empty overlay `patches/qingshui.yml` + README**

`patches/qingshui.yml`:

```yaml
# Per-checkout overlay. Composition lives in plugins/qingshui/cordis.patch.yml.
[]
```

`patches/README.md`:

```markdown
# patches

`cordis.patch.yml` overlays applied with `pnpm dsh --profile web --patch ./patches/<file>.yml`.
Tonight composition is inside `plugins/qingshui/cordis.patch.yml` after `dsh plugin add`.
Keep `patches/qingshui.yml` empty unless a checkout needs a local override.
```

- [ ] **Step 7: Install root + build dsh host libs (local Mac)**

```bash
pnpm install
cd dsh && CI=true pnpm_config_verify_deps_before_run=false pnpm install && pnpm run build:lib:host && cd ..
# For web UI acceptance later also need full web build:
# cd dsh && CI=true pnpm_config_verify_deps_before_run=false npm run build && cd ..
```

Expected: `dsh/packages/**/lib` host artifacts exist; no edits inside `dsh/` committed except submodule pointer.

- [ ] **Step 8: Commit**

```bash
git add .gitmodules dsh package.json pnpm-workspace.yaml pnpm-lock.yaml scripts/dsh.mjs patches/
git commit -m "$(cat <<'EOF'
chore: add dsh submodule pin + root launcher scaffolding

Pin deepseek-harness at dsh-v0.1.1-rc.2 for tonight's vertical slice.
EOF
)"
```

---

### Task 2: Empty `plugins/qingshui` Cordis bundle (loads, no tools yet)

**Files:**
- Create: `plugins/qingshui/package.json`
- Create: `plugins/qingshui/cordis.patch.yml`
- Create: `plugins/qingshui/tsconfig.json`
- Create: `plugins/qingshui/tsdown.config.ts`
- Create: `plugins/qingshui/src/index.ts`
- Create: `plugins/qingshui/src/config.ts`
- Create: `plugins/qingshui/README.md`

**Interfaces:**
- Consumes: Task 1 launcher + dsh pin
- Produces: installable bundle name `qingshui`; `export async function apply(ctx, config)`; Config fields `knowledgeBaseUrl: string`, `knowledgeApiKeyRef: string`, `requestTimeoutMs: number`

- [ ] **Step 1: Write `plugins/qingshui/package.json`**

```json
{
  "name": "qingshui",
  "version": "0.1.0",
  "private": true,
  "license": "UNLICENSED",
  "type": "module",
  "description": "清水投研 Cordis plugin: Knowledge HTTP tools for dsh web (vertical slice).",
  "main": "lib/index.mjs",
  "exports": {
    ".": { "default": "./lib/index.mjs" },
    "./package.json": "./package.json"
  },
  "files": ["lib/index.mjs", "cordis.patch.yml"],
  "dsh": {
    "bundle": {
      "patch": "./cordis.patch.yml"
    }
  }
}
```

- [ ] **Step 2: Write `plugins/qingshui/cordis.patch.yml`**

Use this repo’s LiteLLM (do **not** hardcode memtensor or MatDiscovery Boyue). Align with `Settings.llm_*` defaults; cloud overlays may override via `LLM_*` env + patch replace:

```yaml
- insert:
    - id: qingshui
      name: qingshui
- id: llm-pi-ai
  name: '@deepseek-ai/dsh-llm-pi-ai'
  config:
    providers:
      qingshui:
        displayName: Qingshui LiteLLM
        apiKeyEnv: LLM_API_KEY
        api: openai-completions
        baseURL: http://127.0.0.1:4000/v1
        models:
          - id: MiniMax-M2.7-highspeed
            name: MiniMax M2.7 Highspeed
            contextWindow: 131072
            maxTokens: 8192
- id: agent-default-model
  name: '@deepseek-ai/dsh-agent-default-model'
  config:
    provider: qingshui
    model: MiniMax-M2.7-highspeed
```

Note: a later patch that replaces `llm-pi-ai` / `agent-default-model` must restate the **entire** `config` (Cordis patch replaces whole config). Cloud should set `LLM_BASE_URL`/`LLM_API_KEY`/`LLM_MODEL` to match whatever LiteLLM serves; cordis `baseURL`/model stay aligned with backend defaults unless overlay overrides.

- [ ] **Step 3: Write `tsconfig.json` + `tsdown.config.ts`**

`plugins/qingshui/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "Bundler",
    "lib": ["ES2023"],
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "skipLibCheck": true,
    "esModuleInterop": true,
    "allowImportingTsExtensions": true,
    "verbatimModuleSyntax": true,
    "noEmit": true,
    "types": ["node"]
  },
  "include": ["src"]
}
```

`plugins/qingshui/tsdown.config.ts`:

```ts
import { join } from 'node:path'
import { defineConfig } from 'tsdown'

const here = import.meta.dirname

export default defineConfig([
  {
    entry: [join(here, 'src/index.ts')],
    outDir: join(here, 'lib'),
    format: ['esm'],
    platform: 'node',
    dts: false,
    external: [/^@deepseek-ai\//, /^node:/],
  },
])
```

- [ ] **Step 4: Write `src/config.ts`**

```ts
import z from '@deepseek-ai/schemastery'

export interface Config {
  knowledgeBaseUrl: string
  knowledgeApiKeyRef: string
  requestTimeoutMs: number
}

export const Config: z<Config> = z.object({
  knowledgeBaseUrl: z.string().default('http://127.0.0.1:8080'),
  knowledgeApiKeyRef: z.string().default('KNOWLEDGE_API_KEY'),
  requestTimeoutMs: z.number().default(30000),
})
```

- [ ] **Step 5: Write minimal `src/index.ts` (no tools yet)**

```ts
import type { Context } from '@deepseek-ai/cordis'
import { Config } from './config.ts'
import type { Config as QingshuiConfig } from './config.ts'

export const name = 'qingshui'
export const inject = ['tools']

export { Config }
export type { QingshuiConfig }

export function apply(ctx: Context, config: QingshuiConfig): void {
  ctx.logger.info(
    'qingshui: loaded (tools come in later tasks) base=%c',
    config.knowledgeBaseUrl,
  )
}
```

- [ ] **Step 6: Write short `plugins/qingshui/README.md`**

```markdown
# qingshui

清水投研 dsh Cordis 插件（今晚 vertical slice）。

## Install

```sh
pnpm run build:plugin
pnpm dsh plugin --profile web add ./plugins/qingshui
LLM_API_KEY=… KNOWLEDGE_API_KEY=… pnpm dsh --profile web --no-open
```

LLM: this repo LiteLLM (`LLM_API_KEY` → `http://127.0.0.1:4000/v1`, model `MiniMax-M2.7-highspeed`).
Tools call Knowledge HTTP with `X-API-Key`. Do not copy matdiscovery.
```

- [ ] **Step 7: Build + install into web profile**

```bash
pnpm run build:plugin
pnpm dsh plugin --profile web add ./plugins/qingshui
pnpm dsh --profile web --dump-config 2>&1 | head -80
```

Expected: dump shows a `# == qingshui` (or similar) bundle layer and insert id `qingshui`.

- [ ] **Step 8: Commit**

```bash
git add plugins/qingshui
git commit -m "$(cat <<'EOF'
feat(qingshui): scaffold Cordis plugin bundle for dsh web

Empty host plugin + LiteLLM patch; tools land next.
EOF
)"
```

---

### Task 3: Knowledge HTTP — `POST /api/v1/knowledge/search/semantic`

**Files:**
- Create: `backend/app/knowledge/api/agent_search.py`
- Modify: `backend/app/main.py` (include router)
- Create: `backend/tests/test_agent_search_api.py`

**Interfaces:**
- Consumes: `vector_client.semantic_search_entities` / `semantic_search_chunks`; `_auth.require_api_key`
- Produces: HTTP contract used by plugin client:

`POST /api/v1/knowledge/search/semantic`  
Header: `X-API-Key`  
Body: `{ "query": str, "scope": "entities"|"chunks"|"both" = "entities", "ts_code": str|null = null, "top_k": int = 5 }`  
200: same shape as LangChain tool (`entities` / `chunks` lists with shaped fields)  
401 without key

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/test_agent_search_api.py
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import settings
from app.knowledge.api.agent_search import router as agent_search_router
from app.knowledge.vector_client import SearchResult

HEADERS = {"X-API-Key": "test-key"}


@pytest.fixture(autouse=True)
def _api_key(monkeypatch):
    monkeypatch.setattr(settings, "knowledge_api_key", "test-key", raising=False)
    monkeypatch.setattr(settings, "api_key", "", raising=False)


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(agent_search_router)
    return TestClient(app)


def _entity_hit():
    return SearchResult(
        id="uuid-point-1",
        score=0.91,
        payload={
            "entity_id": "C_宁德时代",
            "entity_name": "宁德时代",
            "entity_type": "Company",
            "ts_code": "300750.SZ",
        },
    )


def _chunk_hit():
    return SearchResult(
        id="uuid-point-2",
        score=0.83,
        payload={
            "evidence_id": "EV:abc123",
            "content": "公司预计2024年产能翻倍。",
            "source_type": "announcement",
            "source_name": "2024年度报告",
        },
    )


def test_semantic_requires_api_key(client):
    r = client.post("/api/v1/knowledge/search/semantic", json={"query": "宁德"})
    assert r.status_code == 401


def test_semantic_entities_shapes_graph_id(client):
    with patch(
        "app.knowledge.api.agent_search.semantic_search_entities",
        return_value=[_entity_hit()],
    ):
        r = client.post(
            "/api/v1/knowledge/search/semantic",
            headers=HEADERS,
            json={"query": "宁德 电池龙头", "scope": "entities"},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["entities"][0]["entity_id"] == "C_宁德时代"
    assert "chunks" not in body


def test_semantic_chunks_and_both(client):
    with (
        patch(
            "app.knowledge.api.agent_search.semantic_search_entities",
            return_value=[_entity_hit()],
        ),
        patch(
            "app.knowledge.api.agent_search.semantic_search_chunks",
            return_value=[_chunk_hit()],
        ),
    ):
        r = client.post(
            "/api/v1/knowledge/search/semantic",
            headers=HEADERS,
            json={"query": "产能", "scope": "both", "top_k": 3},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["chunks"][0]["evidence_id"] == "EV:abc123"
    assert body["chunks"][0]["snippet"].startswith("公司预计")


def test_semantic_invalid_scope(client):
    r = client.post(
        "/api/v1/knowledge/search/semantic",
        headers=HEADERS,
        json={"query": "x", "scope": "nope"},
    )
    assert r.status_code == 400
```

- [ ] **Step 2: Run tests — expect fail (module missing)**

```bash
cd backend && .venv/bin/python -m pytest tests/test_agent_search_api.py -v
```

Expected: FAIL import `agent_search` / collection empty.

- [ ] **Step 3: Implement `agent_search.py` (semantic only)**

```python
"""Agent-facing Knowledge search HTTP (dsh plugin boundary)."""
from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from app.knowledge.api._auth import require_api_key
from app.knowledge.vector_client import (
    semantic_search_chunks,
    semantic_search_entities,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/knowledge", tags=["知识 Agent 检索"])

_VALID_SCOPES = frozenset({"entities", "chunks", "both"})
_SNIPPET_MAX = 200


class SemanticSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    scope: Literal["entities", "chunks", "both"] = "entities"
    ts_code: str | None = Field(default=None, max_length=32)
    top_k: int = Field(default=5, ge=1, le=50)


def _shape_entity(r) -> dict[str, Any]:
    payload = r.payload or {}
    return {
        "entity_id": payload.get("entity_id") or r.id,
        "name": payload.get("entity_name", ""),
        "type": payload.get("entity_type", ""),
        "ts_code": payload.get("ts_code", ""),
        "score": round(float(r.score), 4),
    }


def _shape_chunk(r) -> dict[str, Any]:
    payload = r.payload or {}
    content = payload.get("content", "") or ""
    snippet = content[:_SNIPPET_MAX] + ("…" if len(content) > _SNIPPET_MAX else "")
    return {
        "evidence_id": payload.get("evidence_id", ""),
        "snippet": snippet,
        "source_type": payload.get("source_type", ""),
        "source_name": payload.get("source_name", ""),
        "score": round(float(r.score), 4),
    }


@router.post("/search/semantic")
async def search_semantic(
    req: SemanticSearchRequest,
    x_api_key: str | None = Header(default=None),
):
    require_api_key(x_api_key)
    if req.scope not in _VALID_SCOPES:
        raise HTTPException(400, f"无效 scope={req.scope}")
    result: dict[str, Any] = {}
    if req.scope in ("entities", "both"):
        try:
            hits = semantic_search_entities(req.query, ts_code=req.ts_code, top_k=req.top_k)
            result["entities"] = [_shape_entity(h) for h in hits]
        except Exception as e:  # noqa: BLE001
            logger.warning("semantic_search entities 失败: %s", e)
            result["entities"] = []
    if req.scope in ("chunks", "both"):
        try:
            hits = semantic_search_chunks(req.query, ts_code=req.ts_code, top_k=req.top_k)
            result["chunks"] = [_shape_chunk(h) for h in hits]
        except Exception as e:  # noqa: BLE001
            logger.warning("semantic_search chunks 失败: %s", e)
            result["chunks"] = []
    return result
```

- [ ] **Step 4: Register router in `main.py`**

Add import next to other knowledge routers:

```python
from app.knowledge.api.agent_search import router as agent_search_router
```

Near `app.include_router(evidence_router)`:

```python
app.include_router(agent_search_router)
```

(Auth is per-handler via `require_api_key`, same as worker routers.)

- [ ] **Step 5: Run tests — expect pass**

```bash
cd backend && .venv/bin/python -m pytest tests/test_agent_search_api.py -v
```

Expected: PASS for the four semantic tests.

- [ ] **Step 6: Commit**

```bash
git add backend/app/knowledge/api/agent_search.py backend/app/main.py backend/tests/test_agent_search_api.py
git commit -m "$(cat <<'EOF'
feat(knowledge): add POST /search/semantic for dsh plugin tools

HTTP shape matches LangChain semantic_search; X-API-Key required.
EOF
)"
```

---

### Task 4: Plugin Knowledge HTTP client + config resolution

**Files:**
- Create: `plugins/qingshui/src/knowledge-client.ts`
- Create: `plugins/qingshui/src/knowledge-client.test.ts`
- Modify: `plugins/qingshui/src/config.ts` if needed (already defined)
- Create: `plugins/qingshui/src/tool-output.ts`

**Interfaces:**
- Consumes: Config (`knowledgeBaseUrl`, `knowledgeApiKeyRef`, `requestTimeoutMs`); process.env[apiKeyRef]
- Produces:

```ts
export interface KnowledgeClient {
  semanticSearch(input: {
    query: string
    scope?: 'entities' | 'chunks' | 'both'
    ts_code?: string | null
    top_k?: number
  }): Promise<Record<string, unknown>>
  fetchEvidence(evidenceId: string): Promise<Record<string, unknown>>
}
export function createKnowledgeClient(options: {
  baseUrl: string
  apiKey: string
  timeoutMs: number
  fetchImpl?: typeof fetch
}): KnowledgeClient
```

- [ ] **Step 1: Write failing client test**

```ts
// plugins/qingshui/src/knowledge-client.test.ts
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createKnowledgeClient } from './knowledge-client.ts'

test('semanticSearch posts JSON with X-API-Key', async () => {
  const calls: Array<{ url: string; init: RequestInit }> = []
  const fetchImpl: typeof fetch = async (url, init) => {
    calls.push({ url: String(url), init: init ?? {} })
    return new Response(JSON.stringify({ entities: [] }), { status: 200 })
  }
  const client = createKnowledgeClient({
    baseUrl: 'http://knowledge.test',
    apiKey: 'k',
    timeoutMs: 5000,
    fetchImpl,
  })
  await client.semanticSearch({ query: '宁德', scope: 'entities' })
  assert.equal(calls.length, 1)
  assert.equal(calls[0].url, 'http://knowledge.test/api/v1/knowledge/search/semantic')
  assert.equal((calls[0].init.headers as Record<string, string>)['X-API-Key'], 'k')
  assert.equal(calls[0].init.method, 'POST')
})

test('fetchEvidence GETs evidence id', async () => {
  const calls: string[] = []
  const fetchImpl: typeof fetch = async (url) => {
    calls.push(String(url))
    return new Response(JSON.stringify({ evidence_id: 'EV:1', text_excerpt: 'hi' }), { status: 200 })
  }
  const client = createKnowledgeClient({
    baseUrl: 'http://knowledge.test/',
    apiKey: 'k',
    timeoutMs: 5000,
    fetchImpl,
  })
  const doc = await client.fetchEvidence('EV:1')
  assert.equal(calls[0], 'http://knowledge.test/api/v1/knowledge/evidence/EV%3A1')
  assert.equal(doc.evidence_id, 'EV:1')
})

test('non-2xx throws with status', async () => {
  const fetchImpl: typeof fetch = async () => new Response('nope', { status: 401 })
  const client = createKnowledgeClient({
    baseUrl: 'http://knowledge.test',
    apiKey: 'bad',
    timeoutMs: 5000,
    fetchImpl,
  })
  await assert.rejects(() => client.semanticSearch({ query: 'x' }), /401/)
})
```

- [ ] **Step 2: Run — expect fail**

```bash
pnpm test:plugin
```

Expected: FAIL cannot find module / exports.

- [ ] **Step 3: Implement client + render helper**

`plugins/qingshui/src/tool-output.ts`:

```ts
import type { JsonValue } from '@deepseek-ai/dsh-tools'

export function renderJson(value: JsonValue): Array<{ type: 'text'; text: string }> {
  return [{ type: 'text', text: JSON.stringify(value, null, 2) }]
}
```

`plugins/qingshui/src/knowledge-client.ts`:

```ts
export interface KnowledgeClient {
  semanticSearch(input: {
    query: string
    scope?: 'entities' | 'chunks' | 'both'
    ts_code?: string | null
    top_k?: number
  }): Promise<Record<string, unknown>>
  fetchEvidence(evidenceId: string): Promise<Record<string, unknown>>
}

export function createKnowledgeClient(options: {
  baseUrl: string
  apiKey: string
  timeoutMs: number
  fetchImpl?: typeof fetch
}): KnowledgeClient {
  const base = options.baseUrl.replace(/\/$/, '')
  const fetchImpl = options.fetchImpl ?? fetch

  async function request(path: string, init: RequestInit): Promise<unknown> {
    const ctrl = new AbortController()
    const timer = setTimeout(() => ctrl.abort(), options.timeoutMs)
    try {
      const res = await fetchImpl(`${base}${path}`, {
        ...init,
        signal: ctrl.signal,
        headers: {
          'Content-Type': 'application/json',
          'X-API-Key': options.apiKey,
          ...(init.headers ?? {}),
        },
      })
      if (!res.ok) {
        const text = await res.text().catch(() => '')
        throw new Error(`Knowledge API ${res.status}: ${text.slice(0, 200)}`)
      }
      return await res.json()
    } finally {
      clearTimeout(timer)
    }
  }

  return {
    semanticSearch(input) {
      return request('/api/v1/knowledge/search/semantic', {
        method: 'POST',
        body: JSON.stringify({
          query: input.query,
          scope: input.scope ?? 'entities',
          ts_code: input.ts_code ?? null,
          top_k: input.top_k ?? 5,
        }),
      }) as Promise<Record<string, unknown>>
    },
    fetchEvidence(evidenceId) {
      return request(`/api/v1/knowledge/evidence/${encodeURIComponent(evidenceId)}`, {
        method: 'GET',
      }) as Promise<Record<string, unknown>>
    },
  }
}

export function resolveApiKey(ref: string): string {
  const name = ref.trim() || 'KNOWLEDGE_API_KEY'
  return (process.env[name] ?? '').trim()
}
```

- [ ] **Step 4: Run tests — expect pass**

```bash
pnpm test:plugin
```

Expected: knowledge-client tests PASS (tools tests may still be absent).

- [ ] **Step 5: Commit**

```bash
git add plugins/qingshui/src/knowledge-client.ts plugins/qingshui/src/knowledge-client.test.ts plugins/qingshui/src/tool-output.ts plugins/qingshui/src/config.ts
git commit -m "$(cat <<'EOF'
feat(qingshui): add Knowledge HTTP client with mocked fetch tests

semanticSearch / fetchEvidence over X-API-Key (no resolve tonight).
EOF
)"
```

---

### Task 5: Register ≤2 tools on the plugin

**Files:**
- Create: `plugins/qingshui/src/tools.ts`
- Create: `plugins/qingshui/src/tools.test.ts`
- Modify: `plugins/qingshui/src/index.ts`

**Interfaces:**
- Consumes: `createKnowledgeClient`, `resolveApiKey`, Config
- Produces: tools named exactly `semantic_search`, `fetch_evidence`

- [ ] **Step 1: Write failing tools test**

```ts
// plugins/qingshui/src/tools.test.ts
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { formatEvidenceText, installQingshuiTools } from './tools.ts'
import type { KnowledgeClient } from './knowledge-client.ts'

test('formatEvidenceText truncates long excerpt', () => {
  const text = formatEvidenceText({
    evidence_id: 'EV:1',
    source_type: 'announcement',
    source_name: 'x',
    publish_date: '2024-01-01',
    confidence: 0.9,
    text_excerpt: 'a'.repeat(9000),
  })
  assert.match(text, /EV:1/)
  assert.match(text, /原文过长已截断/)
  assert.ok(text.length < 9000)
})

test('installQingshuiTools registers two names', () => {
  const registered: string[] = []
  const fakeCtx = {
    inject(_deps: string[], fn: (c: { tools: { register: (t: { name: string }) => void } }) => void) {
      fn({
        tools: {
          register(tool) {
            registered.push(tool.name)
          },
        },
      })
    },
  }
  const client: KnowledgeClient = {
    async semanticSearch() { return {} },
    async fetchEvidence() { return {} },
  }
  installQingshuiTools(fakeCtx as never, { client: () => client })
  assert.deepEqual(registered.sort(), ['fetch_evidence', 'semantic_search'])
})
```

- [ ] **Step 2: Run — expect fail**

```bash
pnpm test:plugin
```

- [ ] **Step 3: Implement `tools.ts` + wire `index.ts`**

```ts
// plugins/qingshui/src/tools.ts
import type { Context } from '@deepseek-ai/cordis'
import { defineTool } from '@deepseek-ai/dsh-tools'
import type { JsonValue } from '@deepseek-ai/dsh-tools'
import type { KnowledgeClient } from './knowledge-client.ts'
import { renderJson } from './tool-output.ts'

const MAX_EVIDENCE_TEXT = 8000

export function formatEvidenceText(doc: Record<string, unknown> | null | undefined): string {
  if (!doc) return '未找到该证据记录（可能 evidence_id 无效或数据已过期）。'
  let text = String(doc.text_excerpt ?? '(无文本内容)') || '(无文本内容)'
  if (text.length > MAX_EVIDENCE_TEXT) {
    text =
      text.slice(0, MAX_EVIDENCE_TEXT) +
      `\n...[原文过长已截断：共 ${text.length} 字符，仅显示前 ${MAX_EVIDENCE_TEXT} 字符]`
  }
  const lines = [
    `证据 ID: ${doc.evidence_id ?? 'N/A'}`,
    `来源类型: ${doc.source_type ?? 'N/A'}`,
    `来源名称: ${doc.source_name ?? 'N/A'}`,
    `发布时间: ${doc.publish_date ?? 'N/A'}`,
    `置信度: ${doc.confidence ?? 'N/A'}`,
    '--- 原始文本 ---',
    text,
  ]
  const subject = (doc.subject_hint as Record<string, unknown> | undefined) ?? {}
  if (subject.ts_code) lines.splice(2, 0, `关联股票: ${subject.ts_code}`)
  return lines.join('\n')
}

export interface ToolInstallOptions {
  client: () => KnowledgeClient | undefined
}

export function installQingshuiTools(ctx: Context, options: ToolInstallOptions): void {
  ctx.inject(['tools'], (tctx) => {
    tctx.tools.register(defineTool({
      name: 'semantic_search',
      description:
        '语义向量检索（前置探查）：模糊搜索实体/证据片段。scope=entities|chunks|both。' +
        '拿到 evidence_id 后用 fetch_evidence 拉取原文。',
      parameters: {
        query: { type: 'string', required: true, description: '自然语言检索词' },
        scope: { type: 'string', description: 'entities(默认)|chunks|both' },
        ts_code: { type: 'string', description: '可选股票代码如 300750.SZ' },
        top_k: { type: 'json', description: '每类返回条数，默认 5' },
      },
      output: { schema: { type: 'json' }, render: (_args, value) => renderJson(value) },
      async execute(args) {
        const client = options.client()
        if (!client) return { error: 'Knowledge client not configured (set knowledgeBaseUrl + KNOWLEDGE_API_KEY)' } as unknown as JsonValue
        return await client.semanticSearch({
          query: String(args.query ?? ''),
          scope: (args.scope as 'entities' | 'chunks' | 'both' | undefined) ?? 'entities',
          ts_code: args.ts_code ? String(args.ts_code) : null,
          top_k: typeof args.top_k === 'number' ? args.top_k : 5,
        }) as unknown as JsonValue
      },
    }))

    tctx.tools.register(defineTool({
      name: 'fetch_evidence',
      description: '按 evidence_id（EV:…）拉取 Mongo 证据原文与来源元数据。',
      parameters: {
        evidence_id: { type: 'string', required: true, description: '证据 ID，格式 EV:…' },
      },
      output: {
        schema: { type: 'string' },
        render: (_args, value) => [{ type: 'text', text: String(value) }],
      },
      async execute(args) {
        const client = options.client()
        if (!client) return 'Knowledge client not configured'
        try {
          const doc = await client.fetchEvidence(String(args.evidence_id ?? ''))
          return formatEvidenceText(doc)
        } catch (e) {
          return `证据查询失败: ${e instanceof Error ? e.message : String(e)}`
        }
      },
    }))
  })
}
```

`plugins/qingshui/src/index.ts`:

```ts
import type { Context } from '@deepseek-ai/cordis'
import { Config } from './config.ts'
import type { Config as QingshuiConfig } from './config.ts'
import { createKnowledgeClient, resolveApiKey } from './knowledge-client.ts'
import type { KnowledgeClient } from './knowledge-client.ts'
import { installQingshuiTools } from './tools.ts'

export const name = 'qingshui'
export const inject = ['tools']

export { Config }
export type { QingshuiConfig }

export function apply(ctx: Context, config: QingshuiConfig): void {
  let client: KnowledgeClient | undefined

  const rebuild = (): void => {
    const apiKey = resolveApiKey(config.knowledgeApiKeyRef)
    if (!apiKey || !config.knowledgeBaseUrl.trim()) {
      client = undefined
      ctx.logger.warn('qingshui: Knowledge client disabled (missing URL or API key env %c)', config.knowledgeApiKeyRef)
      return
    }
    client = createKnowledgeClient({
      baseUrl: config.knowledgeBaseUrl.trim(),
      apiKey,
      timeoutMs: config.requestTimeoutMs,
    })
    ctx.logger.info('qingshui: Knowledge client ready → %c', config.knowledgeBaseUrl.trim())
  }

  rebuild()
  installQingshuiTools(ctx, { client: () => client })
}
```

Optionally extend `cordis.patch.yml` plugin row with config:

```yaml
- insert:
    - id: qingshui
      name: qingshui
      config:
        knowledgeBaseUrl: http://127.0.0.1:8080
        knowledgeApiKeyRef: KNOWLEDGE_API_KEY
        requestTimeoutMs: 30000
```

On cloud same host, `http://127.0.0.1:8080` (or whatever backend compose maps) is correct.

- [ ] **Step 4: Rebuild, reinstall, test**

```bash
pnpm run build:plugin
pnpm dsh plugin --profile web add ./plugins/qingshui
pnpm test:plugin
```

Expected: all plugin tests PASS; profile still dumps `qingshui`.

- [ ] **Step 5: Commit**

```bash
git add plugins/qingshui
git commit -m "$(cat <<'EOF'
feat(qingshui): register semantic_search and fetch_evidence tools

Tools call Knowledge HTTP only; evidence text truncated like LangChain.
EOF
)"
```

---

### Task 6: Local smoke script (no cloud SSH)

**Files:**
- Create: `scripts/smoke-dsh-vertical-slice.sh`
- Modify: `plugins/qingshui/README.md` (smoke section)

**Interfaces:**
- Consumes: running Knowledge API (local docker or cloud URL), env `KNOWLEDGE_API_KEY`, `LLM_API_KEY`
- Produces: exit 0 when HTTP semantic + evidence endpoints respond; documents manual dsh web chat check

- [ ] **Step 1: Write smoke script**

```bash
#!/usr/bin/env bash
# Local/Mac smoke for tonight vertical slice HTTP boundary (not full chat).
set -euo pipefail
BASE="${KNOWLEDGE_API_URL:-http://127.0.0.1:8080}"
KEY="${KNOWLEDGE_API_KEY:?set KNOWLEDGE_API_KEY}"
HDR=(-H "X-API-Key: $KEY" -H "Content-Type: application/json")

echo "[1] semantic_search entities"
curl -fsS "${HDR[@]}" -d '{"query":"宁德时代","scope":"entities","top_k":3}' \
  "$BASE/api/v1/knowledge/search/semantic" | head -c 500
echo

echo "[2] semantic_search chunks"
CHUNKS=$(curl -fsS "${HDR[@]}" -d '{"query":"产能","scope":"chunks","top_k":1}' \
  "$BASE/api/v1/knowledge/search/semantic")
echo "$CHUNKS" | head -c 500
echo
EV=$(python3 -c 'import json,sys; d=json.load(sys.stdin); print((d.get("chunks") or [{}])[0].get("evidence_id",""))' <<<"$CHUNKS")
if [[ -n "$EV" ]]; then
  echo "[3] fetch_evidence $EV"
  curl -fsS -H "X-API-Key: $KEY" "$BASE/api/v1/knowledge/evidence/$(python3 -c 'import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1], safe=""))' "$EV")" | head -c 400
  echo
else
  echo "[3] skip fetch_evidence (no chunk hit — empty index OK for wiring check)"
fi

echo "HTTP boundary OK (semantic_search → fetch_evidence). Manual: LLM_API_KEY=… pnpm dsh --profile web --no-open then chat."
```

```bash
chmod +x scripts/smoke-dsh-vertical-slice.sh
```

- [ ] **Step 2: Run against whatever Knowledge is reachable**

```bash
KNOWLEDGE_API_URL=http://127.0.0.1:8080 KNOWLEDGE_API_KEY=… ./scripts/smoke-dsh-vertical-slice.sh
```

Expected: steps 1–2 return JSON (chunks/evidence may be empty on empty DB — still 200). Skip if no local Knowledge; commit script anyway.

- [ ] **Step 3: Commit**

```bash
git add scripts/smoke-dsh-vertical-slice.sh plugins/qingshui/README.md
git commit -m "$(cat <<'EOF'
chore: add HTTP smoke script for dsh vertical slice boundary
EOF
)"
```

---

### Task 7: Deploy notes + nginx basic-auth stub (files only; user applies)

**Files:**
- Create: `deploy/nginx/dsh-web.conf.example`
- Create: `deploy/dsh/qingshui-dsh.service.example`
- Create: `deploy/dsh/README.md`

**Interfaces:**
- Consumes: none from code
- Produces: copy-paste cloud handoff for user / 1:1 DM

- [ ] **Step 1: Write nginx example**

```nginx
# deploy/nginx/dsh-web.conf.example
# Place under /etc/nginx/conf.d/ after filling server_name + cert paths + htpasswd.
# dsh listens 127.0.0.1:3080 only — do not expose 3080 publicly.

server {
    listen 443 ssl http2;
    server_name chat.example.com;  # REPLACE

    ssl_certificate     /etc/nginx/ssl/cert.pem;   # REPLACE
    ssl_certificate_key /etc/nginx/ssl/key.pem;  # REPLACE

    # Basic auth for humans (Login page retired with Vue later; tonight stub).
    auth_basic           "Qingshui dsh";
    auth_basic_user_file /etc/nginx/qingshui-dsh.htpasswd;  # htpasswd -nb USER PASS

    location / {
        proxy_pass http://127.0.0.1:3080;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 3600s;
        proxy_buffering off;
    }
}
```

- [ ] **Step 2: Write systemd example**

```ini
# deploy/dsh/qingshui-dsh.service.example
[Unit]
Description=Qingshui dsh web (vertical slice)
After=network.target docker.service
Wants=docker.service

[Service]
Type=simple
WorkingDirectory=/opt/QingshuiYanTou
Environment=LLM_API_KEY=REPLACE
Environment=LLM_BASE_URL=http://127.0.0.1:4000/v1
Environment=LLM_MODEL=MiniMax-M2.7-highspeed
Environment=KNOWLEDGE_API_KEY=REPLACE
# Same-host Knowledge (docker-compose maps 8080→backend:8000)
Environment=DSH_HOME=/var/lib/qingshui-dsh
ExecStart=/usr/bin/pnpm dsh --profile web --no-open
Restart=on-failure
RestartSec=5
User=qingshui
Group=qingshui

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 3: Write `deploy/dsh/README.md` (user handoff)**

```markdown
# Cloud handoff — dsh vertical slice (user / 1:1 DM)

Implementer **pushes GitHub only** by default. Apply on Knowledge API host:

1. `git fetch && git checkout feat/dsh-vertical-slice && git submodule update --init --recursive`
2. `cd dsh && CI=true pnpm install && npm run build && cd ..`
3. `pnpm install && pnpm run build:plugin`
4. `pnpm dsh plugin --profile web add ./plugins/qingshui`
5. Ensure `plugins/qingshui` config `knowledgeBaseUrl=http://127.0.0.1:8080` (or local backend URL) and export `KNOWLEDGE_API_KEY` + `LLM_API_KEY` (and optionally `LLM_BASE_URL` / `LLM_MODEL` to match LiteLLM).
6. `sudo htpasswd -c /etc/nginx/qingshui-dsh.htpasswd <user>`
7. Install `deploy/nginx/dsh-web.conf.example` → reload nginx.
8. Install systemd unit (or `tmux`/`systemd-run`) from `qingshui-dsh.service.example`; start dsh.
9. Browser: `https://<host>/` → basic auth → dsh chat → ask to `semantic_search` then `fetch_evidence`.
10. Confirm Vue `frontend/` still present and LangChain agent still startable (tonight does not cut over).

Rollback: stop systemd unit; remove nginx site; leave submodule/plugin in git (no data migration).
```

- [ ] **Step 4: Commit**

```bash
git add deploy/nginx/dsh-web.conf.example deploy/dsh/
git commit -m "$(cat <<'EOF'
docs(deploy): nginx basic-auth + systemd stubs for dsh web slice

Cloud apply is user handoff; implementer pushes GitHub only.
EOF
)"
```

---

### Task 8: Spec/plan pointers + AGENTS one-liner (docs only)

**Files:**
- Modify: `AGENTS.md` (short pointer under 联通铁律 / new subsection — do not rewrite iron rules)
- Ensure design spec Locked evening section is present (already written)

- [ ] **Step 1: Append pointer to `AGENTS.md`**

```markdown
## dsh vertical slice (2026-09-29)

- Design: `docs/superpowers/specs/2026-09-29-dsh-agent-runtime-cutover-design.md`
- Plan: `docs/superpowers/plans/2026-09-29-dsh-vertical-slice.md`
- Tonight: dsh web + `plugins/qingshui` + ≤2 Knowledge HTTP tools (`semantic_search`, `fetch_evidence`); **do not** delete `frontend/` or archive LangChain.
- LLM: this repo LiteLLM (`LLM_API_KEY` → `http://127.0.0.1:4000/v1`, model `MiniMax-M2.7-highspeed`).
- Cloud dsh apply: `deploy/dsh/README.md` (user handoff).
```

- [ ] **Step 2: Commit plan + spec + AGENTS**

```bash
git add AGENTS.md docs/superpowers/specs/2026-09-29-dsh-agent-runtime-cutover-design.md docs/superpowers/plans/2026-09-29-dsh-vertical-slice.md
# if gitignore ever blocks plans: git add -f docs/superpowers/plans/2026-09-29-dsh-vertical-slice.md
git commit -m "$(cat <<'EOF'
docs: dsh vertical-slice plan + locked evening decisions

Point AGENTS at tonight slice; full cutover remains out of scope.
EOF
)"
```

- [ ] **Step 3: Push for review (no cloud)**

```bash
git push -u origin feat/dsh-vertical-slice
```

---

## Acceptance (tonight)

- [ ] `dsh/` submodule pinned; no business edits inside submodule.
- [ ] `plugins/qingshui` installed on web profile; **no** `plugins/matdiscovery` tree in this repo.
- [ ] `POST /api/v1/knowledge/search/semantic` + existing evidence GET work with `X-API-Key`. **No** `POST /resolve`.
- [ ] Plugin exposes exactly two tools (`semantic_search`, `fetch_evidence`) and uses HTTP only.
- [ ] Cordis LLM patch uses LiteLLM (`LLM_API_KEY`, `http://127.0.0.1:4000/v1`, `MiniMax-M2.7-highspeed`).
- [ ] `deploy/nginx/dsh-web.conf.example` documents basic auth; Knowledge remains API-key.
- [ ] `frontend/` still in tree; LangChain agent code untouched as default path.
- [ ] Implementer did **not** require production SSH to merge the PR; cloud steps are in `deploy/dsh/README.md`.

Manual chat proof (dev or after user cloud apply): open authenticated dsh web → ask model to search then fetch one `EV:…` → see evidence text.

---

## Self-Review Checklist

**1. Spec coverage (tonight Locked section)**

| Requirement | Task |
|---|---|
| dsh submodule + qingshui plugin | T1–T2 |
| ≤2 tools via Knowledge HTTP | T3–T5 |
| nginx basic auth stub | T7 |
| LiteLLM (not memtensor/Boyue) | T2 cordis.patch + T7 systemd |
| Retain Knowledge/scheduler/chemagent | no destructive tasks |
| No frontend delete / no LangChain archive / no dsh-agent-rpc / no resolve | OUT OF SCOPE + no tasks |
| Deploy = push GitHub default | Deploy Authority + T7–T8 |
| Fresh sessions | no migration tasks |

**2. Placeholder scan:** No TBD/TODO; full code in steps; deploy commands concrete.

**3. Type consistency:** Tool names `semantic_search` / `fetch_evidence`; client methods `semanticSearch` / `fetchEvidence`; HTTP paths `/api/v1/knowledge/search/semantic`, `/evidence/{id}`; config fields `knowledgeBaseUrl` / `knowledgeApiKeyRef` / `requestTimeoutMs` match across T2/T4/T5.

**4. Force-add note:** Plan lives under tracked `docs/superpowers/plans/`. If a future `.gitignore` ignores it, use `git add -f`. Do not store under ignored `.superpowers/`.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-09-29-dsh-vertical-slice.md`. Two execution options:

1. **Subagent-Driven (recommended)** — fresh subagent per task, review between tasks (`superpowers:subagent-driven-development`).
2. **Inline Execution** — same session with `superpowers:executing-plans`, batch with checkpoints.

Which approach?
