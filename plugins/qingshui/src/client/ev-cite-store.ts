/**
 * Cross-node conduit for the EV citation affordance: MarkdownText renders
 * chips inside its own tree, so hover/click intent is funneled through this
 * module-scope bus and rendered as one layer (popover + pinned card) mounted
 * by the research conversation root. Plain state + emitter; React binds via
 * useSyncExternalStore in the layer.
 */

export type EvAnchor = { x: number; y: number; width: number; height: number }

export type EvCiteState = {
  mode: 'closed'
} | {
  mode: 'hover'
  id: string
  anchor: EvAnchor
} | {
  mode: 'pinned'
  id: string
}

type Listener = () => void

const listeners = new Set<Listener>()

let state: EvCiteState = { mode: 'closed' }

/** Stable snapshot source for useSyncExternalStore. @returns the current state. */
export function getEvCiteState(): EvCiteState {
  return state
}

/** Subscribe to state changes. @param fn - change callback. @returns unsubscribe. */
export function subscribeEvCite(fn: Listener): () => void {
  listeners.add(fn)
  return () => { listeners.delete(fn) }
}

function publish(next: EvCiteState): void {
  state = next
  for (const listener of [...listeners]) listener()
}

/** Show the hover preview for one chip. @param anchor - chip bounding rect. */
export function openEvHover(id: string, anchor: EvAnchor): void {
  if (state.mode === 'pinned') return
  if (state.mode === 'hover' && state.id === id && sameAnchor(state.anchor, anchor)) return
  publish({ mode: 'hover', id, anchor })
}

function sameAnchor(a: EvAnchor, b: EvAnchor): boolean {
  return a.x === b.x && a.y === b.y && a.width === b.width && a.height === b.height
}

/** Hide the hover preview (pinned card stays). */
export function closeEvHover(id?: string): void {
  if (state.mode !== 'hover') return
  if (id !== undefined && state.id !== id) return
  publish({ mode: 'closed' })
}

/** Pin the full evidence card. @param id - evidence id. */
export function pinEvEvidence(id: string): void {
  publish({ mode: 'pinned', id })
}

/** Close the pinned card. */
export function closeEvPinned(): void {
  if (state.mode !== 'pinned') return
  publish({ mode: 'closed' })
}

// ---- evidence fetch: same-origin host route, per-id cache + in-flight dedup ----

export type EvEvidence =
  | { status: 'loading' }
  | { status: 'error'; message: string; shortId?: boolean }
  | { status: 'ok'; doc: Record<string, unknown> }

const evidenceCache = new Map<string, EvEvidence>()

/** Cached lookup for one evidence id, kicking off a fetch when absent. */
export function getEvEvidence(id: string, fetchEv: (id: string) => Promise<{ status: 'ok'; doc: Record<string, unknown> } | { status: 'error'; message: string; shortId?: boolean }>): EvEvidence {
  const cached = evidenceCache.get(id)
  if (cached !== undefined) return cached
  void fetchEv(id)
    .then(result => { evidenceCache.set(id, result) })
    .catch((error: unknown) => {
      evidenceCache.set(id, { status: 'error', message: String((error as Error)?.message ?? error) })
    })
    .finally(() => { for (const listener of [...listeners]) listener() })
  const pending: EvEvidence = { status: 'loading' }
  evidenceCache.set(id, pending)
  return pending
}

/** Fetch one evidence doc through the host route. */
export async function fetchEvEvidence(id: string): Promise<{ status: 'ok'; doc: Record<string, unknown> } | { status: 'error'; message: string; shortId?: boolean }> {
  let res: Response
  try {
    res = await fetch(`/qingshui/evidence/${encodeURIComponent(id)}`)
  } catch {
    return { status: 'error', message: '无法连接本地知识路由（服务未启动或已断开）' }
  }
  let body: unknown
  try {
    body = await res.json()
  } catch {
    return { status: 'error', message: `证据路由响应异常（HTTP ${res.status}）` }
  }
  const payload = body as { ok?: boolean; doc?: Record<string, unknown>; error?: string }
  if (res.ok && payload?.ok === true && payload.doc !== undefined) {
    return { status: 'ok', doc: payload.doc }
  }
  const shortId = id.length < 67
  return {
    status: 'error',
    message: payload?.error ?? `证据未命中（HTTP ${res.status}）`,
    shortId,
  }
}

/** Drop the cached entry for one id (retry affordance). */
export function invalidateEvEvidence(id: string): void {
  evidenceCache.delete(id)
  for (const listener of [...listeners]) listener()
}
