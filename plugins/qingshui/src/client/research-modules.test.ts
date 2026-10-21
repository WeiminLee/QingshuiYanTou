import assert from 'node:assert/strict'
import { describe, it } from 'node:test'
import {
  clearModuleStart, RESEARCH_MODULES, stageModuleStart, takeModuleStart,
} from './research-modules.ts'

describe('research modules', () => {
  it('offers the four core lanes in sidebar order', () => {
    assert.deepEqual(
      RESEARCH_MODULES.map(module => module.id),
      ['market-review', 'stock-analysis', 'news-read', 'chat'],
    )
    assert.deepEqual(
      RESEARCH_MODULES.map(module => module.label),
      ['大盘复盘', '个股分析', '资讯解读', '日常对话'],
    )
  })

  it('auto-sends only the lanes whose opening is a complete question', () => {
    const auto = RESEARCH_MODULES.filter(module => module.autoSend).map(module => module.id)
    assert.deepEqual(auto, ['market-review', 'news-read'])
    // The stock lane leaves a half-typed draft so the user adds the subject.
    const stock = RESEARCH_MODULES.find(module => module.id === 'stock-analysis')
    assert.equal(stock?.autoSend, false)
    assert.ok((stock?.starter ?? '').endsWith('：'))
    // Chat starts blank on purpose.
    assert.equal(RESEARCH_MODULES.find(module => module.id === 'chat')?.starter, '')
  })

  it('spends a staged opening exactly once', () => {
    clearModuleStart()
    assert.equal(takeModuleStart(), undefined)

    stageModuleStart({ text: '复盘上个交易日', autoSend: true })
    assert.deepEqual(takeModuleStart(), { text: '复盘上个交易日', autoSend: true })
    assert.equal(takeModuleStart(), undefined)
  })

  it('drops a staged opening that never reached a session', () => {
    stageModuleStart({ text: '今天有哪些值得关注的公告和事件', autoSend: true })
    clearModuleStart()
    assert.equal(takeModuleStart(), undefined)
  })
})
