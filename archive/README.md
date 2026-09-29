# Archive — dsh cutover (2026-09-29)

Trees moved out of the default product path. Knowledge FastAPI, data-pipeline
scheduler, and chemagent workers are **not** here and stay live under `backend/`.

| Path | Former location | Notes |
|---|---|---|
| `archive/frontend/` | `frontend/` | Vue SPA (chat + portfolio/login/…). Replaced by **dsh web**. |
| `archive/langchain_agent/` | `backend/app/reasoning/langchain_agent/` | `run_lead_agent` / LangChain shell. `/api/v1/agent/*` → **410**. |
| `archive/langchain_agent/tests/` | `backend/tests/**` (langchain-dependent) | Kept next to archived package so CI/pytest on `backend/tests` does not import dead paths. See `tests/README.md`. |

Rollback: `git mv` back + restore pre-cutover `agent.py` / `main.py` lifespan HITL task from git history (tag/branch before this commit).

Do **not** import `archive.langchain_agent` from the default serving path.
