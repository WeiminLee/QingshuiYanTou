# Cloud LLM Provider Config Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Configure the Tencent Cloud deployment to use the provided OpenAI-compatible LLM provider without committing secrets.

**Architecture:** The cloud backend, scheduler, job-worker, and manually started extraction workers already consume `LLM_BASE_URL`, `LLM_API_KEY`, and `LLM_MODEL` through `backend/.env` and Docker Compose. The implementation updates only the server-side `.env`, keeps extraction disabled by default, and verifies the provider through a small container-local API call before enabling any backlog processing.

**Tech Stack:** Docker Compose, Bash, Python OpenAI-compatible client, server-side `.env`, existing `server_start.sh`.

## Global Constraints

- Never commit real API keys, passwords, tokens, or provider secrets.
- Keep `EVIDENCE_WORKER_ENABLED=0` by default until provider verification passes.
- Respect provider rate limit: 22 requests per minute.
- Use conservative extraction settings first: max concurrency 1, limit per loop 5, interval 180 seconds.
- Do not expose database ports publicly as part of this change.

---

### Task 1: Publish Current Local Main

**Files:**
- No file changes.

**Interfaces:**
- Consumes: local `main` branch with committed architecture document.
- Produces: remote `origin/main` containing the latest docs and cloud fixes.

- [ ] **Step 1: Verify local branch and worktree**

Run:

```bash
git branch --show-current
git status --short
git log --oneline -3
```

Expected: branch is `main`, status has no uncommitted changes, latest commit is the architecture document commit.

- [ ] **Step 2: Push main**

Run:

```bash
git push origin main
```

Expected: push exits 0 and updates `origin/main`.

### Task 2: Sync Server Code

**Files:**
- No tracked file changes expected on server.

**Interfaces:**
- Consumes: pushed `origin/main`.
- Produces: server checkout at the same or newer commit as local main.

- [ ] **Step 1: Check server state**

Run on server:

```bash
cd /home/lwm/code/QingShuiTouYan
git branch --show-current
git status --short
git rev-parse --short HEAD
```

Expected: branch is `main`. If dirty files are unrelated, do not revert them; inspect before pulling.

- [ ] **Step 2: Pull latest**

Run on server:

```bash
cd /home/lwm/code/QingShuiTouYan
git pull --ff-only origin main
```

Expected: server HEAD advances to the latest pushed commit.

### Task 3: Update Server LLM Environment

**Files:**
- Modify on server only: `/home/lwm/code/QingShuiTouYan/backend/.env`
- Do not modify local tracked files.

**Interfaces:**
- Consumes: provider base URL, model name, and secret API key from the operator.
- Produces: server `.env` with runtime variables.

- [ ] **Step 1: Backup server `.env` without printing secrets**

Run on server:

```bash
cd /home/lwm/code/QingShuiTouYan
cp backend/.env "backend/.env.bak.$(date +%Y%m%d%H%M%S)"
```

Expected: backup file is created; do not display its contents.

- [ ] **Step 2: Upsert LLM variables**

Run a script on server that updates only these keys:

```text
LLM_BASE_URL
LLM_MODEL
LLM_API_KEY
LLM_MAX_CONCURRENCY
LLM_RATE_LIMIT_PER_MINUTE
EVIDENCE_MAX_CONCURRENCY
EVIDENCE_LIMIT_PER_LOOP
EVIDENCE_INTERVAL
EVIDENCE_WORKER_ENABLED
ENABLE_EVIDENCE_SCHEDULER
```

Expected values:

```text
LLM_BASE_URL=<provider URL>
LLM_MODEL=<provider model>
LLM_API_KEY=<provider secret>
LLM_MAX_CONCURRENCY=1
LLM_RATE_LIMIT_PER_MINUTE=22
EVIDENCE_MAX_CONCURRENCY=1
EVIDENCE_LIMIT_PER_LOOP=5
EVIDENCE_INTERVAL=180
EVIDENCE_WORKER_ENABLED=0
ENABLE_EVIDENCE_SCHEDULER=false
```

### Task 4: Restart and Verify Provider

**Files:**
- No tracked file changes.

**Interfaces:**
- Consumes: updated server `.env`.
- Produces: running containers that see the new LLM config.

- [ ] **Step 1: Restart cloud services**

Run on server:

```bash
cd /home/lwm/code/QingShuiTouYan
./server_start.sh restart
```

Expected: backend, scheduler, job-worker, and databases are running.

- [ ] **Step 2: Verify health**

Run on server:

```bash
cd /home/lwm/code/QingShuiTouYan
./server_start.sh health
```

Expected: backend health endpoint returns OK and containers are up.

- [ ] **Step 3: Verify LLM API with a single request**

Run inside the backend container using environment variables from `.env`; do not print the API key:

```bash
docker compose exec -T backend python - <<'PY'
import os
from openai import OpenAI

client = OpenAI(
    api_key=os.environ["LLM_API_KEY"],
    base_url=os.environ["LLM_BASE_URL"],
)
resp = client.chat.completions.create(
    model=os.environ["LLM_MODEL"],
    messages=[{"role": "user", "content": "只回复 OK"}],
    temperature=0,
    max_tokens=8,
    timeout=60,
)
print(resp.choices[0].message.content.strip()[:40])
PY
```

Expected: command exits 0 and returns a short model response.

### Task 5: Keep Extraction Disabled Until Explicit Start

**Files:**
- No tracked file changes.

**Interfaces:**
- Consumes: server `.env` conservative settings.
- Produces: safe idle extraction state.

- [ ] **Step 1: Confirm evidence workers are not running**

Run on server:

```bash
docker ps --format '{{.Names}}' | grep evidence || true
```

Expected: no evidence worker container unless explicitly started later.

- [ ] **Step 2: Report next controlled-start command**

Use this command only after provider verification and user approval:

```bash
cd /home/lwm/code/QingShuiTouYan
EVIDENCE_WORKER_ENABLED=1 EVIDENCE_JOB_TYPES=combined EVIDENCE_MAX_CONCURRENCY=1 EVIDENCE_LIMIT_PER_LOOP=5 EVIDENCE_INTERVAL=180 ./server_start.sh start
```

Expected: starts only the `combined` extraction worker at a conservative rate.
