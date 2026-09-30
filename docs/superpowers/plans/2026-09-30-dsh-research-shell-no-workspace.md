# dsh Research Shell Without Workspace — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cold-open and New chat on cloud dsh web (nginx → `127.0.0.1:3080`) enter a usable投研会话 with **zero** workspace picker and **zero** `host.listDirectory` / pickDirectory. Sidebar shows a flat session list (archive Home IA via dsh web + `plugins/qingshui` client half). No Vue revive, no MatDiscovery shell copy, no Knowledge/tools/skill contract changes, N2 TLS out of scope.

**Architecture:** Approach **A** (design §3): cordis **disable** `ui-workspace` + `directory-picker` (+ Strong hide list from design §6); extend `plugins/qingshui` with a **browser client half** that (1) occupies `sidebar.workspaces` with a flat 投研会话 list + 新建对话, (2) cold-open / New chat → `sessions.create({})` (no `workspaceId` / no `cwd`) then `sessions.open`, (3) **never** calls `workspaces.startSession()` with empty path (that only `sessions.clear()` → inert Hero). Host half stays Knowledge tools + skills. Prefer zero dsh submodule edits.

**Tech Stack:** Node ≥22.19, pnpm, TypeScript, tsdown (host ESM + client CJS ModuleLoader banner, MatDiscovery dual-half pattern), Cordis client slots (`sidebar.workspaces`), dsh client runtime `sessions` / `slots` / `locale`, React 18 (via module-table externals).

**Spec:** `docs/superpowers/specs/2026-09-30-dsh-research-shell-no-workspace-design.md` (**Status: Approved**).

## Global Constraints

- Gates (design §0): no workspace picker; `host.listDirectory` not an entry gate; do not open host FS APIs for UI / through nginx; product = 投研壳 not coding agent; entry+chrome only.
- Approach A only unless Reviewer Approves otherwise. **Do not** silent-fork / edit `dsh/` submodule.
- **Reviewer nit (1):** design Status line must be `Approved` before / with this plan.
- **Reviewer nit (2):** If `ConversationRoot` inert cannot be cleared by “always have `sessionId`” alone, **STOP** and request a **separate Approve** for either (B) minimal upstream ConversationRoot patch or (A′) plugin-local `conversation` slot shadow. Do **not** ship a silent ConversationRoot fork.
- **Reviewer nit (3):** Acceptance = cloud nginx → 3080 **A1–A6** after profile rebuild (not Mac-only).
- Never call `workspaces.startSession()` without a workspace (empty → `sessions.clear()` → inert). Correct path: `sessions.create({})` → `open`.
- Never paste credentials in commits/docs.
- Branch: `feat/dsh-research-shell-no-workspace`. Cloud: `root@124.221.188.38` `/home/lwm/code/QingShuiTouYan`; service `qingshui-dsh`.
- Copy **patterns** from MatDiscovery dual-half (`exports["./client"]`, `dsh.client`, tsdown client banner) and dsh `ui-workspace` slot inject — do **not** copy MatDiscovery FieldMat / Ledger / brand shell as product UI.
- Test: prefer `node --import tsx --test` for pure session-bootstrap helpers; UI smoke on cloud A1–A6.

## Research notes (locked)

| Item | Finding |
|------|---------|
| Inert formula | `ConversationRoot`: `inert = sessionId === undefined \|\| (hero && chipTitle === undefined)`. Blank session **without** owning workspace → `chipTitle` undefined once `workspaces.phase === 'ready'` → **still inert** even with `sessionId`. Design’s “always have session” alone is **insufficient**. |
| Hard stop | If A2 fails after bootstrap `sessions.create({})`, stop per Reviewer nit (2); do not edit `dsh/` without Approve. |
| `startSession()` | `workspaces.startSession()` with no workspace → `sessions.clear()` only. Sidebar brand + New Session buttons call it. Client must replace that behavior (monkey-patch `ctx.workspaces.startSession` **or** own 新建 in `sidebar.workspaces` + patch) so chrome never clears into no-session. |
| Dual-half | MatDiscovery: `exports["./client"]` → `lib/client.js`; `dsh.client.platform: web` + inject; tsdown second entry CJS + `window.__ModuleLoader__.load` banner. |
| Profile (cloud) | `~/.dsh/profiles/web` already bundles `qingshui` link. After client half lands: rebuild plugin, restart `qingshui-dsh` (rebuild `dsh` web profile / `build:lib:client` only if needed for deps). |
| Host FS | Keep directory-picker + ui-workspace **disabled**; public 403 on listDirectory remains correct. |

## OUT OF SCOPE

- Open / relax host FS APIs; Vue `archive/frontend` revive; MatDiscovery shell transplant.
- Knowledge HTTP / tools / skill contract; divergence-mining; Boyue model config.
- N2 TLS / 内网; per-session private scratch UI; attachment upload wave; market sidebar panels; pixel-perfect visual restore.
- Editing files under `dsh/` without separate Approve.

## File Structure

| Path | Responsibility |
|------|----------------|
| `docs/superpowers/specs/2026-09-30-dsh-research-shell-no-workspace-design.md` | Status → Approved |
| `docs/superpowers/plans/2026-09-30-dsh-research-shell-no-workspace.md` | This plan |
| `plugins/qingshui/cordis.patch.yml` | Disable Must + Strong hide (§6); keep tools/LLM insert |
| `plugins/qingshui/package.json` | Add `exports["./client"]`, `files` client artifacts, `dsh.client` |
| `plugins/qingshui/tsdown.config.ts` | Host ESM + client CJS ModuleLoader bundle |
| `plugins/qingshui/src/client/index.ts` | Client `apply`: locale, startSession redirect, bootstrap, slot register |
| `plugins/qingshui/src/client/SessionBrowser.tsx` | Flat session list UI for `sidebar.workspaces` |
| `plugins/qingshui/src/client/session-actions.ts` | `createAndOpenSession(ctx)` — `sessions.create({})` + `open`; no workspaceId |
| `plugins/qingshui/src/client/session-actions.test.ts` | Unit test create payload / never startSession empty |
| `plugins/qingshui/src/client/locales.ts` | zh/en copy for 投研会话 |
| `plugins/qingshui/src/client/SessionBrowser.module.css` | Minimal list styles (IA, not pixel-perfect) |

---

### Task 0: Spec Approved + this plan

**Files:**
- Modify: `docs/superpowers/specs/2026-09-30-dsh-research-shell-no-workspace-design.md`
- Create: `docs/superpowers/plans/2026-09-30-dsh-research-shell-no-workspace.md`

- [ ] **Step 1:** Set design `**Status:** Approved`
- [ ] **Step 2:** Commit plan + status (this file)

```bash
git add docs/superpowers/specs/2026-09-30-dsh-research-shell-no-workspace-design.md \
  docs/superpowers/plans/2026-09-30-dsh-research-shell-no-workspace.md
git commit -m "$(cat <<'EOF'
docs: approve research-shell design + Approach A plan

EOF
)"
```

---

### Task 1: Cordis disables (Must + Strong hide)

**Files:**
- Modify: `plugins/qingshui/cordis.patch.yml`

- [ ] **Step 1:** Append disable rows (ids from `dsh/packages/bundle/web-app/cordis.patch.yml`):

Must:
- `ui-workspace`
- ~~`directory-picker`~~ **KEEP ENABLED** — apiproxy waits on `directoryPicker` service; disable only `ui-workspace` for entry gate

Strong hide (design §6):
- `ui-goal`, `ui-plan`, `ui-jobs`, `ui-subagent`, `ui-workflow-run`, `ui-deliverables`, `ui-trajectory`
- `ui-reference`, `file-reference-local`
- `ui-agent-preset`
- `ui-attachment` (Wave1 default hide)

Keep insert for `qingshui` host + LLM rows unchanged.

- [ ] **Step 2:** Commit

```bash
git add plugins/qingshui/cordis.patch.yml
git commit -m "$(cat <<'EOF'
fix(qingshui): disable workspace/directory chrome for research shell

EOF
)"
```

---

### Task 2: Package + tsdown dual-half scaffolding

**Files:**
- Modify: `plugins/qingshui/package.json`
- Modify: `plugins/qingshui/tsdown.config.ts`

- [ ] **Step 1:** Mirror MatDiscovery client export + `dsh.client`:

```json
"exports": {
  ".": { "default": "./lib/index.mjs" },
  "./client": { "default": "./lib/client.js" },
  "./package.json": "./package.json"
},
"files": ["lib/index.mjs", "lib/client.js", "lib/client.js.map", "cordis.patch.yml", "skills"],
"dsh": {
  "bundle": { "patch": "./cordis.patch.yml" },
  "client": {
    "platform": "web",
    "inject": [
      "@deepseek-ai/dsh-client-runtime",
      "@deepseek-ai/dsh-client-locale",
      "@deepseek-ai/dsh-client-ui-sidebar"
    ]
  }
}
```

(Adjust inject bare ids to match what the web module table resolves — prefer same style as MatDiscovery if scoped names fail on cloud.)

- [ ] **Step 2:** Add tsdown client entry (CJS, browser, ModuleLoader banner `id: "qingshui"`, externals: react, jsx-runtime, cordis, ui-slots, ui-primitives).

- [ ] **Step 3:** `pnpm run build:plugin` succeeds and emits `lib/client.js`.

- [ ] **Step 4:** Commit scaffolding + stub `src/client/index.ts` (`export const inject = ['slots']; export function apply() {}`) if needed for green build.

---

### Task 3: session-actions helper (TDD)

**Files:**
- Create: `plugins/qingshui/src/client/session-actions.ts`
- Create: `plugins/qingshui/src/client/session-actions.test.ts`

- [ ] **Step 1:** Write failing test: `createAndOpenSession` calls `sessions.create` with `{}` (no workspaceId/cwd) then `sessions.open(id)`; never calls `workspaces.startSession`.

- [ ] **Step 2:** Implement helper.

- [ ] **Step 3:** Run `node --import tsx --test plugins/qingshui/src/client/session-actions.test.ts` (or root `test:plugin` glob update).

- [ ] **Step 4:** Commit.

---

### Task 4: SessionBrowser + client apply (bootstrap + startSession redirect)

**Files:**
- Create: `plugins/qingshui/src/client/SessionBrowser.tsx`
- Create: `plugins/qingshui/src/client/SessionBrowser.module.css`
- Create: `plugins/qingshui/src/client/locales.ts`
- Modify: `plugins/qingshui/src/client/index.ts`

- [ ] **Step 1:** `SessionBrowser` occupies `sidebar.workspaces`:
  - Props from slot owner: `wide`, `expandSidebar`
  - List sessions from `useSessions` / injected list (ids + title + updatedAt); no directory tree; no paths
  - 新建对话 → `createAndOpenSession`
  - Row click → `sessions.open(id)`
  - Optional rename via `session.rename` if binding exists (nice-to-have; skip if blocks)

- [ ] **Step 2:** `apply(ctx)`:
  1. Register locale namespace `qingshui-shell`
  2. Redirect `ctx.workspaces.startSession` → `createAndOpenSession` (so shell New Session / brand click never `clear()`)
  3. `slots.inject('sidebar.workspaces', …)` register SessionBrowser
  4. Bootstrap effect: when sessions list `phase === 'ready'` and `current === undefined`, call `createAndOpenSession` once (guard re-entry)

- [ ] **Step 3:** Build plugin; smoke locally if feasible (`pnpm dsh --profile web` only if Mac profile has qingshui — cloud is source of truth).

- [ ] **Step 4:** Commit.

**Inert gate check (before cloud A2):** Re-read ConversationRoot. If blank session without workspace remains inert, **do not** vendor ConversationRoot. Document blocker in commit message / follow-up note and proceed to cloud only to confirm A1/A2 evidence, then STOP for Approve (Reviewer nit 2).

---

### Task 5: Push + cloud deploy + A1–A6

**Files:** none required (ops)

- [ ] **Step 1:** `git push -u origin feat/dsh-research-shell-no-workspace`

- [ ] **Step 2:** Cloud:

```bash
ssh root@124.221.188.38
cd /home/lwm/code/QingShuiTouYan
git fetch origin feat/dsh-research-shell-no-workspace
git checkout feat/dsh-research-shell-no-workspace
git pull --ff-only
# if fetch fails: scp/rsync bundle of plugins/qingshui only — last resort
export NVM_DIR=/home/lwm/.nvm; . "$NVM_DIR/nvm.sh"; nvm use 24
pnpm run build:plugin
# If client half not picked up: re-add plugin / touch profile
# pnpm dsh plugin --profile web add ./plugins/qingshui
systemctl restart qingshui-dsh
# If web static/client graph stale after dsh changes only:
# cd dsh && CI=true pnpm_config_verify_deps_before_run=false pnpm run build:lib:client && pnpm run build:web && cd ..
```

- [ ] **Step 3:** Acceptance (design §8) against public nginx → 3080:

| # | Check | Evidence |
|---|--------|----------|
| A1 | No workspace picker / Hero workspace chip | Screenshot or DOM note |
| A2 | Cold open composer usable (`sessionId` present, not inert) | Type in composer / `data-phase` / disabled attr |
| A3 | Zero `host.listDirectory` / pickDirectory on open→first interact | Browser Network or `qingshui-dsh` / api logs grep |
| A4 | 新建对话 → new session, still no directory API | Same |
| A5 | Sidebar session list visible; no path tree | DOM / screenshot |
| A6 | Knowledge tools/skills still registered (contract untouched) | `cordis` inventory or prior silicon-slice not required this wave |

- [ ] **Step 4:** If A2 fails solely due to ConversationRoot inert/chip with valid `sessionId`: **STOP**. Report blocker + options (upstream one-line inert change vs plugin `conversation` shadow at priority `-1`). Do not silent-edit `dsh/`.

- [ ] **Step 5:** Commit any deploy notes only if tracked docs updated (optional); otherwise leave evidence in the agent report.

---

## Acceptance mapping

| Gate | Task |
|------|------|
| No workspace entry / no listDirectory | Task 1 + 4 + A3 |
| Flat session sidebar + create without workspaceId | Task 3–4 + A4–A5 |
| Composer not inert | Task 4 gate + A2 — may hard-stop |
| Cloud nginx→3080 | Task 5 |
| Spec Approved | Task 0 |

## Hard-stop evidence (2026-09-30 cloud smoke)

Cloud nginx→3080 / tunnel Playwright after Approach A deploy:

| Check | Result | Evidence |
|-------|--------|----------|
| A1 workspace chip | **FAIL** | Hero still shows「选择工作区」; placeholder「选择一个工作区开始」 |
| A2 composer usable | **FAIL** | `textarea.readOnly=true`; fill("ping") no-op; `data-phase=hero` with session present |
| A3 zero listDirectory | **PASS** | Network: no `host.listDirectory` / `pickDirectory` on cold open or 新建对话 |
| A4 新建对话 | **PARTIAL** | `sessions.create` adds sidebar rows; still no directory API; composer remains blocked |
| A5 session sidebar | **PASS** | `投研会话` + `新建对话` + `.qs-shell-row` list; qingshui client in `__DSH_BOOT__` |
| A6 tools/skills | **PASS (host)** | Cordis patch only disables UI chrome; host `qingshui` tools insert unchanged |

**Root cause:** `ConversationRoot` `inert = sessionId === undefined \|\| (hero && chipTitle === undefined)`. Blank session without owning workspace → `chipTitle` undefined after `workspaces.phase === 'ready'` → readOnly composer + workspace chip. Approach A “always have sessionId” is insufficient.

**Ops note:** Do **not** disable host `directory-picker` — apiproxy waits on `directoryPicker` and crash-loops.

**Stopped per Reviewer nit (2):** no silent `dsh/` ConversationRoot fork. Request separate Approve for (B) one-line upstream inert/chip change or (A′) plugin `conversation` slot shadow at priority `-1`.

## A′ evidence (2026-09-30, `828f61a`)

Plugin-local `conversation` shadow at priority **-1** (Cordis: lowest priority renders; default 0). The winner cannot redeclare child seats (`already declared`), so it grafts the shipped entry's `children` + `inject` and renders without the workspace chip. Inert gate is session presence only. No `dsh/` diff.

Playwright (Chrome) via Mac tunnel `127.0.0.1:13080` → cloud `127.0.0.1:3080` (nginx upstream; public `:80` API stays 403 unless Host is loopback — `trustedHosts` does not include the public IP, and nginx `$host` strips a non-80 tunnel port):

| Check | Result | Evidence |
|-------|--------|----------|
| A1 workspace chip | **PASS** | No「选择工作区」/「选择一个工作区开始」; `[data-qs-conversation=research]` |
| A2 composer usable | **PASS** | `readOnly=false`, `disabled=false`; fill `ping` stuck; Enter → `data-phase=active` |
| A3 zero listDirectory | **PASS** | No `listDirectory` / `pickDirectory` in HTTP or websocket frames |
| A4 新建对话 | **PASS** | Sidebar rows 4 → 5; still zero directory API; composer stays editable |
| A5 session sidebar | **PASS** | 「投研会话」+「新建对话」+ `.qs-shell-row` |
| A6 tools/skills | **PASS** | `__DSH_BOOT__` includes qingshui; host patch unchanged |
| dsh/ diff | **none** | shadow is plugin-local |

Cloud checkout `feat/dsh-research-shell-no-workspace` @ `828f61a`; `systemctl restart qingshui-dsh` active, `dsh web: http://127.0.0.1:3080`.
