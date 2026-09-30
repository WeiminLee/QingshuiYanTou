/**
 * Occupy `conversation` at priority -1 once ui-conversation has registered
 * the shipped root. Lowest priority wins; children are grafted, not redeclared.
 */
import { ResearchConversationRoot } from './ResearchConversation.tsx'
import {
  CONVERSATION_SHADOW_PRIORITY,
  donorConversationEntry,
  graftConversationShadow,
  ungraftConversationShadow,
  type LedgerEntry,
} from './conversation-owner.ts'

type SlotsFace = {
  entries: (key: string) => readonly LedgerEntry[]
  register: (options: object, component: unknown) => () => void
  subscribe: (key: string, fn: () => void) => () => void
}

/**
 * Install the research conversation shadow for the life of this fiber.
 * @param ctx - client root context
 * @returns disposer
 */
export function installConversationShadow(ctx: {
  slots: SlotsFace
  on?: (event: string, fn: (key: string) => void) => () => void
}): () => void {
  let shadow: LedgerEntry | undefined
  let installing = false
  let disposeReg: (() => void) | undefined

  const install = (): boolean => {
    if (shadow !== undefined || installing) return shadow !== undefined
    const entries = ctx.slots.entries('conversation')
    const donor = donorConversationEntry(entries, ResearchConversationRoot)
    if (donor?.children === undefined) return false
    installing = true
    try {
      disposeReg = ctx.slots.register({
        name: 'conversation',
        priority: CONVERSATION_SHADOW_PRIORITY,
        locale: 'conversation',
      }, ResearchConversationRoot)
      shadow = ctx.slots.entries('conversation').find(
        entry => entry.options?.priority === CONVERSATION_SHADOW_PRIORITY,
      )
      if (shadow === undefined) {
        console.warn('qingshui: conversation shadow entry missing after register')
        return false
      }
      graftConversationShadow(shadow, donor)
      return true
    } catch (error) {
      console.warn('qingshui: conversation shadow failed', error)
      return false
    } finally {
      installing = false
    }
  }

  // slots/changed is synchronous inside register(), and the donor entry
  // already carries `children` at that point. Installing here beats first paint.
  const offEvent = ctx.on?.('slots/changed', (key) => {
    if (key === 'conversation') install()
  })
  const offSub = ctx.slots.subscribe('conversation', () => { install() })
  install()

  return () => {
    offEvent?.()
    offSub()
    if (shadow !== undefined) ungraftConversationShadow(shadow)
    disposeReg?.()
    shadow = undefined
    disposeReg = undefined
  }
}
