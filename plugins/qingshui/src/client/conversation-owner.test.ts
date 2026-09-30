import assert from 'node:assert/strict'
import { describe, it } from 'node:test'
import {
  CONVERSATION_SHADOW_PRIORITY,
  donorConversationEntry,
  graftConversationShadow,
  researchComposerOwner,
  ungraftConversationShadow,
  type LedgerEntry,
} from './conversation-owner.ts'

const t = (key: string) => key

describe('conversation shadow owner', () => {
  it('uses priority -1, below the shipped default of 0', () => {
    assert.equal(CONVERSATION_SHADOW_PRIORITY, -1)
    assert.ok(CONVERSATION_SHADOW_PRIORITY < 0)
  })

  it('picks the donor that owns children and ignores the shadow row', () => {
    const shadow = function Shadow() {}
    const donor: LedgerEntry = { component: function Root() {}, options: { priority: 0 }, children: { 'conversation.session': {} } }
    const ours: LedgerEntry = { component: shadow, options: { priority: -1 }, children: donor.children }
    assert.equal(donorConversationEntry([ours, donor], shadow), donor)
    assert.equal(donorConversationEntry([ours], shadow), undefined)
  })

  it('grafts children and inject, and ungraft drops them', () => {
    const inject = () => ({})
    const donor: LedgerEntry = { children: { 'conversation.composer': {} }, inject }
    const entry: LedgerEntry = {}
    graftConversationShadow(entry, donor)
    assert.equal(entry.children, donor.children)
    assert.equal(entry.inject, inject)
    ungraftConversationShadow(entry)
    assert.equal(entry.children, undefined)
    assert.equal(entry.inject, undefined)
  })

  it('does not lock the composer or mention a workspace once a session exists', () => {
    const hero = researchComposerOwner({
      sessionId: 'sess-1',
      hero: true,
      composerBlock: undefined,
      t,
    })
    assert.equal(hero['disabled'], undefined)
    assert.equal(hero['onRequestWorkspace'], undefined)
    assert.equal(hero['placeholder'], 'placeholder.hero')
    assert.equal(hero['variant'], 'hero')
    assert.equal(JSON.stringify(hero).includes('workspace'), false)

    const active = researchComposerOwner({
      sessionId: 'sess-1',
      hero: false,
      composerBlock: undefined,
      t,
    })
    assert.equal(active['disabled'], undefined)
    assert.equal(active['placeholder'], undefined)
    assert.equal(active['variant'], 'composer')
  })

  it('stays inert without a session, still without workspace recovery', () => {
    const owner = researchComposerOwner({
      sessionId: undefined,
      hero: true,
      composerBlock: { reason: 'nope' },
      t,
    })
    assert.equal(owner['disabled'], true)
    assert.equal(owner['placeholder'], 'placeholder.hero')
    assert.equal(owner['onRequestWorkspace'], undefined)
    assert.equal('blocked' in owner, false)
  })

  it('surfaces a composer block only when a session exists', () => {
    const block = { reason: 'pick a model' }
    const owner = researchComposerOwner({
      sessionId: 'sess-1',
      hero: false,
      composerBlock: block,
      t,
    })
    assert.equal(owner['blocked'], block)
    assert.equal(owner['placeholder'], 'pick a model')
    assert.equal(owner['disabled'], undefined)
  })
})
