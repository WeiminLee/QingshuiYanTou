import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { describe, it } from 'node:test'
import { fileURLToPath } from 'node:url'
import { RESEARCH_STARTS } from './ResearchStarts.tsx'

const skillPath = join(dirname(fileURLToPath(import.meta.url)), '../../skills/session-review/SKILL.md')

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
