# Cutover follow-up status for Reviewer (2026-09-29 → 全切)

Overnight 成稿 approved; this doc tracks **全切** items. Parent will ping Reviewer when green — do not treat this file alone as the ping.

## (1) Skill mount — landed (`597882b`)

**Root cause:** `plugins/qingshui/skills/divergence-mining/SKILL.md` frontmatter `description` ended with unquoted `EV:` → YAML nested mapping → skill ignored → repo `read` fallback.

**Fix:** Quote `description`; MatDiscovery-style Cordis mount (`qingshui-local`); `pnpm run check:skills`.

## (2) Unwrap LangChain from Knowledge HTTP — landed (`597882b`)

Pure `app/knowledge/agent_*_ops.py`; HTTP contracts unchanged for `plugins/qingshui`.

## (3) Archive Vue + LangChain — landed (`e477c38`)

| Action | Evidence |
|---|---|
| `frontend/` → `archive/frontend/` | default path cleared; docker-compose Vue service commented |
| `langchain_agent/` → `archive/langchain_agent/` | see `archive/README.md` |
| `/api/v1/agent/*` | slim **410** router only — **no** `run_lead_agent` import |
| Knowledge / scheduler / chemagent | untouched |

Grep (`backend/app/**/*.py`): **zero** `run_lead_agent`; **zero** `app.reasoning.langchain_agent` imports.

## (4) Prod dsh web + nginx basic auth — landed (cloud `124.221.188.38`)

- Repo at `e477c38` under `/home/lwm/code/QingShuiTouYan`
- `dnf install nginx httpd-tools`; conf from `deploy/nginx/dsh-web.conf.example` → `/etc/nginx/conf.d/dsh-web.conf` (HTTP :80 + basic auth; TLS stub commented until certs)
- htpasswd: user `qingshui` (secret at `/root/qingshui-dsh-basic-auth.txt` on host only — never committed)
- `qingshui-dsh.service` enabled; dsh binds `127.0.0.1:3080`; Boyue via existing `.env.dsh` (keys not printed)
- Build notes: `dsh` needs `build:lib:host` + `build:lib:client` + `build:web` before web profile boots

**Probe (CST 2026-09-29 ~19:49):**

- `curl -sI http://127.0.0.1/` → **401** `WWW-Authenticate: Basic realm="Qingshui dsh"`
- `curl -sI -u qingshui:*** http://127.0.0.1/` → **200** `text/html` (dsh shell)
- Same **200** via public `http://124.221.188.38/` with auth

## (5) Cloud headless regression — landed

Gate script: `pnpm run check:skills` → `ok: 1 skill(s) — divergence-mining`.

Short prompt (force `skill()` + metric + evidence; forbid repo read). Transcript `/tmp/dsh-skill-regression.log` on cloud:

- `skill("divergence-mining")` ✅ — catalog body (EV: / 先探索后承诺); **no** `plugins/.../SKILL.md` / 改读仓库 fallback
- `compare_metric(dimension="营业收入", scope="硅片")` ✅ — 57 rows
- `fetch_evidence` ✅ — EV:`c2162ae8…` (601012.SH)
- process **EXIT:0**

## 「全切」终验 checklist

- [x] Archive `frontend/` + `langchain_agent/`
- [x] nginx basic auth live in front of dsh web `:3080`
- [x] Cloud catalog skill load with **no** repo read fallback (+ metric + `fetch_evidence`)
- [x] No `run_lead_agent` on default serving path
- [ ] Reviewer 全切终验 — **parent pings** when this file is green

## Rollback

- `git mv archive/frontend frontend` + `git mv archive/langchain_agent backend/app/reasoning/langchain_agent`
- Restore pre-archive `agent.py` / `main.py` HITL lifespan from git history
- `systemctl stop qingshui-dsh`; optionally `systemctl stop nginx`
- Knowledge HTTP contracts stay stable either way
