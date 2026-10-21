/**
 * Qingshui research-shell browser half: flat session list in sidebar.workspaces,
 * cold-open / New chat → sessions.create({}) (no workspaceId), and the
 * assistant-step shadow adding interactive EV citation chips.
 */
import { QingshuiBrandMark, QingshuiBrandName } from './Brand.tsx'
import { clearModuleStart, stageModuleStart, type ResearchModule } from './research-modules.ts'
import { archiveSession, createAndOpenSession, renameSession } from './session-actions.ts'
import { SessionBrowser } from './SessionBrowser.tsx'
import { en, zh, type QingshuiShellKey } from './locales.ts'
import { installClientStyles } from './theme.ts'
import { installConversationShadow } from './conversation-shadow.ts'
import { registerToolviews } from './toolviews/index.ts'
import { QsAssistantStepView } from './ev-view.tsx'

export type { QingshuiShellKey }

const NS = 'qingshui-shell'

/** Cordis inject: slots + sessions + workspaces + locale. */
export const inject = ['slots', 'sessions', 'workspaces', 'locale']

const HARNESS_NOTICE_TITLES = new Set(['内测声明', 'Internal Testing Notice'])

/**
 * The models settings plugin also mounts the harness developer notice.
 * Dismiss that dialog only. The API-key page and a first-run key prompt stay.
 * @returns disposer
 */
function dismissHarnessNotice(): () => void {
  if (typeof document === 'undefined' || typeof MutationObserver === 'undefined') return () => undefined
  const scan = (): void => {
    for (const dialog of document.querySelectorAll('[role="dialog"]')) {
      const title = dialog.querySelector('h2')?.textContent?.trim() ?? ''
      if (!HARNESS_NOTICE_TITLES.has(title)) continue
      const button = [...dialog.querySelectorAll('button')].find(el => {
        const label = el.textContent?.trim()
        return label === '继续' || label === 'Continue'
      })
      if (button instanceof HTMLButtonElement && !button.disabled) button.click()
    }
  }
  let timer: ReturnType<typeof setTimeout> | undefined
  const schedule = (): void => {
    if (timer !== undefined) return
    timer = setTimeout(() => {
      timer = undefined
      scan()
    }, 200)
  }
  const observer = new MutationObserver(schedule)
  observer.observe(document.documentElement, { childList: true, subtree: true })
  scan()
  return () => {
    observer.disconnect()
    if (timer !== undefined) clearTimeout(timer)
  }
}

/**
 * Install research-shell UI.
 * @param ctx - client root context (loosely typed; matches MatDiscovery client style)
 */
export function apply(ctx: any): void {
  ctx.effect(() => installClientStyles(), 'qingshui: shell styles')
  ctx.effect(() => dismissHarnessNotice(), 'qingshui: dismiss harness notice')
  ctx.effect(() => ctx.locale.register(NS, { zh, en }), 'qingshui: shell dictionaries')

  // Shell New Session / brand click call workspaces.startSession(); without a
  // workspace that only sessions.clear()s into the inert Hero. Redirect to
  // sessions.create({}) + open so chrome stays chat-first.
  const workspaces = ctx.workspaces
  if (workspaces !== undefined && typeof workspaces.startSession === 'function') {
    workspaces.startSession = (_workspaceId?: string): void => {
      void createAndOpenSession(ctx.sessions).catch((error: unknown) => {
        console.warn('qingshui: startSession redirect failed', error)
      })
    }
  }

  // Lowest priority wins a single slot, so this replaces the harness fish
  // even when the official brand occupant is also registered.
  ctx.effect(
    () => ctx.slots.inject('sidebar.brand.mark', () =>
      ctx.slots.inject('sidebar.brand.name', function* () {
        yield ctx.slots.register({ name: 'sidebar.brand.mark', priority: -1 }, QingshuiBrandMark)
        yield ctx.slots.register({ name: 'sidebar.brand.name', priority: -1 }, QingshuiBrandName)
      })),
    'qingshui: brand',
  )

  const openSession = (sessionId: string): void => { ctx.sessions.open(sessionId) }
  const archive = (sessionId: string): Promise<void> =>
    archiveSession(ctx.workspaces, sessionId).catch((error: unknown) => {
      console.warn('qingshui: archive failed', error)
    })
  const rename = (sessionId: string, title: string): Promise<boolean> =>
    renameSession(ctx.sessions, sessionId, title)

  // Stage the lane's opening BEFORE creating, so the conversation root finds it
  // the moment the new blank session becomes current.
  const startModule = (module: ResearchModule): void => {
    stageModuleStart({ text: module.starter, autoSend: module.autoSend })
    void createAndOpenSession(ctx.sessions).catch((error: unknown) => {
      clearModuleStart()
      console.warn('qingshui: module session create failed', error)
    })
  }

  ctx.effect(
    () => ctx.slots.inject('sidebar.workspaces', () => ctx.slots.register({
      name: 'sidebar.workspaces',
      locale: NS,
      inject: () => ({
        openSession,
        archiveSession: archive,
        renameSession: rename,
        startModule,
      }),
    }, SessionBrowser)),
    'qingshui: session browser',
  )

  // Cold open: once the list is ready and nothing is selected, create a session.
  let bootstrapping = false
  let bootstrapped = false
  const maybeBootstrap = (): void => {
    if (bootstrapped || bootstrapping) return
    const list = ctx.sessions.list.getSnapshot()
    if (list.phase !== 'ready') return
    if (list.current !== undefined) {
      bootstrapped = true
      return
    }
    bootstrapping = true
    void createAndOpenSession(ctx.sessions)
      .then(() => { bootstrapped = true })
      .catch((error: unknown) => { console.warn('qingshui: cold-open bootstrap failed', error) })
      .finally(() => { bootstrapping = false })
  }

  ctx.effect(() => {
    maybeBootstrap()
    return ctx.sessions.list.subscribe(() => { maybeBootstrap() })
  }, 'qingshui: cold-open bootstrap')

  // Shadow ConversationRoot (priority -1). The shipped root stays registered
  // so it keeps declaring child seats; we graft those seats onto the winner.
  ctx.effect(() => installConversationShadow(ctx), 'qingshui: conversation shadow')

  // Shadow the assistant-step chat-node renderer (same priority mechanism)
  // to promote plain-text EV: citations into interactive evidence chips.
  ctx.effect(
    () => ctx.slots.inject('conversation.chat.node', function* () {
      yield ctx.slots.register(
        {
          name: 'conversation.chat.node',
          key: 'assistant-step',
          priority: -1,
          locale: 'conversation',
        },
        QsAssistantStepView,
      )
    }),
    'qingshui: assistant-step shadow',
  )

  // Keyed tool cards (kline / evidence / search / timeline) for the native
  // tools and their Data MCP twins.
  registerToolviews(ctx)
}
