/**
 * Qingshui research-shell browser half: flat session list in sidebar.workspaces,
 * cold-open / New chat → sessions.create({}) (no workspaceId).
 */
import { createAndOpenSession } from './session-actions.ts'
import { SessionBrowser } from './SessionBrowser.tsx'
import { en, zh, type QingshuiShellKey } from './locales.ts'
import { installClientStyles } from './theme.ts'

export type { QingshuiShellKey }

const NS = 'qingshui-shell'

/** Cordis inject: slots + sessions + workspaces + locale. */
export const inject = ['slots', 'sessions', 'workspaces', 'locale']

/**
 * Install research-shell UI.
 * @param ctx - client root context (loosely typed; matches MatDiscovery client style)
 */
export function apply(ctx: any): void {
  ctx.effect(() => installClientStyles(), 'qingshui: shell styles')
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

  const createSession = (): Promise<string> => createAndOpenSession(ctx.sessions)
  const openSession = (sessionId: string): void => { ctx.sessions.open(sessionId) }

  ctx.effect(
    () => ctx.slots.inject('sidebar.workspaces', () => ctx.slots.register({
      name: 'sidebar.workspaces',
      locale: NS,
      inject: () => ({
        createSession,
        openSession,
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
}
