# Cutover follow-up status for Reviewer (2026-09-29 night → 全切)

Overnight 成稿 approved; this doc tracks **全切** remaining items.

## (1) Skill mount — landed (597882b)

**Root cause:** `plugins/qingshui/skills/divergence-mining/SKILL.md` frontmatter `description` ended with unquoted `EV:`, which YAML treats as a nested mapping. `dsh-skill-filesystem` logged and **ignored** the skill → session catalog miss → agent fell back to `read` on the repo path.

**Fix:** Quote `description`; MatDiscovery-style Cordis mount; `node scripts/check-qingshui-skills.mjs`.

## (2) Unwrap LangChain from Knowledge HTTP — landed (597882b)

Pure services `app/knowledge/agent_*_ops.py`; HTTP unchanged for `plugins/qingshui`.

## (3) Retire old agent shell + archive — landed (this commit)

| Action | Evidence |
|---|---|
| `frontend/` → `archive/frontend/` | Vue SPA out of default path; docker-compose frontend service commented |
| `backend/app/reasoning/langchain_agent/` → `archive/langchain_agent/` | `run_lead_agent` not on default serving path |
| `/api/v1/agent/*` | Slim 410 router only (no langchain imports) |
| Knowledge / scheduler / chemagent | Untouched |

See `archive/README.md`. Residual LangChain **docs/tests** may still mention old paths; they are not default process imports.

## (4) Prod dsh web + nginx basic auth — see deploy evidence

Host `root@124.221.188.38:/home/lwm/code/QingShuiTouYan`. Stubs: `deploy/nginx/dsh-web.conf.example`, `deploy/dsh/qingshui-dsh.service.example`. Boyue via cloud `.env.dsh` (never print keys).

## (5) Cloud headless regression — see deploy evidence

Gate: `divergence-mining` **LOADED** from skill catalog (no repo `read` fallback); short prompt forces `skill()` + one metric tool + `fetch_evidence`.

## 「全切」终验 checklist

- [x] Archive `frontend/` + `langchain_agent/`
- [ ] nginx basic auth live in front of dsh web `:3080`
- [ ] Cloud catalog skill load (LOADED) with **no** repo read fallback
- [x] No `run_lead_agent` import on default serving path (`backend/app/**`)
- [ ] Reviewer 全切终验 (parent pings when green)

## Rollback

- `git mv archive/frontend frontend` + `git mv archive/langchain_agent backend/app/reasoning/langchain_agent`
- Restore pre-archive `agent.py` / `main.py` HITL lifespan from git history
- Knowledge HTTP contracts stay stable either way
