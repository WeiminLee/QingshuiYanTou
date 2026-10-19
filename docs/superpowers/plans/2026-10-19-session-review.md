# 昨日复盘 session-review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用户在本地 Agent 说「复盘上个交易日」时，按固定工具顺序写出六段复盘，并且空会话能点开发出这句话。

**Architecture:** 新增 `plugins/qingshui/skills/session-review/SKILL.md`，用现有只读 MCP 工具约束模型。入口只在 `RESEARCH_STARTS` 加一条文案。不新增后端工具，不部署 chemagent。

**Tech Stack:** dsh 插件技能 Markdown、插件 client React、`node --import tsx --test`、`npm run build:plugin`。

**Spec:** `docs/superpowers/specs/2026-10-19-session-review-design.md`

## Global Constraints

- 交易日 = `get_market_snapshot()` 空日期返回的 `trade_date`（`YYYYMMDD`）。
- 主线调用 `get_top_concepts(days=2, top_n=5)`。不传 `days=1`。不把 `last_up_nums` / `last_pct_chg` 写成昨日涨停或昨日涨跌幅。
- 只对排名第 1 的概念调用 `get_concept_stocks(concept_code, sort_by=pct_chg, limit=5)`。
- 成分涨幅不是涨停名单。`latest_trade_date` 与快照日期不同时，两个日期都写出来。
- 公告与事件只覆盖涨幅前 2 名；不足 2 名则对返回的那几名调用；0 名写「没有」。`find_events` 的 `query` 必填。
- 输出六个二级标题，顺序固定：交易日、市场结构、主线、落到主体、接着看、依据与缺口。
- 禁止买卖、目标价、仓位、`write_finding`、`write_observation`、`compare_metric`，以及宣称存在或不存在预期差。
- 不改 `backend/`、`deploy/`、金标、`expected-gap`、`divergence-mining`。不跑 `scripts/run-golden-eval.sh`。

## Review Focus

- 模型仍可能忽略技能、把两日热度说成单日涨停榜。契约测试只锁技能文本，不锁一次真实模型回答。试用时看正文是否写出「最近两个有概念数据的交易日」，并且没有把 `last_up_nums` 当成昨日涨停家数。
- `get_concept_stocks` 的 `latest_trade_date` 若与快照日不一致，合理使用者会看到两个日期，而不是被并成一天。
- 公告或事件为空时，合理使用者会看到「没有」，而不是编出来的新闻或毛利率维度。
- 工具失败时，该段写「缺失」，其余段仍在。
- 重启前，8399 仍提供旧的 `client.js`，空会话不会出现新按钮。

## File structure

- Create: `plugins/qingshui/skills/session-review/SKILL.md` — 技能契约。
- Create: `plugins/qingshui/src/client/research-starts.test.ts` — 起步文案与技能文本断言。
- Modify: `plugins/qingshui/src/client/ResearchStarts.tsx` — 第四条起步问题。
- Build: `plugins/qingshui/lib/client.js` 与 `lib/client.js.map` — 构建产物，供 8399 加载。不把与本功能无关的既有未提交客户端改动混进本次提交说明之外；构建本身会重写这两个文件。

---

### Task 1: 技能契约

**Files:**
- Create: `plugins/qingshui/skills/session-review/SKILL.md`
- Test: `plugins/qingshui/src/client/research-starts.test.ts`

**Interfaces:**
- Consumes: 无
- Produces: 技能目录名 `session-review`，frontmatter `name: session-review`。工具名使用 `mcp__qingshui_data__` 前缀。

- [ ] **Step 1: Write the failing test**

把下面的 `sessionReviewSkill` 用例放进 `plugins/qingshui/src/client/research-starts.test.ts`。起步列表用例留到 Task 2；本步文件里可以先只放技能用例。

```ts
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { describe, it } from 'node:test'
import { fileURLToPath } from 'node:url'

const skillPath = join(dirname(fileURLToPath(import.meta.url)), '../../skills/session-review/SKILL.md')

describe('session-review skill', () => {
  it('locks the tool order, the two-day concept window, and the bans', () => {
    const text = readFileSync(skillPath, 'utf8')
    for (const phrase of [
      'name: session-review',
      'mcp__qingshui_data__data_readiness',
      'mcp__qingshui_data__get_market_snapshot',
      'mcp__qingshui_data__get_top_concepts(days=2, top_n=5)',
      'mcp__qingshui_data__get_concept_stocks',
      'sort_by=pct_chg',
      'mcp__qingshui_data__get_announcement',
      'mcp__qingshui_data__find_events',
      'query 必填',
      '最近两个有概念数据的交易日',
      '不引用 last_up_nums',
      '不引用 last_pct_chg',
      '不是涨停名单',
      '禁止 write_finding',
      '禁止 write_observation',
      '## 交易日',
      '## 市场结构',
      '## 主线',
      '## 落到主体',
      '## 接着看',
      '## 依据与缺口',
      'latest_trade_date',
    ]) {
      assert.ok(text.includes(phrase), `missing ${phrase}`)
    }
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `TSX_TSCONFIG_PATH=$PWD/dsh/tsconfig.base.json node --import tsx --test plugins/qingshui/src/client/research-starts.test.ts`

Expected: FAIL because `SKILL.md` does not exist.

- [ ] **Step 3: Write minimal implementation**

Create `plugins/qingshui/skills/session-review/SKILL.md` with frontmatter `name: session-review` and a description that mentions 昨日复盘. Body must contain every phrase the test asserts, in the order and with the bans from Global Constraints. Tell the model: 交易日取空日期快照的 `trade_date`；主线列出 `trade_dates`，概念行只用 `concept_name`、`concept_code`、`total_score`、`appear_days`、`rank`；只对第 1 名取成分；涨幅前 2 名才查公告和事件，不足则对现有的几名查，0 名写「没有」；日期不一致时两个日期都写；失败段写「缺失」；接着看只提 1 到 3 个问题，主体必须来自已返回的股票，没有公告和事件时不编造维度。

- [ ] **Step 4: Run test to verify it passes**

Run the same `node --import tsx --test` command. Expected: PASS.

Run: `npm run check:skills`

Expected: `ok:` and the list includes `session-review`.

- [ ] **Step 5: Commit**

```bash
git add plugins/qingshui/skills/session-review/SKILL.md plugins/qingshui/src/client/research-starts.test.ts docs/superpowers/specs/2026-10-19-session-review-design.md docs/superpowers/plans/2026-10-19-session-review.md
git commit -m "feat(skill): add session-review for the last closed session"
```

只暂存这些路径。不要 `git add -A`。

### Task 2: 空会话入口

**Files:**
- Modify: `plugins/qingshui/src/client/ResearchStarts.tsx`
- Test: `plugins/qingshui/src/client/research-starts.test.ts`
- Build: `plugins/qingshui/lib/client.js`, `plugins/qingshui/lib/client.js.map`

**Interfaces:**
- Consumes: 无技能符号。文案常量 `RESEARCH_STARTS`。
- Produces: `RESEARCH_STARTS` 第四项为 `复盘上个交易日`。前三项保持原文。

- [ ] **Step 1: Write the failing test**

在同一测试文件增加：

```ts
import { RESEARCH_STARTS } from './ResearchStarts.tsx'

describe('research starts', () => {
  it('offers a last-session review after the three everyday questions', () => {
    assert.deepEqual(RESEARCH_STARTS, [
      '这只票的毛利率，是不是又上台阶了',
      '芯片板块今天为什么这么热',
      '今天大盘涨跌家数和成交额怎么样',
      '复盘上个交易日',
    ])
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run the same test file command. Expected: FAIL on deepEqual, actual length 3.

- [ ] **Step 3: Write minimal implementation**

在 `RESEARCH_STARTS` 数组末尾加上 `'复盘上个交易日'`。标题「今天想看什么」和点击即发送的行为不动。

- [ ] **Step 4: Run tests and build**

Run the test file command. Expected: PASS.

Run: `npm run test:plugin`

Expected: the plugin suite passes. Failures that already existed before this task are reported by name, not hidden.

Run: `npm run build:plugin`

Expected: `plugins/qingshui/lib/client.js` contains `复盘上个交易日`.

- [ ] **Step 5: Restart local dsh and check the served bundle**

Tunnel on 8100 and 8001 must already be listening. Then:

```bash
launchctl kickstart -k "gui/$(id -u)/com.qingshui.dsh-web"
```

Wait until `http://127.0.0.1:8399/` returns 200. Fetch `/plugins/qingshui/client.js` from the boot HTML and confirm the body contains `复盘上个交易日`.

- [ ] **Step 6: Commit the starter source**

```bash
git add plugins/qingshui/src/client/ResearchStarts.tsx plugins/qingshui/src/client/research-starts.test.ts
git commit -m "feat(client): add last-session review to empty-chat starts"
```

`lib/client.js` 留在工作区给 8399 使用。它重写的是整个客户端包，不单独作为本任务提交，以免把无关的未提交界面改动卷进这个提交。
