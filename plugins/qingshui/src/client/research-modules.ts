/**
 * Core research entry points for the sidebar: each module starts a new chat
 * with its own opening question, so the four lanes differ in workflow (the
 * skill that answers them), not in agent composition.
 *
 * The starter is staged before the session is created and spent by the
 * conversation root once the new blank session can accept input — riding along
 * on `sessions.create` would miss the blank session the shell reuses.
 */

export type ResearchModuleId = 'market-review' | 'stock-analysis' | 'news-read' | 'chat'

export type ResearchModule = {
  id: ResearchModuleId
  label: string
  hint: string
  /** Opening text placed in the composer; empty starts a plain blank chat. */
  starter: string
  /** Send the starter immediately instead of leaving it as an editable draft. */
  autoSend: boolean
}

export const RESEARCH_MODULES: readonly ResearchModule[] = [
  {
    id: 'market-review',
    label: '大盘复盘',
    hint: '上个交易日的市场结构与主线',
    starter: '复盘上个交易日',
    autoSend: true,
  },
  {
    id: 'stock-analysis',
    label: '个股分析',
    hint: '单只标的的预期差',
    starter: '帮我分析这只票的预期差：',
    autoSend: false,
  },
  {
    id: 'news-read',
    label: '资讯解读',
    hint: '公告与事件怎么看',
    starter: '今天有哪些值得关注的公告和事件',
    autoSend: true,
  },
  {
    id: 'chat',
    label: '日常对话',
    hint: '随便问，不预设流程',
    starter: '',
    autoSend: false,
  },
] as const

export type PendingStart = { text: string; autoSend: boolean }

let pending: PendingStart | undefined

/** Stage the module's opening for the next blank session. */
export function stageModuleStart(start: PendingStart): void {
  pending = start
}

/** Claim the staged opening exactly once. @returns the start, or undefined. */
export function takeModuleStart(): PendingStart | undefined {
  const claimed = pending
  pending = undefined
  return claimed
}

/** Drop a staged opening that never reached a session (create failed). */
export function clearModuleStart(): void {
  pending = undefined
}
