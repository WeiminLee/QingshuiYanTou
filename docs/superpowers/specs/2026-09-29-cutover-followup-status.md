# Cutover follow-up status for Reviewer (2026-09-29 night)

Overnight 成稿 approved; **not** full cutover. Three follow-ups:

## (1) Skill mount — landed

**Root cause:** `plugins/qingshui/skills/divergence-mining/SKILL.md` frontmatter `description` ended with unquoted `EV:`, which YAML treats as a nested mapping. `dsh-skill-filesystem` logged and **ignored** the skill → session catalog miss → agent fell back to `read` on the repo path.

**Fix:**
- Quote `description` in SKILL.md
- Harden Cordis mount (MatDiscovery pattern): `inject=['tools','skills']`, provider `qingshui-local`, `includeDefaultRoots:false`, `customSkillDirs`, mount logging
- Gate: `node scripts/check-qingshui-skills.mjs`

**Verify:** check script green; headless smoke that `skill("divergence-mining")` resolves (see commit message / CI notes).

## (2) Unwrap LangChain from Knowledge HTTP — landed

- New pure services: `app/knowledge/agent_metric_ops.py`, `app/knowledge/agent_graph_ops.py`
- `app/knowledge/api/agent_metrics.py` calls those directly (no `ainvoke` / `@tool` / `reasoning.tools`)
- `agent_search` was already vector-client direct
- LangChain `@tool` wrappers in `reasoning/tools/knowledge/{metric_ops,graph_walk}.py` thinned to call the same pure services (rollback / residual shell only)
- HTTP contracts unchanged for `plugins/qingshui`
- Tests: `backend/tests/test_agent_metrics_api.py` (+ langchain-free guard)

## (3) Retire old agent shell (progress, not full delete) — landed

- `/api/v1/agent/*` chat/invoke/stream/report/v2 → **410** `langchain_agent_retired`
- Vue `/home` + `/spike-chat` → `AgentDeprecatedView` (dsh entry instructions)
- `frontend/` tree **not** deleted; remaining pages listed in `2026-09-29-vue-remaining-pages.md`
- Knowledge API / workers / ingest untouched

## Left for 「全切」终验

- [ ] Remove or archive entire `frontend/` after dsh web auth + portfolio parity (or explicit drop)
- [ ] Archive/remove `langchain_agent/` from default installs (keep git tag for rollback)
- [ ] Production: dsh web on Knowledge host with nginx auth (deploy stubs exist)
- [ ] Cloud headless regression: `skill("divergence-mining")` in catalog + full 硅片报告 without repo `read` fallback
- [ ] Confirm no process still imports `run_lead_agent` on the default serving path
- [ ] Reviewer checklist in cutover design §9

## Rollback

- Revert this follow-up commit(s); Knowledge HTTP contracts stay stable either way
- Evidence / PG / Qdrant not touched
