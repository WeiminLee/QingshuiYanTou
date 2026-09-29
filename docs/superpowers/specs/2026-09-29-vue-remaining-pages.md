# Vue `frontend/` remaining pages (cutover progress, 2026-09-29 night)

Reviewer approved overnight 成稿 but **not** full cutover. This note tracks what still lives under `frontend/` after retiring default agent UX.

## Agent / chat entry (deprecated tonight)

| Route | Status |
|---|---|
| `/home` | Renders `AgentDeprecatedView` — points to dsh |
| `/spike-chat` | Same |
| `/agent-deprecated` | Explicit notice page |

Backend `/api/v1/agent/{chat,invoke,stream,report,v2/*…}` → **410 Gone** with `langchain_agent_retired`. Knowledge HTTP `/api/v1/knowledge/*` unchanged.

## Must stay until 「全切」终验 (or dsh re-home)

| Route / area | Why kept |
|---|---|
| `/login`, `/select-identity` | Account auth (not agent shell) |
| `/portfolio` | Account portfolio UX |
| `/stock/:tsCode` | Stock detail (non-chat) |
| `/report` | Legacy report viewer (read-only; no new agent runs) |
| `/tdesign-demo` | Design spike; non-product |

## Explicitly not deleted tonight

- Entire `frontend/` tree (Reviewer: no full cutover yet)
- LangChain package code under `backend/app/reasoning/langchain_agent/` (rollback surface; default routes hard-stopped)

## Documented agent entry

```sh
pnpm run build:plugin
pnpm dsh plugin --profile web add ./plugins/qingshui   # or headless
pnpm dsh --profile web
# headless smoke:
pnpm dsh --profile headless "对硅片板块做预期差分析"
```
