# Vue `frontend/` — archived (2026-09-29 全切)

`frontend/` moved to **`archive/frontend/`**. Product shell is **dsh web** (+ nginx basic auth on cloud).

Non-chat pages (login / portfolio / stock / report) are **not** re-homed tonight; they live only under the archive tree for rollback. Rebuild via dsh later if needed.

Backend `/api/v1/agent/*` → **410** `langchain_agent_retired`. Knowledge HTTP unchanged.

```sh
pnpm run build:plugin
pnpm dsh plugin --profile web add ./plugins/qingshui
pnpm dsh --profile web
```
